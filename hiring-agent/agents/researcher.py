"""
agents/researcher.py
═══════════════════════════════════════════════════════
Researcher Agent for the Autonomous Hiring Agent.
Uses Groq compound-beta (built-in web search) to verify
and enrich applicant profiles from public sources.

Checks:
  - GitHub: repository count, recent activity, project quality
  - Portfolio / personal site: existence and content summary
  - Claims consistency: which skills can be verified online,
    whether stated experience is plausible
  - Any public red flags (conflicting dates, missing presence, etc.)

Runs after initial scoring and before the final orchestrator
decision, giving the scorer additional signal it couldn't derive
from the resume alone.

Usage:
    agent = ResearcherAgent()
    result = await agent.research(applicant)
    print(result.overall_credibility)      # 0–10
    print(result.verification.red_flags)   # list[str]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from groq import AsyncGroq

from models.applicant import Applicant
from utils.logger import logger
from utils.prompt_templates import RESEARCHER_SYSTEM, researcher_prompt
from utils.rate_limiter import DailyLimitExceededError, rate_limiter, with_retry

# Read at import time — load_dotenv() is always called first in main.py.
# Falls back to "compound-beta" if GROQ_RESEARCHER is not set.
RESEARCHER_MODEL = os.getenv("GROQ_RESEARCHER", "compound-beta")


# ─────────────────────────────────────────────────────
#  Result types
# ─────────────────────────────────────────────────────

@dataclass
class GitHubAnalysis:
    """Findings from the applicant's GitHub profile."""
    found:            bool
    repo_count:       int        = 0
    recent_activity:  str        = ""
    notable_projects: list[str]  = field(default_factory=list)
    quality_score:    float      = 0.0    # 0–10; 0 when not found


@dataclass
class PortfolioAnalysis:
    """Findings from the applicant's portfolio / personal site."""
    found:   bool
    summary: str = ""


@dataclass
class VerificationResult:
    """
    Cross-check between the applicant's stated profile and
    what the model actually found online.
    """
    skills_verified:       list[str] = field(default_factory=list)
    skills_not_found:      list[str] = field(default_factory=list)
    experience_consistent: bool      = True
    red_flags:             list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """
    Full output of the Researcher Agent for one applicant.

    Attributes:
        applicant_id        — links back to the Applicant record
        github_analysis     — GitHub presence and project quality
        portfolio_analysis  — portfolio site existence and summary
        verification        — skills / experience consistency check
        overall_credibility — 0–10 composite trust score
        notes               — freeform model notes (conflicts, highlights)
        error               — set when the research call failed entirely
    """
    applicant_id:        str
    github_analysis:     GitHubAnalysis     = field(
        default_factory=lambda: GitHubAnalysis(found=False)
    )
    portfolio_analysis:  PortfolioAnalysis  = field(
        default_factory=lambda: PortfolioAnalysis(found=False)
    )
    verification:        VerificationResult = field(default_factory=VerificationResult)
    overall_credibility: float              = 0.0
    notes:               str               = ""
    error:               Optional[str]     = None


# ─────────────────────────────────────────────────────
#  Agent
# ─────────────────────────────────────────────────────

