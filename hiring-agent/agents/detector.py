"""
agents/detector.py
═══════════════════════════════════════════════════════
AI Detection Agent for the Autonomous Hiring Agent.
Uses Groq llama-3.1-8b-instant (fastest/cheapest model)
to detect AI-generated or plagiarised interview responses.

Designed to run after every interview response — latency matters.

Usage:
    agent = DetectorAgent()

    # Single response
    result = await agent.detect(question, response, name, role, exp_years)

    # Full session scan
    results = await agent.scan_session(session, experience_years=3.0)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from groq import AsyncGroq

from models.applicant import AIDetectionVerdict
from models.interview import InterviewSession
from utils.logger import logger
from utils.prompt_templates import DETECTOR_SYSTEM, detector_prompt
from utils.rate_limiter import DailyLimitExceededError, rate_limiter, with_retry

DETECTOR_MODEL       = "llama-3.1-8b-instant"
_DEFAULT_THRESHOLD   = 0.75


def _threshold() -> float:
    """Read AI_DETECTION_THRESHOLD from env at call time (not import time)."""
    try:
        return float(os.getenv("AI_DETECTION_THRESHOLD", _DEFAULT_THRESHOLD))
    except ValueError:
        return _DEFAULT_THRESHOLD


# ─────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """
    Result of a single AI-detection analysis.

    Attributes:
        question_id  — links back to InterviewQuestion.question_id (None for ad-hoc calls)
        verdict      — clean / suspicious / ai_generated
        confidence   — 0.0–1.0 (model's self-reported certainty)
        signals      — specific signals the model identified
        reasoning    — 1–2 sentence explanation
        flagged      — True when confidence >= AI_DETECTION_THRESHOLD
    """
    question_id: str | None
    verdict:     AIDetectionVerdict
    confidence:  float
    signals:     list[str] = field(default_factory=list)
    reasoning:   str       = ""
    flagged:     bool      = False


# ─────────────────────────────────────────────────────
#  Agent
# ─────────────────────────────────────────────────────

class DetectorAgent:
    """
    Analyses interview responses for AI generation or plagiarism.

    Each public method is async and stateless — no per-instance caches.
    All errors on a single response are caught and returned as a
    SUSPICIOUS verdict (conservative — never silently drops a flag).

    Re-raises DailyLimitExceededError so the caller can abort.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = DETECTOR_MODEL

    # ─────────────────────────────────────────────────
    #  Groq API call
    # ─────────────────────────────────────────────────

    async def _call_groq(self, prompt: str) -> str:
        """Single-shot classification call. No conversation history needed."""
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DETECTOR_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    # ─────────────────────────────────────────────────
    #  JSON → DetectionResult
    # ─────────────────────────────────────────────────

    def _parse_response(
        self,
        raw: str,
        question_id: str | None,
    ) -> DetectionResult:
        data       = json.loads(raw)
        verdict    = AIDetectionVerdict(data.get("verdict", AIDetectionVerdict.SUSPICIOUS))
        confidence = float(data.get("confidence", 0.5))
        signals    = data.get("signals", [])
        reasoning  = data.get("reasoning", "")
        flagged    = confidence >= _threshold()
        return DetectionResult(
            question_id=question_id,
            verdict=verdict,
            confidence=confidence,
            signals=signals,
            reasoning=reasoning,
            flagged=flagged,
        )

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def detect(
        self,
        question: str,
        response: str,
        applicant_name: str,
        role: str,
        experience_years: float = 0.0,
        question_id: str | None = None,
    ) -> DetectionResult:
        """
        Analyse a single question + response pair.

        Returns SUSPICIOUS with confidence 0.5 on any API or parse error
        rather than silently passing a response — fail-safe over fail-open.
        Re-raises DailyLimitExceededError.
        """
        try:
            prompt = detector_prompt(
                question=question,
                response=response,
                applicant_name=applicant_name,
                role=role,
                experience_years=experience_years,
            )
            raw = await with_retry(
                self._call_groq,
                prompt,
                max_retries=3,
                base_delay=1.0,
                model=self.model,
            )
            result = self._parse_response(raw, question_id)

        except DailyLimitExceededError:
            raise

        except Exception as e:
            logger.error(
                f"DETECT | Parse/API error for question {question_id!r}: {e}"
            )
            result = DetectionResult(
                question_id=question_id,
                verdict=AIDetectionVerdict.SUSPICIOUS,
                confidence=0.5,
                reasoning=f"Detection failed: {e}",
                flagged=False,
            )

        if result.flagged:
            logger.warning(
                f"DETECT | FLAGGED | question={question_id!r} | "
                f"verdict={result.verdict.value} | "
                f"confidence={result.confidence:.2f} | "
                f"signals={result.signals}"
            )
        else:
            logger.debug(
                f"DETECT | {result.verdict.value} | "
                f"confidence={result.confidence:.2f} | "
                f"question={question_id!r}"
            )

        return result

    async def scan_session(
        self,
        session: InterviewSession,
        experience_years: float = 0.0,
    ) -> list[DetectionResult]:
        """
        Scan every answered question in the session sequentially.

        Pairs session.questions[i] with session.responses[i].
        Stops at whichever list is shorter (unanswered questions are skipped).
        Each response is analysed independently — one error never skips others.

        Returns one DetectionResult per answered question, in order.
        Re-raises DailyLimitExceededError (quota exhausted — abort the run).
        """
        pairs   = zip(session.questions, session.responses)
        results: list[DetectionResult] = []

        for question, response in pairs:
            result = await self.detect(
                question=question.question_text,
                response=response.response_text,
                applicant_name=session.applicant_name,
                role=session.role_applied,
                experience_years=experience_years,
                question_id=question.question_id,
            )
            results.append(result)

        total_flagged = sum(1 for r in results if r.flagged)
        if total_flagged:
            logger.warning(
                f"DETECT | Session {session.session_id} | "
                f"{total_flagged}/{len(results)} responses flagged"
            )
        else:
            logger.info(
                f"DETECT | Session {session.session_id} | "
                f"All {len(results)} responses clean"
            )

        return results
