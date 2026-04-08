"""
pipelines/rank.py
═══════════════════════════════════════════════════════
Rank Pipeline for the Autonomous Hiring Agent.

Takes a list of ApplicantScore objects (from the ingest
pipeline or directly from ScorerAgent) and sorts them
into three bands:
  - shortlisted  — score >= SHORTLIST_THRESHOLD (default 65)
  - rejected     — score <  AUTO_REJECT_THRESHOLD (default 35)
  - on_hold      — everything in between

Also computes percentile ranks across all scored applicants.

Usage:
    pipeline = RankPipeline()
    result   = pipeline.run(scores)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models.score import ApplicantScore, ScoringStatus
from utils.logger import logger, log_shortlist, log_rejected

_DEFAULT_SHORTLIST_THRESHOLD    = 65.0
_DEFAULT_AUTO_REJECT_THRESHOLD  = 35.0


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
class RankResult:
    """
    Output of the RankPipeline.

    Attributes:
        shortlisted            — scores above shortlist threshold, sorted desc
        rejected               — scores below auto-reject threshold, sorted desc
        on_hold                — scores in the middle band, sorted desc
        failed                 — scoring errors (not ranked)
        skipped                — insufficient data (not ranked)
        stats                  — summary statistics dict
        shortlist_threshold    — threshold used for shortlisting
        auto_reject_threshold  — threshold used for auto-rejection
        total_input            — total scores received
        ranked_at              — timestamp of this ranking run
    """
    shortlisted:            list[ApplicantScore]    = field(default_factory=list)
    rejected:               list[ApplicantScore]    = field(default_factory=list)
    on_hold:                list[ApplicantScore]    = field(default_factory=list)
    failed:                 list[ApplicantScore]    = field(default_factory=list)
    skipped:                list[ApplicantScore]    = field(default_factory=list)
    stats:                  dict                    = field(default_factory=dict)
    shortlist_threshold:    float                   = _DEFAULT_SHORTLIST_THRESHOLD
    auto_reject_threshold:  float                   = _DEFAULT_AUTO_REJECT_THRESHOLD
    total_input:            int                     = 0
    ranked_at:              datetime                = field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        return (
            f"RankPipeline | Total: {self.total_input} | "
            f"Shortlisted: {len(self.shortlisted)} | "
            f"On Hold: {len(self.on_hold)} | "
            f"Rejected: {len(self.rejected)} | "
            f"Failed: {len(self.failed)} | "
            f"Skipped: {len(self.skipped)}"
        )

    def top_n(self, n: int = 10) -> list[ApplicantScore]:
        """Return top N shortlisted candidates."""
        return self.shortlisted[:n]


# ─────────────────────────────────────────────────────
#  Pipeline
# ─────────────────────────────────────────────────────

class RankPipeline:
    """
    Sorts ApplicantScore objects into shortlisted / on-hold / rejected bands.
    Computes percentile ranks and summary statistics.

    Synchronous — no I/O. Call run() directly (no await needed).
    """

    def run(
        self,
        scores: list[ApplicantScore],
        shortlist_threshold: Optional[float] = None,
        auto_reject_threshold: Optional[float] = None,
    ) -> RankResult:
        """
        Rank all applicants and return a RankResult.

        Args:
            scores                — list of ApplicantScore from ScorerAgent
            shortlist_threshold   — override env SHORTLIST_THRESHOLD
            auto_reject_threshold — override env AUTO_REJECT_THRESHOLD

        Returns:
            RankResult with sorted bands and percentile ranks assigned.
        """
        t_shortlist = shortlist_threshold or _shortlist_threshold()
        t_reject    = auto_reject_threshold or _auto_reject_threshold()

        result = RankResult(
            shortlist_threshold=t_shortlist,
            auto_reject_threshold=t_reject,
            total_input=len(scores),
        )

        logger.info(
            f"RANK | Starting | "
            f"Total: {len(scores)} | "
            f"Shortlist ≥ {t_shortlist} | "
            f"Auto-reject < {t_reject}"
        )

        # Separate completed scores from errors/skips
        completed = [
            s for s in scores
            if s.status == ScoringStatus.COMPLETED and s.final_score is not None
        ]
        result.failed  = [s for s in scores if s.status == ScoringStatus.FAILED]
        result.skipped = [s for s in scores if s.status == ScoringStatus.SKIPPED]

        # Sort completed by score descending
        completed.sort(key=lambda s: s.final_score or 0, reverse=True)

        # Assign global rank and percentile
        total_scored = len(completed)
        for rank_idx, score in enumerate(completed, start=1):
            score.rank       = rank_idx
            score.percentile = round(
                (1 - (rank_idx - 1) / total_scored) * 100, 1
            ) if total_scored > 1 else 100.0

        # Bucket into bands
        for score in completed:
            if score.is_shortlistable(t_shortlist):
                result.shortlisted.append(score)
                log_shortlist(score.applicant_id, score.applicant_name, score.final_score or 0)
            elif score.should_auto_reject(t_reject):
                result.rejected.append(score)
                log_rejected(score.applicant_id, score.applicant_name, score.final_score or 0)
            else:
                result.on_hold.append(score)
                logger.debug(
                    f"RANK | ON HOLD | [{score.applicant_id}] "
                    f"{score.applicant_name} | Score: {score.final_score}"
                )

        # Compute stats
        result.stats = self._compute_stats(completed, result, t_shortlist, t_reject)

        logger.info(f"RANK | Complete | {result.summary()}")
        return result

    # ─────────────────────────────────────────────────
    #  Stats helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _compute_stats(
        completed: list[ApplicantScore],
        result: RankResult,
        shortlist_threshold: float,
        reject_threshold: float,
    ) -> dict:
        """Build summary statistics dict for the result."""
        all_scores = [s.final_score for s in completed if s.final_score is not None]

        stats: dict = {
            "total_input":         result.total_input,
            "total_ranked":        len(completed),
            "total_failed":        len(result.failed),
            "total_skipped":       len(result.skipped),
            "shortlisted":         len(result.shortlisted),
            "on_hold":             len(result.on_hold),
            "rejected":            len(result.rejected),
            "shortlist_threshold": shortlist_threshold,
            "auto_reject_threshold": reject_threshold,
        }

        if all_scores:
            stats["highest_score"]  = max(all_scores)
            stats["lowest_score"]   = min(all_scores)
            stats["average_score"]  = round(sum(all_scores) / len(all_scores), 2)
            stats["median_score"]   = _median(all_scores)

        if completed:
            grade_dist: dict[str, int] = {}
            for s in completed:
                grade = s.grade.value if s.grade else "N/A"
                grade_dist[grade] = grade_dist.get(grade, 0) + 1
            stats["grade_distribution"] = grade_dist

        return stats


def _median(values: list[float]) -> float:
    """Compute the median of a list of floats."""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return round((sorted_vals[mid - 1] + sorted_vals[mid]) / 2, 2)
    return round(sorted_vals[mid], 2)