class ResearcherAgent:
    """
    Verifies applicant profiles via compound-beta's built-in web search.

    compound-beta performs live searches as part of the completion call —
    no separate search tool call is required.

    Stateless — safe to reuse one instance across many applicants.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = RESEARCHER_MODEL

    # ─────────────────────────────────────────────────
    #  Groq API call
    # ─────────────────────────────────────────────────

    async def _call_groq(self, prompt: str) -> str:
        """Single research call with JSON response mode."""
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": RESEARCHER_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,   # deterministic — verification facts don't need randomness
            max_tokens=600,    # structured JSON verification; 800 was over-allocated
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    # ─────────────────────────────────────────────────
    #  JSON → ResearchResult
    # ─────────────────────────────────────────────────

    def _parse_response(self, raw: str, applicant_id: str) -> ResearchResult:
        """
        Parse the Groq JSON response into a ResearchResult.

        Raises json.JSONDecodeError on malformed JSON so the caller
        can surface a distinct error rather than a generic one.
        Missing keys fall back to safe defaults — a partial response
        is still more useful than nothing.
        """
        data = json.loads(raw)   # raises JSONDecodeError if invalid

        gh_raw = data.get("github_analysis") or {}
        github = GitHubAnalysis(
            found=bool(gh_raw.get("found", False)),
            repo_count=int(gh_raw.get("repo_count", 0)),
            recent_activity=str(gh_raw.get("recent_activity", "")),
            notable_projects=list(gh_raw.get("notable_projects") or []),
            quality_score=float(gh_raw.get("quality_score", 0.0)),
        )

        pf_raw = data.get("portfolio_analysis") or {}
        portfolio = PortfolioAnalysis(
            found=bool(pf_raw.get("found", False)),
            summary=str(pf_raw.get("summary", "")),
        )

        vr_raw = data.get("verification") or {}
        verification = VerificationResult(
            skills_verified=list(vr_raw.get("skills_verified") or []),
            skills_not_found=list(vr_raw.get("skills_not_found") or []),
            experience_consistent=bool(vr_raw.get("experience_consistent", True)),
            red_flags=list(vr_raw.get("red_flags") or []),
        )

        return ResearchResult(
            applicant_id=applicant_id,
            github_analysis=github,
            portfolio_analysis=portfolio,
            verification=verification,
            overall_credibility=float(data.get("overall_credibility", 0.0)),
            notes=str(data.get("notes", "")),
        )

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def research(self, applicant: Applicant) -> ResearchResult:
        """
        Research one applicant's online presence and verify their claims.

        Args:
            applicant — full applicant profile. Uses:
                          github_url, portfolio_url, linkedin_url (checked online)
                          skill_names(), total_experience_years()  (verified against findings)

        Returns:
            ResearchResult with github_analysis, portfolio_analysis,
            verification, overall_credibility, and notes.

            On JSON parse error: ResearchResult with error set and all
            analysis fields at safe defaults (found=False, empty lists).

            On any other API/runtime error: same safe-default ResearchResult
            with error set.

            Re-raises DailyLimitExceededError — quota exhausted, abort the run.
        """
        logger.info(
            f"RESEARCH | [{applicant.id}] {applicant.full_name} | "
            f"GitHub: {applicant.github_url or 'none'} | "
            f"Portfolio: {applicant.portfolio_url or 'none'} | "
            f"Skills claimed: {len(applicant.skills)}"
        )

        try:
            prompt = researcher_prompt(
                applicant_name=applicant.full_name,
                applicant_id=applicant.id,
                github_url=applicant.github_url,
                portfolio_url=applicant.portfolio_url,
                linkedin_url=applicant.linkedin_url,
                claimed_skills=applicant.skill_names(),
                claimed_experience_years=applicant.total_experience_years(),
            )

            raw = await with_retry(
                self._call_groq,
                prompt,
                max_retries=3,
                base_delay=2.0,
                model=self.model,
            )

            result = self._parse_response(raw, applicant.id)

        except DailyLimitExceededError:
            raise

        except json.JSONDecodeError as exc:
            logger.error(
                f"RESEARCH | JSON parse error for [{applicant.id}] "
                f"{applicant.full_name}: {exc}"
            )
            return ResearchResult(
                applicant_id=applicant.id,
                error=f"JSON parse error: {exc}",
            )

        except Exception as exc:
            logger.error(
                f"RESEARCH | Failed for [{applicant.id}] "
                f"{applicant.full_name}: {exc}"
            )
            return ResearchResult(
                applicant_id=applicant.id,
                error=str(exc),
            )

        _flags = result.verification.red_flags
        logger.info(
            f"RESEARCH | [{applicant.id}] {applicant.full_name} | "
            f"Credibility: {result.overall_credibility}/10 | "
            f"GitHub: {'✓' if result.github_analysis.found else '✗'} "
            f"(quality {result.github_analysis.quality_score}/10) | "
            f"Skills verified: {len(result.verification.skills_verified)} | "
            f"Red flags: {len(_flags)}"
        )
        if _flags:
            logger.warning(
                f"RESEARCH | [{applicant.id}] Red flags: {_flags}"
            )

        return result
