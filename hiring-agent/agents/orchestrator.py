"""
agents/orchestrator.py
═══════════════════════════════════════════════════════
Orchestrator Agent for the Autonomous Hiring Agent.
Uses Groq llama-3.3-70b-versatile to make final
hire / reject / hold verdicts after scoring and interviews.

Inputs per decision:
  - ApplicantScore  (scoring agent output)
  - list[DetectionResult]  (detector agent output)
  - optional list of per-round interview scores

Output:
  OrchestratorDecision
    verdict     : "accept" | "reject" | "hold"
    confidence  : 0.0–1.0
    reason      : str
    next_action : "send_offer" | "send_rejection"
                  | "schedule_final_round" | "hold_for_review"

Fail-safe: any API or parse error returns "hold", never "reject".
Stateless — safe to reuse one instance across many applicants.

Usage:
    agent = OrchestratorAgent()
    decision = await agent.decide(applicant, score, detection_results)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from groq import AsyncGroq

from agents.detector import DetectionResult
from models.applicant import Applicant
from models.score import ApplicantScore
from utils.logger import logger
from utils.prompt_templates import ORCHESTRATOR_SYSTEM, orchestrator_decision_prompt
from utils.rate_limiter import DailyLimitExceededError, rate_limiter, with_retry

ORCHESTRATOR_MODEL = "llama-3.3-70b-versatile"


# ─────────────────────────────────────────────────────
#  Decision type
# ─────────────────────────────────────────────────────

@dataclass
class OrchestratorDecision:
    """
    Final hiring decision for one applicant.

    Attributes:
        applicant_id  — links back to the Applicant record
        verdict       — accept / reject / hold
        confidence    — 0.0–1.0 (model's self-reported certainty)
        reason        — brief human-readable explanation
        next_action   — concrete action to trigger downstream
        ai_flags      — number of responses flagged by the detector
        error         — set when the decision fell back to "hold" on error
    """
    applicant_id: str
    verdict:      str          # "accept" | "reject" | "hold"
    confidence:   float
    reason:       str
    next_action:  str          # "send_offer" | "send_rejection" | "schedule_final_round" | "hold_for_review"
    ai_flags:     int   = 0
    error:        str | None = None


# ─────────────────────────────────────────────────────
#  Agent
# ─────────────────────────────────────────────────────

class OrchestratorAgent:
    """
    Makes final hire / reject / hold verdicts.

    Stateless — no per-instance caches. One instance can be shared
    across many concurrent applicant pipelines.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = ORCHESTRATOR_MODEL

    # ─────────────────────────────────────────────────
    #  Groq API call
    # ─────────────────────────────────────────────────

    async def _call_groq(self, prompt: str) -> str:
        """Standalone decision call — no conversation history."""
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    # ─────────────────────────────────────────────────
    #  JSON → OrchestratorDecision
    # ─────────────────────────────────────────────────

    def _parse_response(
        self,
        raw: str,
        applicant_id: str,
        ai_flags: int,
    ) -> OrchestratorDecision:
        data = json.loads(raw)

        verdict     = data.get("verdict", "hold")
        confidence  = float(data.get("confidence", 0.5))
        reason      = data.get("reason", "")
        next_action = data.get("next_action", "hold_for_review")

        # Guard against unexpected model output — always safe-default
        if verdict not in ("accept", "reject", "hold"):
            logger.warning(
                f"ORCHESTRATOR | Unexpected verdict {verdict!r} — defaulting to 'hold'"
            )
            verdict     = "hold"
            next_action = "hold_for_review"

        if next_action not in (
            "send_offer", "send_rejection", "schedule_final_round", "hold_for_review"
        ):
            logger.warning(
                f"ORCHESTRATOR | Unexpected next_action {next_action!r} — defaulting to 'hold_for_review'"
            )
            next_action = "hold_for_review"

        return OrchestratorDecision(
            applicant_id=applicant_id,
            verdict=verdict,
            confidence=confidence,
            reason=reason,
            next_action=next_action,
            ai_flags=ai_flags,
        )

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def decide(
        self,
        applicant: Applicant,
        score: ApplicantScore,
        detection_results: list[DetectionResult],
        round_scores: list[float] | None = None,
    ) -> OrchestratorDecision:
        """
        Make a final hiring decision for one applicant.

        Args:
            applicant         — full applicant profile (for name, role, id)
            score             — output from ScorerAgent.score_applicant()
            detection_results — output from DetectorAgent.scan_session()
                                (pass [] if no interview was conducted)
            round_scores      — per-round interview scores, e.g. [72.0, 68.0, 81.0].
                                Pass None to omit from the prompt (pre-interview decisions).

        Returns:
            OrchestratorDecision with verdict, confidence, reason, next_action.
            On any API or parse error, returns a "hold" / "hold_for_review" decision
            — never rejects an applicant due to a system failure.

        Re-raises DailyLimitExceededError (quota exhausted — abort the run).
        """
        ai_flags = sum(1 for r in detection_results if r.flagged)

        try:
            prompt = orchestrator_decision_prompt(
                applicant_name=applicant.full_name,
                applicant_id=applicant.id,
                role=applicant.role_applied.value,
                score=score.final_score or 0.0,
                grade=score.grade.value if score.grade else "N/A",
                ai_flags=ai_flags,
                round_scores=round_scores or [],
                strengths=score.strengths or [],
                weaknesses=score.weaknesses or [],
            )

            raw = await with_retry(
                self._call_groq,
                prompt,
                max_retries=3,
                base_delay=2.0,
                model=self.model,
            )

            decision = self._parse_response(raw, applicant.id, ai_flags)

        except DailyLimitExceededError:
            raise

        except Exception as e:
            logger.error(
                f"ORCHESTRATOR | Decision failed for [{applicant.id}] "
                f"{applicant.full_name}: {e} — defaulting to 'hold'"
            )
            return OrchestratorDecision(
                applicant_id=applicant.id,
                verdict="hold",
                confidence=0.0,
                reason=f"System error — manual review required: {e}",
                next_action="hold_for_review",
                ai_flags=ai_flags,
                error=str(e),
            )

        logger.info(
            f"ORCHESTRATOR | [{applicant.id}] {applicant.full_name} | "
            f"verdict={decision.verdict} | "
            f"confidence={decision.confidence:.2f} | "
            f"action={decision.next_action} | "
            f"ai_flags={ai_flags} | "
            f"score={score.final_score or 0.0:.1f}"
        )

        return decision
