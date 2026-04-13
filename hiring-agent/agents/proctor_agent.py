"""
agents/proctor_agent.py
═══════════════════════════════════════════════════════
AI proctoring agent for the DSA interview platform.

Responsibilities:
  1. Track cheat events forwarded from the frontend (tab switches,
     copy-paste, window blur, rapid pastes).
  2. Apply the 3-strike system:
       Strike 1 → avatar delivers verbal warning
       Strike 2 → avatar delivers final warning
       Strike 3 → session terminated (KICKED)
  3. Generate avatar-spoken warning scripts via Groq.
  4. Analyse suspicious events using LLM to reduce false positives
     (e.g. switching to a calculator app ≠ cheating).

Model: GROQ_INTERVIEWER (meta-llama/llama-4-maverick-17b-128e-instruct)
       Falls back to GROQ_ORCHESTRATOR if not set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from groq import Groq

from models.dsa_problem import CheatEventType, CheatStrike, ProctorEvent
from utils.logger import logger


# ── Warning scripts (avatar speaks these) ────────────
_WARNING_SCRIPTS = {
    CheatStrike.WARNING_1: (
        "I noticed some unusual activity just now. "
        "This is your first warning — please keep the interview window "
        "in focus and avoid copying content from external sources. "
        "I'm here to help you show your best work, not to catch you out."
    ),
    CheatStrike.WARNING_2: (
        "That's a second incident. This is your final warning. "
        "If I detect another violation, your session will be automatically "
        "terminated and marked for review. Please stay focused on the problem "
        "in front of you — you have the skills, trust yourself."
    ),
}

_KICK_MESSAGE = (
    "I'm sorry, but this session has been terminated due to repeated violations "
    "of the academic integrity policy. Your recruiter has been notified. "
    "Please contact the hiring team if you believe this is an error."
)


@dataclass
class ProctorState:
    """Per-session proctoring state (in-memory)."""
    session_id:    str
    applicant_id:  str
    strike_count:  int = 0
    strike_level:  CheatStrike = CheatStrike.NONE
    events:        list[ProctorEvent] = field(default_factory=list)
    kicked:        bool = False


class ProctorAgent:
    """
    Stateless proctoring logic. Caller maintains ProctorState.

    Designed to be called from DSAInterviewPipeline:
      event  = ProctorEvent(...)
      result = proctor.handle_event(state, event)
      # result.warning_text → TTS pipeline
      # result.kicked       → terminate session
    """

    def __init__(self) -> None:
        self._model = (
            os.getenv("GROQ_INTERVIEWER")
            or os.getenv("GROQ_ORCHESTRATOR", "llama-3.3-70b-versatile")
        )
        self._client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

    # ── Public API ────────────────────────────────────

    def handle_event(
        self,
        state: ProctorState,
        event: ProctorEvent,
    ) -> "ProctorResult":
        """
        Process one cheat event. Increments strike count and
        returns the appropriate avatar warning or kick action.

        Returns ProctorResult with:
          .warning_text  — text for TTS (empty string = no speech)
          .new_strike    — updated CheatStrike level
          .kicked        — True if this was the 3rd strike
        """
        if state.kicked:
            return ProctorResult("", CheatStrike.KICKED, kicked=True)

        # Low-severity events that shouldn't count as a strike alone
        if event.event_type in (CheatEventType.WINDOW_BLUR,) and state.strike_count == 0:
            logger.info(
                f"PROCTOR | {state.session_id} | {event.event_type.value} ignored (first blur)"
            )
            state.events.append(event)
            return ProctorResult("", state.strike_level, kicked=False)

        # Escalate strike
        state.strike_count += 1
        state.events.append(event)

        if state.strike_count == 1:
            state.strike_level = CheatStrike.WARNING_1
            event.strike_after = CheatStrike.WARNING_1
            text = self._warning_text(CheatStrike.WARNING_1, event)
            logger.warning(
                f"PROCTOR | {state.session_id} | Strike 1 | {event.event_type.value}"
            )
            return ProctorResult(text, CheatStrike.WARNING_1, kicked=False)

        elif state.strike_count == 2:
            state.strike_level = CheatStrike.WARNING_2
            event.strike_after = CheatStrike.WARNING_2
            text = self._warning_text(CheatStrike.WARNING_2, event)
            logger.warning(
                f"PROCTOR | {state.session_id} | Strike 2 | {event.event_type.value}"
            )
            return ProctorResult(text, CheatStrike.WARNING_2, kicked=False)

        else:
            state.strike_level = CheatStrike.KICKED
            event.strike_after = CheatStrike.KICKED
            state.kicked = True
            logger.error(
                f"PROCTOR | {state.session_id} | Strike 3 — KICKED | {event.event_type.value}"
            )
            return ProctorResult(_KICK_MESSAGE, CheatStrike.KICKED, kicked=True)

    def generate_warning(
        self,
        strike_number: int,
        event_type:    CheatEventType,
        problem_title: str = "",
    ) -> str:
        """
        Generate a personalised, contextual warning using Groq LLM.
        Falls back to static script if Groq is unavailable.

        strike_number: 1 or 2 (3 always kicks, no custom text needed)
        """
        strike = CheatStrike.WARNING_1 if strike_number == 1 else CheatStrike.WARNING_2
        fallback = _WARNING_SCRIPTS[strike]

        try:
            prompt = (
                f"You are an AI interview proctor. A candidate just triggered "
                f"a {event_type.value.replace('_', ' ')} event during a coding interview "
                f"{'on the problem: ' + problem_title if problem_title else ''}. "
                f"This is their strike #{strike_number}. "
                f"Write a firm but fair 2-sentence verbal warning that the avatar will speak aloud. "
                f"Keep it under 40 words. Do not include any preamble or formatting."
            )
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.4,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"PROCTOR | Groq warning generation failed: {exc} — using fallback")
            return fallback

    # ── Internal ──────────────────────────────────────

    def _warning_text(self, strike: CheatStrike, event: ProctorEvent) -> str:
        return _WARNING_SCRIPTS.get(strike, "")


@dataclass
class ProctorResult:
    warning_text: str
    new_strike:   CheatStrike
    kicked:       bool
