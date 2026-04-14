"""
models/proctoring.py
═══════════════════════════════════════════════════════
Data models for the silent proctoring system.

The silent proctoring pipeline runs in parallel with the DSA interview
but never shows warnings to the candidate. All collected data is held
server-side and delivered to the recruiter after the session ends.

Key design: no candidate-facing feedback. Everything is silent.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────
#  Event taxonomy
# ─────────────────────────────────────────────────────

class SilentEventType(str, Enum):
    TAB_HIDDEN       = "tab_hidden"        # document.hidden became True
    TAB_VISIBLE      = "tab_visible"       # document.hidden became False
    WINDOW_BLUR      = "window_blur"       # window lost OS focus
    WINDOW_FOCUS     = "window_focus"      # window regained OS focus
    PASTE_DETECTED   = "paste_detected"    # paste event in editor (any size)
    LARGE_PASTE      = "large_paste"       # paste > 10 lines (high suspicion)
    COPY_DETECTED    = "copy_detected"     # copy from editor content
    CURSOR_LEFT      = "cursor_left"       # mouseleave on document
    RAPID_INPUT      = "rapid_input"       # >200 chars typed in <3s burst
    SCREEN_FLAGGED   = "screen_flagged"    # Groq vision flagged screenshot
    DEVTOOLS         = "devtools"          # DevTools dimension heuristic
    SESSION_START    = "session_start"     # monitoring began
    SESSION_END      = "session_end"       # interview completed


class RiskLevel(str, Enum):
    LOW      = "low"       # 0-25:  normal interview behaviour
    MEDIUM   = "medium"    # 26-50: some suspicious activity
    HIGH     = "high"      # 51-75: strong indicators of cheating
    CRITICAL = "critical"  # 76-100: almost certain cheating


# ─────────────────────────────────────────────────────
#  Individual event
# ─────────────────────────────────────────────────────

class SilentEvent(BaseModel):
    """
    One proctoring event — collected silently, never shown to candidate.
    Stored per-session in-memory; included verbatim in ProctoringReport.
    """
    id:               str
    session_id:       str
    applicant_id:     str
    event_type:       SilentEventType
    timestamp:        datetime = Field(default_factory=datetime.utcnow)
    # Duration-based fields (populated when TAB_VISIBLE pairs with TAB_HIDDEN)
    duration_away_ms: Optional[int]  = None
    # Paste analysis
    paste_length:     Optional[int]  = None   # character count
    paste_preview:    Optional[str]  = None   # first 120 chars, sanitised
    paste_looks_ai:   bool           = False  # True if paste matches AI output patterns
    # Generic detail
    detail:           str            = ""


# ─────────────────────────────────────────────────────
#  Screen capture analysis
# ─────────────────────────────────────────────────────

class ScreenAnalysis(BaseModel):
    """
    Result of one Groq vision call on a candidate screenshot.
    Populated by SilentProctorAgent.analyze_screenshot().
    """
    id:               str
    session_id:       str
    captured_at:      datetime = Field(default_factory=datetime.utcnow)
    flagged:          bool           = False
    # Tools detected on screen (e.g. ["ChatGPT", "GitHub Copilot"])
    detected_tools:   list[str]      = []
    # Raw Groq vision output
    analysis_text:    str            = ""
    confidence:       float          = 0.0    # 0.0–1.0


# ─────────────────────────────────────────────────────
#  Per-question timing metrics
# ─────────────────────────────────────────────────────

class QuestionMetrics(BaseModel):
    """
    Timing breakdown for a single DSA problem within the session.
    Built from SilentEvent timestamps by the pipeline.
    """
    problem_id:            str
    problem_title:         str
    time_started:          datetime
    time_first_keystroke:  Optional[datetime] = None
    time_submitted:        Optional[datetime] = None
    active_time_ms:        int    = 0   # time window was focused
    away_time_ms:          int    = 0   # cumulative tab-hidden / window-blur time
    submission_attempts:   int    = 0
    best_score_pct:        float  = 0.0
    solved:                bool   = False
    # Suspicion: if solve time < expected minimum for difficulty
    suspiciously_fast:     bool   = False


# ─────────────────────────────────────────────────────
#  Candidate risk profile
# ─────────────────────────────────────────────────────

class CandidateRiskProfile(BaseModel):
    """
    Aggregated risk assessment computed from all events in a session.
    Risk score 0–100 drives the risk_level bucket.
    """
    session_id:               str
    applicant_id:             str
    risk_level:               RiskLevel = RiskLevel.LOW
    risk_score:               float     = 0.0   # 0-100
    # Event counts
    tab_switch_count:         int       = 0
    total_away_time_ms:       int       = 0
    suspicious_paste_count:   int       = 0     # pastes > 10 lines
    large_paste_total_chars:  int       = 0
    external_tool_detections: int       = 0     # screen snapshots flagged
    window_blur_count:        int       = 0
    rapid_input_events:       int       = 0
    devtools_detected:        bool      = False
    # Narrative (Groq-generated)
    ai_summary:               str       = ""


# ─────────────────────────────────────────────────────
#  Full post-interview report
# ─────────────────────────────────────────────────────

class ProctoringReport(BaseModel):
    """
    Complete post-interview proctoring report delivered to recruiter.
    Generated once when session ends; cached in _proctor_reports dict.
    """
    session_id:          str
    applicant_id:        str
    applicant_name:      str   = "Unknown Candidate"
    recruiter_id:        str
    generated_at:        datetime = Field(default_factory=datetime.utcnow)
    session_duration_ms: int   = 0
    # Raw data
    events:              list[SilentEvent]    = []
    screen_analyses:     list[ScreenAnalysis] = []
    question_metrics:    list[QuestionMetrics] = []
    # Risk
    risk:                Optional[CandidateRiskProfile] = None
    # Ranking (populated after comparing across recruiter's sessions)
    rank:                Optional[int]   = None   # 1 = best score
    total_candidates:    int             = 0
    percentile:          float           = 0.0    # 100 = top candidate
    code_score_pct:      float           = 0.0
    # Narrative
    behavioral_summary:  str             = ""
    red_flags:           list[str]       = []
    recommendations:     list[str]       = []
