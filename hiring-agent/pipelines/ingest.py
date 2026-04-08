"""
pipelines/ingest.py
═══════════════════════════════════════════════════════
Ingest Pipeline for the Autonomous Hiring Agent.

Orchestrates the full applicant intake flow:
  1. Accept raw applicant data (CSV or portal)
  2. Parse resume if resume_url / resume bytes present
  3. Score each applicant via ScorerAgent
  4. Store results in PageIndexStore
  5. Return IngestPipelineResult with shortlist breakdown

Errors are isolated per applicant — one failure never
aborts the whole batch.

Usage:
    pipeline = IngestPipeline()
    result = await pipeline.run_from_csv(file_bytes, file_type="csv")
    result = await pipeline.run_from_applicants(applicants)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime

from agents.scorer import ScorerAgent
from connectors.csv_ingestor import IngestResult, csv_ingestor
from memory.pageindex_store import PageIndexStore
from models.applicant import Applicant, ApplicationStatus
from models.score import ApplicantScore, ScoringStatus
from utils.logger import logger

_DEFAULT_MAX_APPLICANTS = 1000
_DEFAULT_SHORTLIST_THRESHOLD = 65.0
_DEFAULT_AUTO_REJECT_THRESHOLD = 35.0


def _max_applicants() -> int:
    try:
        return int(os.getenv("MAX_APPLICANTS", _DEFAULT_MAX_APPLICANTS))
    except ValueError:
        return _DEFAULT_MAX_APPLICANTS


def _shortlist_threshold() -> float:
    try:
        return float(os.getenv("SHORTLIST_THRESHOLD", _DEFAULT_SHORTLIST_THRESHOLD))
    except ValueError:
        return _DEFAULT_SHORTLIST_THRESHOLD


def _auto_reject_threshold() -> float:
    try:
        return float(os.getenv("AUTO_REJECT_THRESHOLD", _DEFAULT_AUTO_REJECT_THRESHOLD))
    except ValueError:
        return _DEFAULT_AUTO_REJECT_THRESHOLD


# ─────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────

@dataclass
class IngestPipelineResult:
    """
    Full result of running the ingest pipeline.

    Attributes:
        total_applicants  — total input applicants processed
        scores            — all ApplicantScore objects (one per applicant)
        shortlisted       — applicants who passed shortlist threshold
        rejected          — applicants below auto-reject threshold
        on_hold           — applicants in the middle band
        failed            — applicants where scoring failed
        skipped           — applicants with insufficient data
        started_at        — pipeline start time
        completed_at      — pipeline end time
    """
    total_applicants:   int                     = 0
    scores:             list[ApplicantScore]    = field(default_factory=list)
    shortlisted:        list[ApplicantScore]    = field(default_factory=list)
    rejected:           list[ApplicantScore]    = field(default_factory=list)
    on_hold:            list[ApplicantScore]    = field(default_factory=list)
    failed:             list[ApplicantScore]    = field(default_factory=list)
    skipped:            list[ApplicantScore]    = field(default_factory=list)
    started_at:         datetime                = field(default_factory=datetime.utcnow)
    completed_at:       datetime | None         = None

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None

    def summary(self) -> str:
        return (
            f"IngestPipeline | Total: {self.total_applicants} | "
            f"Shortlisted: {len(self.shortlisted)} | "
            f"Rejected: {len(self.rejected)} | "
            f"On Hold: {len(self.on_hold)} | "
            f"Failed: {len(self.failed)} | "
            f"Skipped: {len(self.skipped)} | "
            f"Duration: {self.duration_seconds}s"
        )


# ─────────────────────────────────────────────────────
#  Pipeline
# ─────────────────────────────────────────────────────

class IngestPipeline:
    """
    Orchestrates applicant intake: ingest → score → index.

    One IngestPipeline instance can be reused across multiple runs.
    It holds a ScorerAgent and a PageIndexStore; both are stateless
    with respect to individual applicants.
    """

    def __init__(
        self,
        page_index: PageIndexStore | None = None,
        scorer: ScorerAgent | None = None,
    ) -> None:
        self.scorer     = scorer or ScorerAgent()
        self.page_index = page_index or PageIndexStore()

    # ─────────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────────

    def _bucket_score(
        self,
        score: ApplicantScore,
        result: IngestPipelineResult,
        shortlist_threshold: float,
        auto_reject_threshold: float,
    ) -> None:
        """Sort a completed score into shortlisted / rejected / on_hold."""
        if score.status == ScoringStatus.FAILED:
            result.failed.append(score)
        elif score.status == ScoringStatus.SKIPPED:
            result.skipped.append(score)
        elif score.is_shortlistable(shortlist_threshold):
            result.shortlisted.append(score)
        elif score.should_auto_reject(auto_reject_threshold):
            result.rejected.append(score)
        else:
            result.on_hold.append(score)

    def _update_applicant_status(
        self,
        applicant: Applicant,
        score: ApplicantScore,
        shortlist_threshold: float,
        auto_reject_threshold: float,
    ) -> Applicant:
        """Update applicant status based on their score bucket."""
        if score.is_shortlistable(shortlist_threshold):
            applicant.status = ApplicationStatus.SHORTLISTED
        elif score.should_auto_reject(auto_reject_threshold):
            applicant.status = ApplicationStatus.REJECTED
        else:
            applicant.status = ApplicationStatus.ON_HOLD
        return applicant

    # ─────────────────────────────────────────────────
    #  Core scoring loop
    # ─────────────────────────────────────────────────

    async def _score_and_index(
        self,
        applicants: list[Applicant],
        result: IngestPipelineResult,
    ) -> None:
        """
        Score all applicants via ScorerAgent batch runs,
        then index them in PageIndexStore.

        One failure per applicant never stops the batch.
        DailyLimitExceededError propagates to the caller.
        """
        shortlist_t = _shortlist_threshold()
        reject_t    = _auto_reject_threshold()

        # Run all batches
        batch_results = await self.scorer.score_all(applicants)

        # Flatten all scores from all batches
        all_scores: list[ApplicantScore] = []
        for batch in batch_results:
            all_scores.extend(batch.scores)
        result.scores = all_scores

        # Build a lookup for quick access
        score_by_id = {s.applicant_id: s for s in all_scores}

        for applicant in applicants:
            score = score_by_id.get(applicant.id)
            if not score:
                logger.warning(
                    f"INGEST | No score returned for [{applicant.id}] — skipping index"
                )
                continue

            # Bucket the score + update applicant status
            self._bucket_score(score, result, shortlist_t, reject_t)
            self._update_applicant_status(applicant, score, shortlist_t, reject_t)

            # Index in PageIndexStore
            self.page_index.add_applicant(applicant, score=score)

        logger.info(f"INGEST | Scoring & indexing complete | {result.summary()}")

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def run_from_applicants(
        self,
        applicants: list[Applicant],
    ) -> IngestPipelineResult:
        """
        Run the ingest pipeline on a pre-built list of Applicant objects.

        Use this when applicants come from the FastAPI portal
        (already parsed by portal_api.py) or from any other source.

        Args:
            applicants — list of validated Applicant models

        Returns:
            IngestPipelineResult with full breakdown.
        """
        result = IngestPipelineResult(total_applicants=len(applicants))

        # Enforce MAX_APPLICANTS cap
        max_cap = _max_applicants()
        if len(applicants) > max_cap:
            logger.warning(
                f"INGEST | Capping at {max_cap} applicants "
                f"(received {len(applicants)})"
            )
            applicants = applicants[:max_cap]
            result.total_applicants = len(applicants)

        logger.info(
            f"INGEST | Pipeline started | "
            f"Applicants: {result.total_applicants} | "
            f"Shortlist threshold: {_shortlist_threshold()} | "
            f"Auto-reject threshold: {_auto_reject_threshold()}"
        )

        await self._score_and_index(applicants, result)
        result.completed_at = datetime.utcnow()
        logger.info(f"INGEST | Pipeline complete | {result.summary()}")
        return result

    async def run_from_csv(
        self,
        file_bytes: bytes,
        file_type: str = "csv",
        source_label: str = "csv_upload",
    ) -> IngestPipelineResult:
        """
        Ingest applicants from a CSV or Excel file, then score them.

        Args:
            file_bytes   — raw file bytes
            file_type    — "csv", "xlsx", or "xls"
            source_label — label shown in logs (e.g. "internshala_export")

        Returns:
            IngestPipelineResult with full breakdown.
        """
        logger.info(
            f"INGEST | CSV ingest started | "
            f"Type: {file_type} | Source: {source_label}"
        )

        ingest_result: IngestResult = await asyncio.to_thread(
            csv_ingestor.ingest,
            file_bytes,
            file_type,
            source_label,
        )

        if not ingest_result.applicants:
            logger.warning(
                f"INGEST | No valid applicants parsed from {source_label} | "
                f"Errors: {ingest_result.error_count}"
            )
            result = IngestPipelineResult(total_applicants=0)
            result.completed_at = datetime.utcnow()
            return result

        logger.info(
            f"INGEST | CSV parsed | {ingest_result.summary()}"
        )
        return await self.run_from_applicants(ingest_result.applicants)
