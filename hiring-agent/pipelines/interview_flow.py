"""
pipelines/interview_flow.py
═══════════════════════════════════════════════════════
Interview Pipeline for the Autonomous Hiring Agent.

Orchestrates the full 3-round autonomous interview flow
for a single applicant, combining:
  - InterviewerAgent   → asks questions, evaluates rounds
  - DetectorAgent      → checks responses for AI content
  - OrchestratorAgent  → makes final hire/reject/hold decision
  - SessionStore       → tracks active session state

Rounds:
  1 → Screening  (5 questions — introduction & motivation)
  2 → Technical  (5 questions — depth & problem-solving)
  3 → Cultural   (5 questions — values & teamwork)

If advance_to_next is False after any round, the pipeline
skips remaining rounds and goes straight to the orchestrator.

Usage:
    pipeline = InterviewPipeline()
    decision = await pipeline.run_interview(applicant, experience_years=3.0)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from agents.detector import DetectionResult, DetectorAgent
from agents.interviewer import InterviewerAgent
from agents.orchestrator import OrchestratorDecision, OrchestratorAgent
from connectors.supabase_mcp import supabase_store
from memory.session_store import SessionStore
from models.applicant import Applicant
from models.interview import InterviewSession, SessionStatus
from models.score import ApplicantScore
from utils.logger import log_interview_event, logger

# Maps orchestrator verdict strings to Supabase ApplicationStatus values.
# Kept here so the mapping is explicit and easy to change in one place.
_VERDICT_TO_STATUS = {
    "accept": "accepted",
    "reject": "rejected",
    "hold":   "on_hold",
}


# ─────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────

@dataclass
class InterviewPipelineResult:
    """
    Full result of running the interview pipeline for one applicant.

    Attributes:
        applicant_id       — links back to Applicant record
        session            — the completed InterviewSession
        detection_results  — DetectionResult for every answered question
        decision           — final OrchestratorDecision (hire/reject/hold)
        round_scores       — per-round scores from RoundSummary objects
        total_ai_flags     — total responses flagged as AI-generated
        started_at         — pipeline start time
        completed_at       — pipeline end time
        error              — set if the pipeline aborted due to an error
    """
    applicant_id:       str
    session:            Optional[InterviewSession]      = None
    detection_results:  list[DetectionResult]           = field(default_factory=list)
    decision:           Optional[OrchestratorDecision]  = None
    round_scores:       list[float]                     = field(default_factory=list)
    total_ai_flags:     int                             = 0
    started_at:         datetime                        = field(default_factory=datetime.utcnow)
    completed_at:       Optional[datetime]              = None
    error:              Optional[str]                   = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None

    def summary(self) -> str:
        decision_str = (
            f"{self.decision.verdict} ({self.decision.next_action})"
            if self.decision else "no decision"
        )
        return (
            f"InterviewPipeline | [{self.applicant_id}] | "
            f"Decision: {decision_str} | "
            f"AI flags: {self.total_ai_flags} | "
            f"Round scores: {self.round_scores} | "
            f"Duration: {self.duration_seconds}s"
        )


# ─────────────────────────────────────────────────────
#  Simulated applicant response provider (for testing)
# ─────────────────────────────────────────────────────

class _ResponseProvider:
    """
    Abstract interface for providing applicant responses.
    In production this is fulfilled by the FastAPI portal
    (real-time chat). In tests, use a mock implementation.
    """
    async def get_response(self, question: str, session_id: str) -> str:
        raise NotImplementedError


# ─────────────────────────────────────────────────────
#  Interview Pipeline
# ─────────────────────────────────────────────────────

class InterviewPipeline:
    """
    Runs the full 3-round autonomous interview for one applicant.

    In live deployments, the pipeline is turn-based: the portal sends
    applicant responses one at a time via process_interview_response().

    For full automated runs (e.g. integration tests or offline simulations),
    use run_interview() with a _ResponseProvider.

    The pipeline is stateless per-applicant — safe to reuse across many
    concurrent interview sessions.
    """

    def __init__(
        self,
        session_store: SessionStore | None = None,
        interviewer: InterviewerAgent | None = None,
        detector: DetectorAgent | None = None,
        orchestrator: OrchestratorAgent | None = None,
    ) -> None:
        self.session_store = session_store or SessionStore()
        self.interviewer   = interviewer   or InterviewerAgent()
        self.detector      = detector      or DetectorAgent()
        self.orchestrator  = orchestrator  or OrchestratorAgent()

    # ─────────────────────────────────────────────────
    #  Full automated interview run
    # ─────────────────────────────────────────────────

    async def run_interview(
        self,
        applicant: Applicant,
        score: ApplicantScore | None = None,
        response_provider: _ResponseProvider | None = None,
        experience_years: float = 0.0,
    ) -> InterviewPipelineResult:
        """
        Run a full 3-round interview end-to-end.

        For automated / offline use. In production REST flows,
        use start_interview() + process_interview_response() instead.

        Args:
            applicant          — full applicant profile
            score              — scorer output (used by orchestrator for final decision)
            response_provider  — provides applicant answers (mock in tests)
            experience_years   — used by detector for calibration

        Returns:
            InterviewPipelineResult with session, detections, and final decision.
        """
        pipeline_result = InterviewPipelineResult(applicant_id=applicant.id)

        logger.info(
            f"INTERVIEW | Pipeline started | "
            f"[{applicant.id}] {applicant.full_name} | "
            f"Role: {applicant.role_applied.value}"
        )

        try:
            # ── Start session ─────────────────────────────────────────
            session, first_question = await self.interviewer.start_session(applicant)
            self.session_store.create_session(session)
            log_interview_event(session.session_id, "Pipeline started", applicant.full_name)

            current_question = first_question
            is_complete      = False

            # ── Turn-by-turn interview loop ───────────────────────────
            while not is_complete:
                if response_provider is None:
                    # No provider in automated mode — skip response loop
                    # (used when running from portal where responses come in via HTTP)
                    break

                response_text = await response_provider.get_response(
                    current_question, session.session_id
                )

                # Run AI detection on this response immediately
                if session.questions:
                    last_question = session.questions[-1]
                    detection = await self.detector.detect(
                        question=last_question.question_text,
                        response=response_text,
                        applicant_name=applicant.full_name,
                        role=applicant.role_applied.value,
                        experience_years=experience_years,
                        question_id=last_question.question_id,
                    )
                    pipeline_result.detection_results.append(detection)

                # Process the response in the interviewer
                next_question, is_complete = await self.interviewer.process_response(
                    session, response_text
                )
                self.session_store.update_session(session)

                if next_question:
                    current_question = next_question

            # ── Run AI detection on full session (if no per-turn detection) ───
            if not pipeline_result.detection_results and session.responses:
                pipeline_result.detection_results = await self.detector.scan_session(
                    session, experience_years=experience_years
                )

            # ── Gather round scores ───────────────────────────────────
            pipeline_result.round_scores = [
                s.round_score
                for s in session.round_summaries
                if s.round_score is not None
            ]
            pipeline_result.total_ai_flags = sum(
                1 for d in pipeline_result.detection_results if d.flagged
            )

            log_interview_event(
                session.session_id,
                "Rounds complete",
                f"Scores: {pipeline_result.round_scores} | "
                f"AI flags: {pipeline_result.total_ai_flags}",
            )

            # ── Final orchestrator decision ───────────────────────────
            pipeline_result.decision = await self.orchestrator.decide(
                applicant=applicant,
                score=score or _empty_score(applicant.id, applicant.full_name),
                detection_results=pipeline_result.detection_results,
                round_scores=pipeline_result.round_scores,
            )

            session.final_verdict = pipeline_result.decision.verdict
            self.session_store.update_session(session)
            self.session_store.end_session(session.session_id)

            pipeline_result.session    = session
            pipeline_result.completed_at = datetime.utcnow()

            logger.info(f"INTERVIEW | Pipeline complete | {pipeline_result.summary()}")

        except Exception as e:
            pipeline_result.error = str(e)
            pipeline_result.completed_at = datetime.utcnow()
            logger.error(
                f"INTERVIEW | Pipeline FAILED | [{applicant.id}] {applicant.full_name} | {e}"
            )

        return pipeline_result

    # ─────────────────────────────────────────────────
    #  Real-time portal flow (turn-by-turn)
    # ─────────────────────────────────────────────────

    async def start_interview(
        self,
        applicant: Applicant,
    ) -> tuple[str, str]:
        """
        Start an interview session for a live portal interaction.

        Returns:
            (session_id, first_question_text)

        The caller (e.g. a FastAPI endpoint) should present the
        first_question to the applicant and then call
        process_interview_response() with each answer.
        """
        session, first_question = await self.interviewer.start_session(applicant)
        self.session_store.create_session(session)
        log_interview_event(session.session_id, "Live session started", applicant.full_name)
        return session.session_id, first_question

    async def process_interview_response(
        self,
        session_id: str,
        response_text: str,
        applicant: Applicant,
        score: ApplicantScore | None = None,
        experience_years: float = 0.0,
    ) -> dict:
        """
        Process one applicant response in a live portal session.

        Args:
            session_id      — from start_interview()
            response_text   — the applicant's typed answer
            applicant       — needed for detector + orchestrator
            score           — needed by orchestrator for final decision
            experience_years — for detector calibration

        Returns a dict with:
            {
                "next_question": str | None,
                "is_complete": bool,
                "decision": OrchestratorDecision | None,  (set when is_complete)
                "ai_flagged": bool,
            }
        """
        session = self.session_store.get_session(session_id)
        if not session:
            logger.error(f"INTERVIEW | Session [{session_id}] not found or expired")
            return {
                "next_question": None,
                "is_complete": True,
                "decision": None,
                "ai_flagged": False,
                "error": f"Session {session_id} not found or expired",
            }

        # Run AI detection on this response
        ai_flagged = False
        detection: DetectionResult | None = None
        if session.questions:
            last_question = session.questions[len(session.responses)]
            try:
                detection = await self.detector.detect(
                    question=last_question.question_text,
                    response=response_text,
                    applicant_name=applicant.full_name,
                    role=applicant.role_applied.value,
                    experience_years=experience_years,
                    question_id=last_question.question_id,
                )
                ai_flagged = detection.flagged
            except Exception as e:
                logger.warning(f"INTERVIEW | Detector failed for [{session_id}]: {e}")

        # Process response in interviewer
        next_question, is_complete = await self.interviewer.process_response(
            session, response_text
        )
        self.session_store.update_session(session)

        decision = None
        if is_complete:
            # Scan all responses for final AI detection summary
            all_detections: list[DetectionResult] = []
            if detection:
                all_detections.append(detection)
            try:
                remaining = await self.detector.scan_session(
                    session, experience_years=experience_years
                )
                all_detections.extend(remaining)
            except Exception as e:
                logger.warning(f"INTERVIEW | scan_session failed for [{session_id}]: {e}")

            round_scores = [
                s.round_score
                for s in session.round_summaries
                if s.round_score is not None
            ]

            decision = await self.orchestrator.decide(
                applicant=applicant,
                score=score or _empty_score(applicant.id, applicant.full_name),
                detection_results=all_detections,
                round_scores=round_scores,
            )
            session.final_verdict = decision.verdict
            self.session_store.update_session(session)
            self.session_store.end_session(session_id)

            # Persist the final verdict to Supabase so it survives restarts.
            # Uses asyncio.to_thread because supabase-py is a blocking client.
            # A save failure is non-fatal — log it but still return the decision.
            new_status = _VERDICT_TO_STATUS.get(decision.verdict, "on_hold")
            try:
                await asyncio.to_thread(
                    supabase_store.update_applicant_status,
                    applicant.id,
                    new_status,
                )
                logger.info(
                    f"INTERVIEW | [{session_id}] Supabase status updated → {new_status}"
                )
            except Exception as exc:
                logger.error(
                    f"INTERVIEW | [{session_id}] Supabase status update failed: {exc}"
                )

            logger.info(
                f"INTERVIEW | [{session_id}] Complete | "
                f"Decision: {decision.verdict} | "
                f"Round scores: {round_scores}"
            )

        return {
            "next_question": next_question,
            "is_complete":   is_complete,
            "decision":      decision,
            "ai_flagged":    ai_flagged,
        }


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _empty_score(applicant_id: str, applicant_name: str) -> ApplicantScore:
    """
    Create a minimal ApplicantScore placeholder for applicants
    who enter the interview pipeline without a prior scoring pass.
    The orchestrator will rely on interview performance alone.
    """
    from models.score import ScoringStatus
    return ApplicantScore(
        applicant_id=applicant_id,
        applicant_name=applicant_name,
        status=ScoringStatus.SKIPPED,
        final_score=None,
    )
