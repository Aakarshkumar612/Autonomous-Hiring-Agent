"""
agents/interviewer.py
═══════════════════════════════════════════════════════
Interviewer Agent for the Autonomous Hiring Agent.
Uses Groq meta-llama/llama-4-maverick-17b-128e-instruct
to conduct 3-round autonomous interviews.

Rounds:
  1 → Screening  (5 questions — introduction & motivation)
  2 → Technical  (5 questions — depth & problem-solving)
  3 → Cultural   (5 questions — values & teamwork)

Follow-up logic:
  If a response is under MIN_RESPONSE_WORDS words, the agent
  asks for elaboration before advancing. Each question gets
  at most one follow-up prompt.

Usage:
    agent = InterviewerAgent()
    session, first_q = await agent.start_session(applicant)
    next_q, done     = await agent.process_response(session, applicant_answer)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime

from groq import AsyncGroq

from connectors.supabase_mcp import supabase_store
from models.applicant import Applicant
from models.interview import (
    InterviewQuestion,
    InterviewResponse,
    InterviewSession,
    InterviewType,
    MessageRole,
    QuestionCategory,
    RoundSummary,
    SessionStatus,
)
from utils.logger import log_interview_event, logger
from utils.prompt_templates import (
    INTERVIEWER_SYSTEMS,
    interviewer_followup_prompt,
    interviewer_opening_prompt,
    interviewer_round_summary_prompt,
)
from utils.rate_limiter import DailyLimitExceededError, rate_limiter, with_retry

INTERVIEWER_MODEL   = os.getenv("GROQ_INTERVIEWER", "meta-llama/llama-4-maverick-17b-128e-instruct")
QUESTIONS_PER_ROUND = int(os.getenv("INTERVIEW_QUESTIONS_PER_ROUND", "5"))
MIN_RESPONSE_WORDS  = 20

# Default question category per round
_ROUND_CATEGORY: dict[int, QuestionCategory] = {
    1: QuestionCategory.INTRODUCTION,
    2: QuestionCategory.TECHNICAL_CONCEPT,
    3: QuestionCategory.BEHAVIORAL,
}


class InterviewerAgent:
    """
    Conducts 3-round autonomous interviews via a turn-by-turn API.

    Each public method is async and stateless with respect to the
    InterviewSession object — all mutable state lives in the session,
    which is persisted to Supabase after each meaningful change.

    Agent-level caches (_followup_pending, _session_meta) are
    keyed on session_id and are cleared when the session completes.
    They hold transient in-process state that doesn't belong in
    the persisted model.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self.model  = INTERVIEWER_MODEL

        # session_id → True when awaiting a follow-up response
        self._followup_pending: dict[str, bool] = {}
        # session_id → {experience_years, skills} cached from Applicant
        self._session_meta: dict[str, dict]     = {}

    # ─────────────────────────────────────────────────
    #  State helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.strip().split())

    def _is_short(self, text: str) -> bool:
        return self._word_count(text) < MIN_RESPONSE_WORDS

    def _new_question_id(self, session: InterviewSession) -> str:
        n = len(session.questions) + 1
        return f"{session.session_id}-R{session.current_round}-Q{n}"

    def _questions_this_round(self, session: InterviewSession) -> int:
        """Number of main questions asked in the current round."""
        return len(session.questions) - (session.current_round - 1) * QUESTIONS_PER_ROUND

    def _responses_this_round(self, session: InterviewSession) -> int:
        """Number of responses recorded in the current round."""
        return len(session.responses) - (session.current_round - 1) * QUESTIONS_PER_ROUND

    def _pending_question(self, session: InterviewSession) -> InterviewQuestion:
        """
        Return the question that has been asked but not yet answered.
        Only valid when len(questions) > len(responses).
        """
        return session.questions[len(session.responses)]

    def _get_round_qa_pairs(self, session: InterviewSession) -> list[dict]:
        """Q&A pairs for the current round, formatted for the summary prompt."""
        start     = (session.current_round - 1) * QUESTIONS_PER_ROUND
        questions = session.questions[start : start + QUESTIONS_PER_ROUND]
        responses = session.responses[start : start + QUESTIONS_PER_ROUND]
        return [
            {
                "question": q.question_text,
                "response": responses[i].response_text if i < len(responses) else "No answer",
            }
            for i, q in enumerate(questions)
        ]

    def _clear_cache(self, session_id: str) -> None:
        self._followup_pending.pop(session_id, None)
        self._session_meta.pop(session_id, None)

    # ─────────────────────────────────────────────────
    #  Groq API calls
    # ─────────────────────────────────────────────────

    async def _call_groq(self, session: InterviewSession, user_prompt: str) -> str:
        """
        Interview call — includes conversation history so the model
        has full context of the exchange so far.
        The user_prompt is a meta-instruction (not the applicant's words).
        """
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": INTERVIEWER_SYSTEMS[session.current_round]},
                *session.get_conversation_history(),
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()

    async def _call_groq_summary(self, prompt: str) -> str:
        """
        Standalone evaluation call — no conversation history.
        The full transcript is embedded in the prompt itself.
        Uses low temperature for consistent scoring.
        """
        await rate_limiter.acquire(self.model)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    # ─────────────────────────────────────────────────
    #  Round management
    # ─────────────────────────────────────────────────

    def _parse_round_summary(
        self,
        raw: str,
        round_number: int,
        interview_type: InterviewType,
    ) -> RoundSummary:
        data = json.loads(raw)
        return RoundSummary(
            round_number=round_number,
            interview_type=interview_type,
            total_questions=QUESTIONS_PER_ROUND,
            answered=QUESTIONS_PER_ROUND,
            round_score=float(data.get("round_score", 0)),
            key_strengths=data.get("key_strengths", []),
            key_weaknesses=data.get("key_weaknesses", []),
            advance_to_next=bool(data.get("advance_to_next", True)),
            summary_text=data.get("summary_text"),
            completed_at=datetime.utcnow(),
        )

    async def _complete_round(self, session: InterviewSession) -> RoundSummary:
        """
        Call Groq to evaluate the completed round.
        Parses the JSON response into a RoundSummary.
        """
        log_interview_event(
            session.session_id,
            f"Round {session.current_round} evaluating",
            f"{QUESTIONS_PER_ROUND} Q&A pairs submitted for scoring",
        )
        prompt = interviewer_round_summary_prompt(
            applicant_name=session.applicant_name,
            round_number=session.current_round,
            interview_type=session.interview_type.value,
            questions_and_responses=self._get_round_qa_pairs(session),
        )
        raw = await with_retry(
            self._call_groq_summary,
            prompt,
            max_retries=3,
            base_delay=2.0,
            model=self.model,
        )
        summary = self._parse_round_summary(raw, session.current_round, session.interview_type)
        log_interview_event(
            session.session_id,
            f"Round {session.current_round} scored",
            f"Score: {summary.round_score} | Advance: {summary.advance_to_next}",
        )
        return summary

    async def _open_round(self, session: InterviewSession) -> str:
        """
        Generate and record the opening question for the current round.
        Adds the question to session.questions and session.messages.
        Returns the question text.
        """
        meta   = self._session_meta.get(session.session_id, {})
        prompt = interviewer_opening_prompt(
            applicant_name=session.applicant_name,
            role=session.role_applied,
            round_number=session.current_round,
            experience_years=meta.get("experience_years", 0.0),
            skills=meta.get("skills", []),
        )
        question_text = await with_retry(
            self._call_groq,
            session,
            prompt,
            max_retries=3,
            base_delay=2.0,
            model=self.model,
        )
        session.questions.append(
            InterviewQuestion(
                question_id=self._new_question_id(session),
                category=_ROUND_CATEGORY[session.current_round],
                question_text=question_text,
            )
        )
        session.add_message(MessageRole.AGENT, question_text)
        log_interview_event(
            session.session_id,
            f"Round {session.current_round} opened",
            f"Type: {session.interview_type.value}",
        )
        return question_text

    # ─────────────────────────────────────────────────
    #  Persistence
    # ─────────────────────────────────────────────────

    async def _save(self, session: InterviewSession) -> None:
        """Persist session to Supabase without blocking the event loop."""
        try:
            await asyncio.to_thread(supabase_store.save_session, session)
        except Exception as e:
            logger.warning(f"Session save failed [{session.session_id}]: {e}")

    # ─────────────────────────────────────────────────
    #  Internal turn helpers
    # ─────────────────────────────────────────────────

    async def _ask_next_question(
        self,
        session: InterviewSession,
        last_response: str,
    ) -> str:
        """
        Ask the next main question using interviewer_followup_prompt.
        Adds the new InterviewQuestion and AGENT message to the session.
        """
        prompt = interviewer_followup_prompt(
            applicant_response=last_response,
            questions_asked=self._questions_this_round(session),
            max_questions=QUESTIONS_PER_ROUND,
            round_number=session.current_round,
        )
        question_text = await with_retry(
            self._call_groq,
            session,
            prompt,
            max_retries=3,
            base_delay=2.0,
            model=self.model,
        )
        session.questions.append(
            InterviewQuestion(
                question_id=self._new_question_id(session),
                category=_ROUND_CATEGORY[session.current_round],
                question_text=question_text,
            )
        )
        session.add_message(MessageRole.AGENT, question_text)
        await self._save(session)
        return question_text

    async def _finish_round(
        self,
        session: InterviewSession,
    ) -> tuple[str | None, bool]:
        """
        Evaluate the completed round and either advance to the next
        round or terminate the session.

        Returns (next_question | None, is_complete).
        """
        summary = await self._complete_round(session)
        session.round_summaries.append(summary)

        # Applicant did not pass this round
        if not summary.advance_to_next:
            session.status = SessionStatus.COMPLETED
            session.compute_final_score()
            self._clear_cache(session.session_id)
            await self._save(session)
            log_interview_event(
                session.session_id,
                "Session ended — not advanced",
                f"Round {session.current_round} | Final score: {session.final_score}",
            )
            return None, True

        # Try to advance to the next round
        if not session.advance_round():
            # All rounds complete
            session.status = SessionStatus.COMPLETED
            session.compute_final_score()
            self._clear_cache(session.session_id)
            await self._save(session)
            log_interview_event(
                session.session_id,
                "Session completed — all rounds done",
                f"Final score: {session.final_score}",
            )
            return None, True

        # Open the next round
        next_question = await self._open_round(session)
        await self._save(session)
        log_interview_event(
            session.session_id,
            f"Advanced to round {session.current_round}",
            session.interview_type.value,
        )
        return next_question, False

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def start_session(self, applicant: Applicant) -> tuple[InterviewSession, str]:
        """
        Create an interview session and generate the Round 1 opening question.

        Returns:
            (session, first_question_text)

        The caller is responsible for delivering first_question_text to the
        applicant and then calling process_response() with their answer.
        """
        session_id = f"SESS-{uuid.uuid4().hex[:8].upper()}"
        session = InterviewSession(
            session_id=session_id,
            applicant_id=applicant.id,
            applicant_name=applicant.full_name,
            role_applied=applicant.role_applied.value,
            status=SessionStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
        )

        # Cache applicant profile for use when opening rounds 2 and 3,
        # where we no longer have the Applicant object available.
        self._session_meta[session_id] = {
            "experience_years": applicant.total_experience_years(),
            "skills": applicant.skill_names(),
        }

        log_interview_event(session_id, "Session started", applicant.full_name)

        first_question = await self._open_round(session)
        await self._save(session)
        return session, first_question

    async def process_response(
        self,
        session: InterviewSession,
        response_text: str,
    ) -> tuple[str | None, bool]:
        """
        Process one applicant response and return the agent's next message.

        Sequence per turn:
          1. If awaiting a follow-up (previous response was too short):
             record the elaborated response and continue.
          2. Else if response is too short: ask for elaboration.
             The question counter does NOT advance; the response is not
             recorded yet. Returns the follow-up prompt.
          3. Else: record the response normally.
          4. If the round is now complete (5 responses recorded):
             evaluate the round, then advance or terminate.
          5. Otherwise: ask the next main question.

        Returns:
            (next_question, is_complete)
            next_question is None when the session ends (all rounds done
            or applicant did not advance).

        Re-raises DailyLimitExceededError — quota exhausted, caller should abort.
        """
        sid        = session.session_id
        is_followup = self._followup_pending.get(sid, False)

        # ── Branch 1: receiving the follow-up elaboration ──────────
        if is_followup:
            pending_q = self._pending_question(session)
            session.add_response(
                InterviewResponse(
                    question_id=pending_q.question_id,
                    response_text=response_text,
                )
            )
            session.add_message(MessageRole.APPLICANT, response_text)
            self._followup_pending[sid] = False
            log_interview_event(
                sid,
                "Follow-up received",
                f"Words: {self._word_count(response_text)}",
            )

        # ── Branch 2: response too short → ask follow-up ───────────
        elif self._is_short(response_text):
            self._followup_pending[sid] = True
            followup_instruction = (
                f"The candidate gave a very brief answer: \"{response_text}\"\n"
                "Their response was too short. Politely ask them to elaborate "
                "with more specific details or an example. Be encouraging."
            )
            followup_text = await with_retry(
                self._call_groq,
                session,
                followup_instruction,
                max_retries=3,
                base_delay=2.0,
                model=self.model,
            )
            session.add_message(MessageRole.APPLICANT, response_text)
            session.add_message(MessageRole.AGENT, followup_text)
            log_interview_event(
                sid,
                "Follow-up sent",
                f"Short response ({self._word_count(response_text)} words)",
            )
            await self._save(session)
            return followup_text, False

        # ── Branch 3: normal-length response ───────────────────────
        else:
            pending_q = self._pending_question(session)
            session.add_response(
                InterviewResponse(
                    question_id=pending_q.question_id,
                    response_text=response_text,
                )
            )
            session.add_message(MessageRole.APPLICANT, response_text)

        # ── Round complete? ─────────────────────────────────────────
        if self._responses_this_round(session) >= QUESTIONS_PER_ROUND:
            return await self._finish_round(session)

        # ── Ask next main question ──────────────────────────────────
        next_question = await self._ask_next_question(session, response_text)
        return next_question, False
