"""
agents/scorer.py
═══════════════════════════════════════════════════════
Scorer Agent for the Autonomous Hiring Agent.
Uses Groq llama-3.3-70b-versatile to evaluate tech
applicants across 5 weighted dimensions.

Processes applicants in batches of 50.
Errors per applicant are isolated — one failure never
crashes the batch.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from groq import AsyncGroq

from models.applicant import Applicant
from models.score import (
    ApplicantScore,
    BatchScoringResult,
    DimensionScore,
    ScoringDimension,
    ScoringStatus,
)
from utils.logger import (
    log_api_error,
    log_batch_complete,
    log_batch_start,
    log_score,
    logger,
)
from utils.prompt_templates import SCORER_SYSTEM, scorer_prompt
from utils.rate_limiter import (
    DailyLimitExceededError,
    batch_delay,
    rate_limiter,
    with_retry,
)

SCORER_MODEL = "llama-3.3-70b-versatile"
BATCH_SIZE   = 50


class ScorerAgent:
    """
    Scores tech applicants using Groq llama-3.3-70b-versatile.

    Usage:
        agent = ScorerAgent()
        results = await agent.score_all(applicants)   # list[BatchScoringResult]
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = SCORER_MODEL

    # ─────────────────────────────────────────────────
    #  Internal Groq call
    # ─────────────────────────────────────────────────

    async def _call_groq(self, prompt: str) -> str:
        """Call Groq and return raw response content."""
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SCORER_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    # ─────────────────────────────────────────────────
    #  JSON → ApplicantScore
    # ─────────────────────────────────────────────────

    def _parse_response(self, raw: str, score: ApplicantScore) -> ApplicantScore:
        """
        Parse the Groq JSON response into ApplicantScore fields.
        Raises on malformed JSON or missing dimensions.
        """
        data = json.loads(raw)

        dimensions = data.get("dimensions")
        if not dimensions:
            raise ValueError("Groq response missing 'dimensions' field")

        score.dimension_scores = [
            DimensionScore(
                dimension=ScoringDimension(dim["dimension"]),
                score=float(dim["score"]),
                weight=float(dim["weight"]),
                reasoning=dim.get("reasoning", "No reasoning provided."),
                red_flags=dim.get("red_flags", []),
            )
            for dim in dimensions
        ]
        score.strengths       = data.get("strengths", [])
        score.weaknesses      = data.get("weaknesses", [])
        score.overall_summary = data.get("overall_summary")
        score.recommendation  = data.get("recommendation")
        return score

    # ─────────────────────────────────────────────────
    #  Single applicant
    # ─────────────────────────────────────────────────

    async def score_applicant(self, applicant: Applicant) -> ApplicantScore:
        """
        Score one applicant.
        Returns SKIPPED if there is not enough data.
        Returns FAILED on API or parse errors (does not re-raise).
        Re-raises DailyLimitExceededError so the caller can abort.
        """
        score = ApplicantScore(
            applicant_id=applicant.id,
            applicant_name=applicant.full_name,
            status=ScoringStatus.IN_PROGRESS,
        )

        if not applicant.skills and not applicant.resume_text and not applicant.work_experience:
            score.status        = ScoringStatus.SKIPPED
            score.error_message = "Insufficient profile data to score"
            logger.warning(
                f"SCORE | Skipping [{applicant.id}] {applicant.full_name} — no scorable data"
            )
            return score

        try:
            prompt = scorer_prompt(
                applicant_id=applicant.id,
                name=applicant.full_name,
                role=applicant.role_applied.value,
                experience_years=applicant.total_experience_years(),
                skills=applicant.skill_names(),
                work_experience=[we.model_dump() for we in applicant.work_experience],
                github_url=applicant.github_url,
                portfolio_url=applicant.portfolio_url,
                cover_letter=applicant.cover_letter,
                education=applicant.education,
                resume_text=applicant.resume_text,
            )

            raw = await with_retry(
                self._call_groq,
                prompt,
                max_retries=3,
                base_delay=2.0,
                model=self.model,
            )

            self._parse_response(raw, score)
            score.compute_final_score()
            log_score(
                applicant.id,
                applicant.full_name,
                score.final_score,
                score.grade.value,
            )

        except DailyLimitExceededError:
            raise  # abort the whole run — quota exhausted for today

        except Exception as e:
            score.status        = ScoringStatus.FAILED
            score.error_message = str(e)
            log_api_error("scorer", str(e))
            logger.error(
                f"SCORE | FAILED [{applicant.id}] {applicant.full_name} | {e}"
            )

        return score

    # ─────────────────────────────────────────────────
    #  Batch (≤ 50 applicants)
    # ─────────────────────────────────────────────────

    async def score_batch(
        self,
        applicants: list[Applicant],
        batch_id: str | None = None,
    ) -> BatchScoringResult:
        """Score a single batch of up to BATCH_SIZE applicants."""
        batch_id = batch_id or str(uuid.uuid4())[:8].upper()
        result   = BatchScoringResult(batch_id=batch_id, batch_size=len(applicants))

        log_batch_start(batch_id, len(applicants))

        for applicant in applicants:
            score = await self.score_applicant(applicant)
            result.scores.append(score)

        result.compute_stats()
        log_batch_complete(
            batch_id,
            result.total_scored,
            result.total_failed,
            result.average_score or 0.0,
        )
        return result

    # ─────────────────────────────────────────────────
    #  Full run (1000+ applicants)
    # ─────────────────────────────────────────────────

    async def score_all(self, applicants: list[Applicant]) -> list[BatchScoringResult]:
        """
        Score all applicants, chunked into batches of BATCH_SIZE.
        A 5-second delay is inserted between batches to avoid
        burning through the daily Groq quota too quickly.
        """
        batches = [
            applicants[i : i + BATCH_SIZE]
            for i in range(0, len(applicants), BATCH_SIZE)
        ]
        logger.info(
            f"SCORE | Starting full run | "
            f"{len(applicants)} applicants | "
            f"{len(batches)} batch(es) of up to {BATCH_SIZE}"
        )

        results: list[BatchScoringResult] = []
        for idx, batch in enumerate(batches):
            await batch_delay(idx)
            batch_result = await self.score_batch(batch)
            results.append(batch_result)

        total_scored  = sum(r.total_scored  for r in results)
        total_failed  = sum(r.total_failed  for r in results)
        total_skipped = sum(r.total_skipped for r in results)
        logger.info(
            f"SCORE | Full run complete | "
            f"Scored: {total_scored} | "
            f"Failed: {total_failed} | "
            f"Skipped: {total_skipped}"
        )
        return results
