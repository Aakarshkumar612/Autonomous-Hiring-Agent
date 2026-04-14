"""
pipelines/proctoring_pipeline.py
═══════════════════════════════════════════════════════
Silent proctoring pipeline — manages per-session monitoring state
and assembles post-interview reports for recruiters.

Lifecycle:
  1. start_session()      → called when DSA session begins
  2. record_events()      → called in batches as frontend sends events
  3. record_submission()  → called when candidate submits code (updates metrics)
  4. generate_report()    → called after session ends; runs Groq analysis
  5. get_report()         → called by recruiter dashboard endpoint

All state is in-memory dicts keyed by session_id.
No shared mutable data between sessions — safe for concurrent use.

Ranking:
  After generate_report() all sessions for a recruiter are re-ranked by
  code_score_pct descending. Rank 1 = highest score.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from agents.silent_proctor import SilentProctorAgent
from models.proctoring import (
    ProctoringReport,
    QuestionMetrics,
    SilentEvent,
    SilentEventType,
)
from utils.logger import logger


class _SessionState:
    """Per-session mutable container. Not a Pydantic model — mutated in place."""

    def __init__(
        self,
        session_id:   str,
        applicant_id: str,
        recruiter_id: str,
        problem_id:   str,
        problem_title: str,
        started_at:   datetime,
    ) -> None:
        self.session_id    = session_id
        self.applicant_id  = applicant_id
        self.recruiter_id  = recruiter_id
        self.problem_id    = problem_id
        self.problem_title = problem_title
        self.started_at    = started_at
        self.ended_at: Optional[datetime] = None

        # Accumulated events from frontend (ordered by timestamp)
        self.events: list[SilentEvent] = []

        # Tracking tab-hidden timestamp for computing duration_away_ms
        self._last_hidden_at: Optional[datetime] = None

        # Submission tracking
        self.submission_attempts    = 0
        self.best_score_pct: float  = 0.0
        self.first_keystroke: Optional[datetime] = None
        self.last_submission: Optional[datetime] = None

        # Code score from DSA pipeline
        self.code_score_pct: float = 0.0

        # Applicant name (populated from applicant store if available)
        self.applicant_name: str = "Unknown Candidate"


class ProctoringPipeline:
    """
    Manages silent monitoring across all concurrent DSA sessions.

    One instance is shared (stateless pipeline, stateful dicts).
    """

    def __init__(self) -> None:
        self._agent   = SilentProctorAgent()
        # session_id → _SessionState
        self._sessions: dict[str, _SessionState] = {}
        # session_id → ProctoringReport (cached after generation)
        self._reports:  dict[str, ProctoringReport] = {}
        # recruiter_id → list[session_id]
        self._recruiter_sessions: dict[str, list[str]] = {}

    # ── Session lifecycle ─────────────────────────────

    def start_session(
        self,
        session_id:    str,
        applicant_id:  str,
        recruiter_id:  str,
        problem_id:    str,
        problem_title: str,
        applicant_name: str = "Unknown Candidate",
    ) -> None:
        """Register a new DSA session for silent monitoring."""
        state = _SessionState(
            session_id=session_id,
            applicant_id=applicant_id,
            recruiter_id=recruiter_id,
            problem_id=problem_id,
            problem_title=problem_title,
            started_at=datetime.utcnow(),
        )
        state.applicant_name = applicant_name
        self._sessions[session_id] = state

        # Index under recruiter for ranking
        if recruiter_id not in self._recruiter_sessions:
            self._recruiter_sessions[recruiter_id] = []
        if session_id not in self._recruiter_sessions[recruiter_id]:
            self._recruiter_sessions[recruiter_id].append(session_id)

        logger.info(
            f"PROCTOR_PIPELINE | session started | {session_id} | {applicant_id}"
        )

    def record_events(
        self,
        session_id: str,
        raw_events: list[dict],
    ) -> int:
        """
        Accept a batch of raw event dicts from the frontend.
        Returns count of events successfully recorded.

        Each dict must have: event_type (str), timestamp (ISO str),
        and optional: duration_away_ms, paste_length, paste_preview, detail.
        """
        state = self._sessions.get(session_id)
        if not state:
            logger.warning(f"PROCTOR_PIPELINE | record_events | unknown session: {session_id}")
            return 0

        recorded = 0
        for raw in raw_events:
            try:
                event_type_str = raw.get("event_type", "")
                try:
                    event_type = SilentEventType(event_type_str)
                except ValueError:
                    continue

                ts_raw = raw.get("timestamp")
                ts = (
                    datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if ts_raw else datetime.utcnow()
                )

                event = SilentEvent(
                    id=f"sev_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    applicant_id=state.applicant_id,
                    event_type=event_type,
                    timestamp=ts,
                    duration_away_ms=raw.get("duration_away_ms"),
                    paste_length=raw.get("paste_length"),
                    paste_preview=raw.get("paste_preview"),
                    detail=str(raw.get("detail", "")),
                )

                # Track duration: pair TAB_HIDDEN → TAB_VISIBLE
                if event_type == SilentEventType.TAB_HIDDEN:
                    state._last_hidden_at = ts
                elif event_type == SilentEventType.TAB_VISIBLE:
                    if state._last_hidden_at and not event.duration_away_ms:
                        diff_ms = int((ts - state._last_hidden_at).total_seconds() * 1000)
                        event.duration_away_ms = diff_ms
                    state._last_hidden_at = None

                # Track first keystroke proxy (first RAPID_INPUT or PASTE)
                if (
                    event_type in (SilentEventType.RAPID_INPUT, SilentEventType.PASTE_DETECTED, SilentEventType.LARGE_PASTE)
                    and state.first_keystroke is None
                ):
                    state.first_keystroke = ts

                state.events.append(event)
                recorded += 1

            except Exception as exc:
                logger.warning(f"PROCTOR_PIPELINE | bad event payload: {exc} | raw={raw}")

        logger.info(f"PROCTOR_PIPELINE | {session_id} | recorded {recorded} events")
        return recorded

    def record_submission(
        self,
        session_id:    str,
        score_pct:     float,
        submitted_at:  Optional[datetime] = None,
    ) -> None:
        """
        Called each time the candidate submits code.
        Updates best score and attempt count for the session.
        """
        state = self._sessions.get(session_id)
        if not state:
            return

        state.submission_attempts += 1
        state.last_submission = submitted_at or datetime.utcnow()
        if score_pct > state.best_score_pct:
            state.best_score_pct = score_pct

        state.code_score_pct = state.best_score_pct
        logger.info(
            f"PROCTOR_PIPELINE | submission | {session_id} | "
            f"attempt={state.submission_attempts} | score={score_pct:.1f}%"
        )

    # ── Report generation ─────────────────────────────

    def generate_report(
        self,
        session_id: str,
        ended_at:   Optional[datetime] = None,
    ) -> Optional[ProctoringReport]:
        """
        Generate and cache the proctoring report for one session.
        Triggers Groq analysis. Safe to call multiple times (cached).
        """
        # Return cached report if already generated
        if session_id in self._reports:
            return self._reports[session_id]

        state = self._sessions.get(session_id)
        if not state:
            logger.warning(f"PROCTOR_PIPELINE | generate_report | unknown session: {session_id}")
            return None

        state.ended_at = ended_at or datetime.utcnow()
        duration_ms = int(
            (state.ended_at - state.started_at).total_seconds() * 1000
        )

        # Build question metrics (one problem per DSA session currently)
        qm = self._build_question_metrics(state)

        # Rank this session among the recruiter's sessions
        rank, total, percentile = self._compute_ranking(
            session_id=session_id,
            recruiter_id=state.recruiter_id,
            this_score=state.code_score_pct,
        )

        report = self._agent.build_report(
            session_id=session_id,
            applicant_id=state.applicant_id,
            applicant_name=state.applicant_name,
            recruiter_id=state.recruiter_id,
            session_duration_ms=duration_ms,
            events=list(state.events),
            question_metrics=qm,
            code_score_pct=state.code_score_pct,
            rank=rank,
            total_candidates=total,
            percentile=percentile,
        )

        self._reports[session_id] = report
        logger.info(
            f"PROCTOR_PIPELINE | report generated | {session_id} | "
            f"risk={report.risk.risk_level.value if report.risk else 'n/a'}"
        )
        return report

    def get_report(self, session_id: str) -> Optional[ProctoringReport]:
        """Return a cached report, or None if not yet generated."""
        return self._reports.get(session_id)

    # ── Recruiter-level aggregation ───────────────────

    def get_recruiter_summary(self, recruiter_id: str) -> dict:
        """
        Aggregate data for all sessions belonging to one recruiter.
        Used by the dashboard data endpoint.
        """
        session_ids = self._recruiter_sessions.get(recruiter_id, [])
        candidates  = []

        for sid in session_ids:
            report = self._reports.get(sid)
            state  = self._sessions.get(sid)

            if report:
                risk = report.risk
                candidates.append({
                    "session_id":             report.session_id,
                    "applicant_id":           report.applicant_id,
                    "applicant_name":         report.applicant_name,
                    "started_at":             report.generated_at.isoformat(),
                    "session_duration_ms":    report.session_duration_ms,
                    "code_score_pct":         report.code_score_pct,
                    "risk_level":             risk.risk_level.value if risk else "low",
                    "risk_score":             risk.risk_score if risk else 0,
                    "tab_switch_count":       risk.tab_switch_count if risk else 0,
                    "total_away_time_ms":     risk.total_away_time_ms if risk else 0,
                    "suspicious_paste_count": risk.suspicious_paste_count if risk else 0,
                    "window_blur_count":      risk.window_blur_count if risk else 0,
                    "rapid_input_events":     risk.rapid_input_events if risk else 0,
                    "devtools_detected":      risk.devtools_detected if risk else False,
                    "rank":                   report.rank,
                    "total_candidates":       report.total_candidates,
                    "percentile":             report.percentile,
                    "behavioral_summary":     report.behavioral_summary,
                    "red_flags":              report.red_flags,
                    "recommendations":        report.recommendations,
                    "events": [
                        {
                            "event_type":     e.event_type.value,
                            "timestamp":      e.timestamp.isoformat(),
                            "duration_away_ms": e.duration_away_ms,
                            "paste_length":   e.paste_length,
                            "detail":         e.detail,
                        }
                        for e in report.events
                    ],
                })
            elif state:
                # Session exists but report not generated yet
                candidates.append({
                    "session_id":   sid,
                    "applicant_id": state.applicant_id,
                    "applicant_name": state.applicant_name,
                    "started_at":   state.started_at.isoformat(),
                    "code_score_pct": state.code_score_pct,
                    "risk_level":   "pending",
                    "risk_score":   0,
                    "report_ready": False,
                })

        # Sort by code score descending
        candidates.sort(key=lambda c: c.get("code_score_pct", 0), reverse=True)

        flagged = sum(
            1 for c in candidates
            if c.get("risk_level") in ("high", "critical")
        )
        scores = [c["code_score_pct"] for c in candidates if "code_score_pct" in c]

        return {
            "recruiter_id":       recruiter_id,
            "total_sessions":     len(candidates),
            "flagged_sessions":   flagged,
            "average_score":      round(sum(scores) / len(scores), 1) if scores else 0,
            "candidates":         candidates,
        }

    # ── Internal helpers ──────────────────────────────

    def _build_question_metrics(self, state: _SessionState) -> list[QuestionMetrics]:
        """Build QuestionMetrics from events for the single problem in this session."""
        total_away_ms = sum(
            (ev.duration_away_ms or 0)
            for ev in state.events
            if ev.event_type == SilentEventType.TAB_VISIBLE and ev.duration_away_ms
        )
        session_ms = 0
        if state.ended_at:
            session_ms = int((state.ended_at - state.started_at).total_seconds() * 1000)

        active_ms = max(session_ms - total_away_ms, 0)

        # Suspiciously fast: submitted within 2 min of starting for any problem
        suspiciously_fast = (
            state.last_submission is not None
            and state.submission_attempts > 0
            and (state.last_submission - state.started_at).total_seconds() < 120
            and state.code_score_pct >= 90
        )

        return [
            QuestionMetrics(
                problem_id=state.problem_id,
                problem_title=state.problem_title,
                time_started=state.started_at,
                time_first_keystroke=state.first_keystroke,
                time_submitted=state.last_submission,
                active_time_ms=active_ms,
                away_time_ms=total_away_ms,
                submission_attempts=state.submission_attempts,
                best_score_pct=state.best_score_pct,
                solved=state.best_score_pct >= 100.0,
                suspiciously_fast=suspiciously_fast,
            )
        ]

    def _compute_ranking(
        self,
        session_id:  str,
        recruiter_id: str,
        this_score:  float,
    ) -> tuple[Optional[int], int, float]:
        """
        Rank this session among all completed sessions for the recruiter.
        Returns (rank, total_candidates, percentile).
        Rank 1 = best score. Percentile 100 = top candidate.
        """
        sibling_ids = self._recruiter_sessions.get(recruiter_id, [])
        scores = []
        for sid in sibling_ids:
            s = self._sessions.get(sid)
            if s:
                scores.append(s.code_score_pct)

        total = len(scores)
        if total == 0:
            return 1, 1, 100.0

        scores_sorted = sorted(scores, reverse=True)
        rank = scores_sorted.index(this_score) + 1
        below = sum(1 for s in scores if s < this_score)
        percentile = round((below / total) * 100, 1)

        return rank, total, percentile


# ── Singleton factory ─────────────────────────────────

_proctor_pipeline: Optional[ProctoringPipeline] = None


def get_proctoring_pipeline() -> ProctoringPipeline:
    global _proctor_pipeline
    if _proctor_pipeline is None:
        _proctor_pipeline = ProctoringPipeline()
        logger.info("ProctoringPipeline initialised")
    return _proctor_pipeline
