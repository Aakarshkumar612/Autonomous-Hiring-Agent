"""
agents/silent_proctor.py
═══════════════════════════════════════════════════════
Silent proctoring agent — runs in the background during DSA interviews.

Key differences from ProctorAgent (proctor_agent.py):
  - NEVER warns the candidate. Zero UI feedback to candidate.
  - All data is held server-side; recruiter receives it after interview ends.
  - Computes a 0-100 risk score from weighted behavioural signals.
  - Generates a Groq-powered narrative for the recruiter report.

Risk weights:
  TAB_HIDDEN      +8  per event
  WINDOW_BLUR     +3  per event
  LARGE_PASTE     +15 per event  (paste > 10 lines)
  PASTE_DETECTED  +5  per event
  RAPID_INPUT     +10 per burst
  DEVTOOLS        +20 one-time
  AWAY_TIME       +1  per 30s away (capped at +20)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Optional

from groq import Groq

from models.proctoring import (
    CandidateRiskProfile,
    ProctoringReport,
    QuestionMetrics,
    RiskLevel,
    SilentEvent,
    SilentEventType,
)
from utils.logger import logger


# ── Risk weight constants ─────────────────────────────
_W_TAB_SWITCH     = 8
_W_WINDOW_BLUR    = 3
_W_LARGE_PASTE    = 15
_W_PASTE          = 5
_W_RAPID_INPUT    = 10
_W_DEVTOOLS       = 20
_MAX_AWAY_BONUS   = 20


class SilentProctorAgent:
    """
    Stateless agent — all per-session state lives in ProctoringPipeline.

    Public methods:
      compute_risk()        → CandidateRiskProfile
      generate_narrative()  → (summary, red_flags, recommendations)
      build_report()        → ProctoringReport
    """

    def __init__(self) -> None:
        self._model = (
            os.getenv("GROQ_ORCHESTRATOR")
            or "llama-3.3-70b-versatile"
        )
        self._client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

    # ── Risk computation (deterministic, no LLM) ──────

    def compute_risk(
        self,
        session_id:   str,
        applicant_id: str,
        events:       list[SilentEvent],
    ) -> CandidateRiskProfile:
        """
        Compute a 0-100 risk score from all silent events.
        Pure arithmetic — fast and deterministic.
        """
        score         = 0.0
        tab_switches  = 0
        window_blurs  = 0
        large_pastes  = 0
        total_pastes  = 0
        rapid_inputs  = 0
        total_away_ms = 0
        large_chars   = 0
        devtools      = False

        for ev in events:
            t = ev.event_type
            if t == SilentEventType.TAB_HIDDEN:
                tab_switches += 1
                score += _W_TAB_SWITCH
            elif t == SilentEventType.WINDOW_BLUR:
                window_blurs += 1
                score += _W_WINDOW_BLUR
            elif t == SilentEventType.LARGE_PASTE:
                large_pastes += 1
                score += _W_LARGE_PASTE
                large_chars += ev.paste_length or 0
            elif t == SilentEventType.PASTE_DETECTED:
                total_pastes += 1
                score += _W_PASTE
            elif t == SilentEventType.RAPID_INPUT:
                rapid_inputs += 1
                score += _W_RAPID_INPUT
            elif t == SilentEventType.DEVTOOLS and not devtools:
                devtools = True
                score += _W_DEVTOOLS
            elif t == SilentEventType.TAB_VISIBLE and ev.duration_away_ms:
                total_away_ms += ev.duration_away_ms

        # Away-time bonus: 1 point per 30s, capped at 20
        score += min(total_away_ms / 30_000, _MAX_AWAY_BONUS)
        score  = min(score, 100.0)

        risk_level = (
            RiskLevel.CRITICAL if score >= 76 else
            RiskLevel.HIGH     if score >= 51 else
            RiskLevel.MEDIUM   if score >= 26 else
            RiskLevel.LOW
        )

        logger.info(
            f"SILENT_PROCTOR | risk | {session_id} | "
            f"score={score:.1f} | {risk_level.value}"
        )

        return CandidateRiskProfile(
            session_id=session_id,
            applicant_id=applicant_id,
            risk_level=risk_level,
            risk_score=round(score, 1),
            tab_switch_count=tab_switches,
            total_away_time_ms=total_away_ms,
            suspicious_paste_count=large_pastes,
            large_paste_total_chars=large_chars,
            external_tool_detections=0,   # no screen capture in this build
            window_blur_count=window_blurs,
            rapid_input_events=rapid_inputs,
            devtools_detected=devtools,
        )

    # ── Groq narrative generation ─────────────────────

    def generate_narrative(
        self,
        risk:             CandidateRiskProfile,
        events:           list[SilentEvent],
        question_metrics: list[QuestionMetrics],
        code_score_pct:   float,
    ) -> tuple[str, list[str], list[str]]:
        """
        Returns (behavioral_summary, red_flags, recommendations).
        Falls back to rule-based text if Groq is unavailable.
        """
        away_min = risk.total_away_time_ms / 60_000

        digest = (
            f"Code score: {code_score_pct:.1f}%\n"
            f"Risk score: {risk.risk_score}/100 ({risk.risk_level.value.upper()})\n"
            f"Tab switches: {risk.tab_switch_count}\n"
            f"Total away from window: {away_min:.1f} minutes\n"
            f"Large pastes (>10 lines): {risk.suspicious_paste_count}\n"
            f"Window blur count: {risk.window_blur_count}\n"
            f"Rapid-input bursts: {risk.rapid_input_events}\n"
            f"DevTools opened: {'Yes' if risk.devtools_detected else 'No'}\n"
        )

        for qm in question_metrics:
            away_qmin = qm.away_time_ms / 60_000
            solved    = "Solved" if qm.solved else "Not solved"
            fast_note = " (suspiciously fast)" if qm.suspiciously_fast else ""
            digest += (
                f"\nProblem '{qm.problem_title}': {solved}{fast_note} | "
                f"Score {qm.best_score_pct:.0f}% | "
                f"{qm.submission_attempts} attempt(s) | "
                f"{away_qmin:.1f} min away"
            )

        prompt = (
            "You are a senior technical recruiter reviewing an automated proctoring report "
            "from a DSA coding interview. Based on the data below, provide:\n"
            "1. A 3-4 sentence behavioural summary of the candidate's integrity.\n"
            "2. A JSON list of up to 5 specific red flags (short phrases, max 12 words each). "
            "Empty list if none.\n"
            "3. A JSON list of up to 3 recruiter recommendations (short phrases).\n\n"
            "Return ONLY valid JSON:\n"
            '{"summary": "...", "red_flags": [...], "recommendations": [...]}\n\n'
            f"--- Report Data ---\n{digest}"
        )

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return (
                    str(parsed.get("summary", "")),
                    [str(f) for f in parsed.get("red_flags", [])],
                    [str(r) for r in parsed.get("recommendations", [])],
                )
        except Exception as exc:
            logger.warning(f"SILENT_PROCTOR | narrative failed: {exc}")

        return self._fallback_narrative(risk, code_score_pct)

    # ── Report assembly ───────────────────────────────

    def build_report(
        self,
        *,
        session_id:          str,
        applicant_id:        str,
        applicant_name:      str,
        recruiter_id:        str,
        session_duration_ms: int,
        events:              list[SilentEvent],
        question_metrics:    list[QuestionMetrics],
        code_score_pct:      float,
        rank:                Optional[int],
        total_candidates:    int,
        percentile:          float,
    ) -> ProctoringReport:
        """Assemble the full ProctoringReport for one session."""
        risk = self.compute_risk(session_id, applicant_id, events)

        summary, flags, recs = self.generate_narrative(
            risk=risk,
            events=events,
            question_metrics=question_metrics,
            code_score_pct=code_score_pct,
        )
        risk.ai_summary = summary

        return ProctoringReport(
            session_id=session_id,
            applicant_id=applicant_id,
            applicant_name=applicant_name,
            recruiter_id=recruiter_id,
            session_duration_ms=session_duration_ms,
            events=events,
            screen_analyses=[],
            question_metrics=question_metrics,
            risk=risk,
            rank=rank,
            total_candidates=total_candidates,
            percentile=percentile,
            code_score_pct=code_score_pct,
            behavioral_summary=summary,
            red_flags=flags,
            recommendations=recs,
        )

    # ── Rule-based fallback ───────────────────────────

    def _fallback_narrative(
        self,
        risk: CandidateRiskProfile,
        code_score_pct: float,
    ) -> tuple[str, list[str], list[str]]:
        flags = []
        recs  = []

        if risk.tab_switch_count >= 3:
            flags.append(f"Switched away from interview {risk.tab_switch_count} times")
        if risk.suspicious_paste_count >= 1:
            flags.append(f"Pasted large code blocks {risk.suspicious_paste_count} time(s)")
        if risk.devtools_detected:
            flags.append("Browser DevTools opened during interview")
        if risk.total_away_time_ms > 180_000:
            flags.append(f"Away from window for {risk.total_away_time_ms // 60_000} minutes total")
        if risk.rapid_input_events >= 2:
            flags.append(f"Unusually fast typing bursts detected {risk.rapid_input_events} time(s)")

        if risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            recs += ["Schedule a live follow-up interview", "Treat code score with caution"]
        elif risk.risk_level == RiskLevel.MEDIUM:
            recs.append("Review paste events before making a hiring decision")
        else:
            recs.append("Low integrity risk — proceed to next hiring stage")

        level = risk.risk_level.value.upper()
        summary = (
            f"Candidate integrity risk is rated {level} "
            f"(score {risk.risk_score:.0f}/100). "
            f"Code score: {code_score_pct:.1f}%. "
        )
        if flags:
            summary += f"Primary concerns: {'; '.join(flags[:2])}. "
        else:
            summary += "No significant integrity issues detected during the session. "

        return summary, flags, recs
