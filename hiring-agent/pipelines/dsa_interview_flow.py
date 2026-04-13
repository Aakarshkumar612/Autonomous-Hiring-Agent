"""
pipelines/dsa_interview_flow.py
═══════════════════════════════════════════════════════
DSA Interview orchestration pipeline.

Wires together:
  - FeatureGate     → tier/usage enforcement
  - CodeExecutor    → Judge0 code runner
  - SQLExecutor     → sandboxed SQL runner
  - ProctorAgent    → 3-strike cheat detection
  - AvatarBridge    → proctor avatar speech

Session lifecycle:
  1. start()           → create DSASession, gate check, return problem
  2. submit_code()     → execute code/SQL, score, save result
  3. handle_cheat()    → increment strike, avatar speaks warning
  4. end()             → mark session complete, return final score

Supports 100+ concurrent sessions — all state is per-session,
no shared mutable data.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Optional

from agents.proctor_agent import ProctorAgent, ProctorState
from connectors.code_executor import CodeExecutor
from connectors.feature_gate import FeatureGate
from connectors.sql_executor import SQLExecutor
from models.dsa_problem import (
    CheatEventType,
    CheatStrike,
    CodeSubmission,
    DSAProblem,
    DSASession,
    DSASessionStatus,
    ProctorEvent,
    ProblemType,
    SubmissionStatus,
)
from models.subscription import Feature
from utils.logger import logger


class DSAInterviewPipeline:
    """
    Orchestrates a single candidate's DSA interview session.

    One instance is shared across all sessions (stateless).
    Per-session state is in DSASession + ProctorState objects,
    not in the pipeline itself.
    """

    def __init__(
        self,
        feature_gate:   FeatureGate,
        code_executor:  Optional[CodeExecutor]  = None,
        sql_executor:   Optional[SQLExecutor]   = None,
        proctor_agent:  Optional[ProctorAgent]  = None,
    ) -> None:
        self._gate    = feature_gate
        self._code_ex = code_executor or CodeExecutor()
        self._sql_ex  = sql_executor  or SQLExecutor()
        self._proctor = proctor_agent or ProctorAgent()

        # In-memory session registry (session_id → ProctorState)
        # In production, ProctorState would live in Redis/Supabase for
        # multi-replica deployments. For now: single-process is fine.
        self._proctor_states: dict[str, ProctorState] = {}

    # ── Session management ────────────────────────────

    async def start(
        self,
        recruiter_id:  str,
        applicant_id:  str,
        problem:       DSAProblem,
        duration_min:  int = 90,
    ) -> tuple[DSASession, "GateResult"]:
        """
        Gate check → create and return a DSASession.

        Returns (session, gate_result).
        Caller should check gate_result.allowed before using session.
        """
        # Check feature availability
        feat    = Feature.SQL_TEST if problem.problem_type == ProblemType.SQL else Feature.DSA_TEST
        gate_ok = await self._gate.check(recruiter_id, feat)

        if not gate_ok.allowed:
            logger.warning(
                f"DSA_PIPELINE | start blocked | {recruiter_id} | {feat.value} | {gate_ok.reason}"
            )
            return DSASession(
                id="",
                applicant_id=applicant_id,
                recruiter_id=recruiter_id,
                problem_id=problem.id,
                status=DSASessionStatus.EXPIRED,
            ), gate_ok

        session = DSASession(
            id=f"dsa_{uuid.uuid4().hex[:12]}",
            applicant_id=applicant_id,
            recruiter_id=recruiter_id,
            problem_id=problem.id,
            status=DSASessionStatus.ACTIVE,
            duration_minutes=duration_min,
        )

        # Register proctor state
        self._proctor_states[session.id] = ProctorState(
            session_id=session.id,
            applicant_id=applicant_id,
        )

        # Increment feature usage
        await self._gate.increment_usage(recruiter_id, feat)

        logger.info(
            f"DSA_PIPELINE | session started | {session.id} | "
            f"{applicant_id} | {problem.title} | tier={gate_ok.tier.value}"
        )
        return session, gate_ok

    async def submit_code(
        self,
        session:     DSASession,
        problem:     DSAProblem,
        source_code: str,
    ) -> CodeSubmission:
        """
        Execute code/SQL and return a scored CodeSubmission.
        Does NOT mutate session — caller updates session.submissions.
        """
        sub_id     = f"sub_{uuid.uuid4().hex[:10]}"
        submission = CodeSubmission(
            id=sub_id,
            session_id=session.id,
            problem_id=problem.id,
            applicant_id=session.applicant_id,
            language=session.language,
            source_code=source_code,
            status=SubmissionStatus.RUNNING,
        )

        all_tests = problem.examples + problem.hidden_tests

        if problem.problem_type == ProblemType.SQL:
            results, agg_status = await asyncio.to_thread(
                self._sql_ex.run_test_cases,
                source_code,
                problem.schema_sql,
                all_tests,
            )
        else:
            results, agg_status = await self._code_ex.run_test_cases(
                source_code=source_code,
                language=session.language,
                test_cases=all_tests,
                time_limit_ms=problem.time_limit_ms,
                memory_limit_mb=problem.memory_limit_mb,
            )

        passed = sum(1 for r in results if r.passed)
        total  = len(results)

        submission.test_results   = results
        submission.status         = agg_status
        submission.passed_count   = passed
        submission.total_count    = total
        submission.score_pct      = (passed / total * 100) if total else 0.0

        if results:
            runtimes = [r.runtime_ms for r in results if r.runtime_ms is not None]
            if runtimes:
                submission.runtime_ms = max(runtimes)

        logger.info(
            f"DSA_PIPELINE | submit | {session.id} | {sub_id} | "
            f"{passed}/{total} passed | {agg_status.value}"
        )
        return submission

    async def handle_cheat_event(
        self,
        session:    DSASession,
        event_type: CheatEventType,
        detail:     str = "",
        problem_title: str = "",
    ) -> tuple[ProctorState, str, bool]:
        """
        Process one cheat event.

        Returns:
          (updated_proctor_state, avatar_warning_text, is_kicked)

        avatar_warning_text → pass to TTS pipeline to have avatar speak it.
        is_kicked=True      → terminate session immediately.
        """
        state = self._proctor_states.get(session.id)
        if not state:
            state = ProctorState(session_id=session.id, applicant_id=session.applicant_id)
            self._proctor_states[session.id] = state

        event = ProctorEvent(
            id=f"evt_{uuid.uuid4().hex[:8]}",
            session_id=session.id,
            applicant_id=session.applicant_id,
            event_type=event_type,
            detail=detail,
            timestamp=datetime.utcnow(),
        )

        result = self._proctor.handle_event(state, event)

        # Generate richer warning if Groq available
        warning_text = result.warning_text
        if result.new_strike in (CheatStrike.WARNING_1, CheatStrike.WARNING_2) and warning_text:
            strike_num = 1 if result.new_strike == CheatStrike.WARNING_1 else 2
            warning_text = self._proctor.generate_warning(
                strike_number=strike_num,
                event_type=event_type,
                problem_title=problem_title,
            )

        logger.info(
            f"DSA_PIPELINE | cheat_event | {session.id} | "
            f"{event_type.value} | strike={state.strike_count} | kicked={result.kicked}"
        )

        return state, warning_text, result.kicked

    async def end(
        self,
        session:     DSASession,
        submissions: list[CodeSubmission],
    ) -> DSASession:
        """
        Mark session as completed. Compute best score across all submissions.
        Returns updated session.
        """
        proctor_state = self._proctor_states.pop(session.id, None)

        if proctor_state and proctor_state.kicked:
            session.status = DSASessionStatus.KICKED
        elif session.status == DSASessionStatus.ACTIVE:
            session.status = DSASessionStatus.COMPLETED

        session.ended_at = datetime.utcnow()

        if submissions:
            session.best_score_pct = max(s.score_pct for s in submissions)
        if proctor_state:
            session.strike_count = proctor_state.strike_count
            session.strike_level = proctor_state.strike_level

        logger.info(
            f"DSA_PIPELINE | session ended | {session.id} | "
            f"status={session.status.value} | best_score={session.best_score_pct:.1f}%"
        )
        return session


def build_dsa_pipeline(gate: Optional[FeatureGate] = None) -> DSAInterviewPipeline:
    """Factory — creates pipeline with all dependencies wired."""
    from connectors.feature_gate import get_feature_gate
    return DSAInterviewPipeline(feature_gate=gate or get_feature_gate())
