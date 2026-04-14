"""
agents/avatar_persona.py
═══════════════════════════════════════════════════════
Persona layer for the avatar interviewer.

Defines WHO the avatar is (PersonaConfig) and shapes every
LLM response to sound like a real human professional
(HumanResponseShaper) — stripping AI tells, injecting
natural pacing markers, and locking in conversational style.

Components:
  PersonaConfig       — identity, personality, voice profile
  HumanResponseShaper — post-processes raw LLM text to remove
                        robot patterns and add human rhythm
  DEFAULT_PERSONA     — ready-to-use corporate interviewer persona
  ALL_PERSONAS        — pool of 5 distinct interviewers
  select_persona()    — weekly rotation so the same candidate
                        sees a different face each time they apply

Rotation strategy:
  index = sha256(applicant_id + year + ISO_week) % len(ALL_PERSONAS)
  — same applicant → different persona each week
  — deterministic within a single week (restart-safe)

Phase integration:
  Phase 1 (this file)  — persona config + response shaping
  Phase 2 (tts_service)— consumes voice_id and [PAUSE:Xs] markers
  Phase 3 (avatar_bridge) — consumes emotion_state from shaper
  Phase 4 (meeting_bot) — uses persona name as bot display name
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────
#  Persona identity
# ─────────────────────────────────────────────────────

class PersonalityTrait(str, Enum):
    WARM        = "warm"
    DIRECT      = "direct"
    ANALYTICAL  = "analytical"
    EMPATHETIC  = "empathetic"
    FORMAL      = "formal"
    CURIOUS     = "curious"


class PersonaConfig(BaseModel):
    """
    Full identity definition for the avatar interviewer.

    All fields here flow downstream:
    - name / title / company → system prompt identity lock
    - voice_id / reference_audio_path → Coqui TTS (Phase 2)
    - personality_traits → round-specific tone shaping
    - avatar_emotion_default → Unreal Engine default blend shape (Phase 3)
    - display_name → Daily.co bot participant name (Phase 4)
    """

    # ── Identity ───────────────────────────────────────
    name:               str = Field(..., description="Full human name of the interviewer")
    title:              str = Field(..., description="Job title, e.g. 'Senior Talent Acquisition Lead'")
    company:            str = Field(..., description="Company name shown in context")
    years_experience:   int = Field(default=10, ge=1, description="Backstory: years in recruiting/hiring")
    backstory:          str = Field(
        default="",
        description="2-3 sentence first-person backstory used in the system prompt"
    )

    # ── Personality ────────────────────────────────────
    personality_traits: list[PersonalityTrait] = Field(
        default_factory=lambda: [PersonalityTrait.WARM, PersonalityTrait.DIRECT]
    )
    interview_style:    str = Field(
        default="conversational and focused",
        description="Adjective phrase describing interviewing style"
    )

    # ── Voice (Phase 2 — Coqui TTS) ───────────────────
    voice_id:               str         = Field(default="default_female_en", description="Coqui TTS voice ID")
    reference_audio_path:   Optional[str] = Field(
        default=None,
        description="Path to reference WAV for XTTS v2 voice cloning"
    )
    speech_rate:            float       = Field(default=1.0, ge=0.5, le=2.0, description="TTS speed multiplier")

    # ── Avatar (Phase 3 — Unreal Engine) ──────────────
    avatar_asset_id:        str         = Field(default="corporate_female_01", description="MetaHuman asset ID in UE5")
    avatar_emotion_default: str         = Field(default="neutral", description="Default facial expression blend shape")

    # ── Meeting (Phase 4 — Daily.co) ──────────────────
    display_name:   str = Field(default="", description="Name shown in the video call participant list")

    def model_post_init(self, __context) -> None:
        if not self.display_name:
            self.display_name = self.name
        if not self.backstory:
            self.backstory = (
                f"I've been in talent acquisition for {self.years_experience} years, "
                f"focused on tech hiring at {self.company}. "
                f"I conduct interviews across all rounds — screening, technical, and culture fit."
            )


# ─────────────────────────────────────────────────────
#  Human response shaper
# ─────────────────────────────────────────────────────

# Patterns that immediately signal AI authorship — strip these.
_AI_TELL_PATTERNS: list[tuple[str, str]] = [
    # Robotic openers
    (r"^Certainly[!,.]?\s*", ""),
    (r"^Absolutely[!,.]?\s*", ""),
    (r"^Of course[!,.]?\s*", ""),
    (r"^Sure[!,.]?\s*", ""),
    (r"^Great question[!,.]?\s*", ""),
    (r"^That(?:'s| is) a great question[!,.]?\s*", ""),
    (r"^That(?:'s| is) an excellent question[!,.]?\s*", ""),
    (r"^Excellent question[!,.]?\s*", ""),
    (r"^Wonderful[!,.]?\s*", ""),
    (r"^Fantastic[!,.]?\s*", ""),
    # AI identity reveals
    (r"\bAs an AI\b", "In my experience"),
    (r"\bAs an artificial intelligence\b", "As someone who's done this a long time"),
    (r"\bI(?:'m| am) an AI\b", "I'm"),
    (r"\bI(?:'m| am) a language model\b", "I'm"),
    (r"\bI(?:'m| am) programmed to\b", "I tend to"),
    (r"\bI cannot (feel|experience|have emotions)\b", "I don't usually"),
    (r"\bI don't have (feelings|emotions|personal experiences)\b", "I keep things professional"),
    # Robotic closings
    (r"\bI hope this (helps|answers|clarifies)\b.*?[.!]", ""),
    (r"\bIs there anything else I can (help|assist) you with\??", ""),
    (r"\bLet me know if you (have|need) (any|more) (questions|clarification)\b.*?[.!]", ""),
    # Hollow affirmations mid-sentence
    (r"\bDefinitely[,!]\s*", ""),
    (r"\bAbsolutely[,!]\s*", ""),
    (r"\bCertainly[,!]\s*", ""),
]

# Natural human openers — injected at the start when the response
# doesn't already begin with the persona's name or a question word.
_HUMAN_OPENERS: list[str] = [
    "Right, so— ",
    "Mm, okay. ",
    "Got it. ",
    "I see. ",
    "Sure. ",
    "Okay. ",
    "Alright. ",
    "Mm-hmm. ",
]

# Acknowledgement phrases that precede the next question —
# injected when the shaper detects the response is a follow-up question.
_ACKNOWLEDGEMENTS: list[str] = [
    "That's helpful context.",
    "Good to know.",
    "I appreciate you sharing that.",
    "That gives me a clearer picture.",
    "Interesting — thanks for walking me through that.",
    "Right, that makes sense.",
]

# Pause markers consumed by Phase 2 (Coqui TTS).
# Format: [PAUSE:Xs] where X is seconds (float, 1 decimal).
_SHORT_PAUSE = "[PAUSE:0.6s]"
_MEDIUM_PAUSE = "[PAUSE:1.0s]"
_THINK_PAUSE = "[PAUSE:1.4s]"

# Sentence-boundary pattern — used to insert pauses at natural points.
_SENTENCE_END = re.compile(r"([.!?])\s+(?=[A-Z])")


class HumanResponseShaper:
    """
    Post-processes raw LLM output to sound like a human professional.

    Pipeline (applied in order):
      1. Strip AI tell patterns (regex substitution)
      2. Strip leading/trailing whitespace artefacts
      3. Optionally prepend a natural acknowledgement or opener
      4. Insert [PAUSE:Xs] markers at sentence boundaries
         (consumed by Phase 2 TTS service)
      5. Emit an emotion_state hint for Phase 3 avatar bridge

    All operations are pure string manipulation — no LLM calls.
    This keeps latency at zero for the shaping step.
    """

    def __init__(self, seed: int | None = None) -> None:
        # Fixed seed → deterministic openers per session (less jarring).
        # None → random each time.
        self._rng = random.Random(seed)
        self._compiled = [
            (re.compile(pat, re.IGNORECASE | re.DOTALL), repl)
            for pat, repl in _AI_TELL_PATTERNS
        ]

    # ── Public API ─────────────────────────────────────

    def shape(
        self,
        text: str,
        is_question: bool = True,
        inject_opener: bool = False,
        inject_acknowledgement: bool = False,
    ) -> tuple[str, str]:
        """
        Shape a raw LLM response into human-sounding speech.

        Args:
            text:                  Raw LLM output to shape.
            is_question:           True when the response ends with a question
                                   (most interview turns do). Controls pause placement.
            inject_opener:         Prepend a short natural opener ("Got it. ").
                                   Use for non-opening turns where the shaper
                                   detects the candidate just answered.
            inject_acknowledgement: Prepend an acknowledgement before the next question.
                                   More substantive than an opener.

        Returns:
            (shaped_text, emotion_state)
            emotion_state is a hint for the avatar's facial expression:
              "neutral"  — standard question delivery
              "engaged"  — active listening / positive acknowledgement
              "thinking" — pause before a harder question
        """
        text = self._strip_ai_tells(text)
        text = text.strip()

        if not text:
            return text, "neutral"

        # Prepend acknowledgement or opener (mutually exclusive; ack > opener)
        if inject_acknowledgement:
            ack = self._rng.choice(_ACKNOWLEDGEMENTS)
            text = f"{ack} {_SHORT_PAUSE} {text}"
        elif inject_opener:
            opener = self._rng.choice(_HUMAN_OPENERS)
            text = f"{opener}{text}"

        # Insert pacing pauses at sentence boundaries
        text = self._inject_pauses(text, is_question)

        # Derive emotion hint
        emotion = self._infer_emotion(text)

        return text, emotion

    # ── Internal helpers ───────────────────────────────

    def _strip_ai_tells(self, text: str) -> str:
        for pattern, replacement in self._compiled:
            text = pattern.sub(replacement, text)
        # Collapse multiple spaces left by substitutions
        text = re.sub(r"  +", " ", text)
        return text

    def _inject_pauses(self, text: str, is_question: bool) -> str:
        """
        Insert pause markers at natural sentence boundaries.

        Strategy:
        - Before a question sentence → THINK_PAUSE
        - Between regular sentences → SHORT_PAUSE
        - Max 2 pauses per response to avoid over-engineering.

        re.split with a capturing group produces alternating
        [text, delimiter, text, delimiter, ...] — we recombine
        each text chunk with its trailing punctuation, then insert
        pause markers between the resulting sentences.
        """
        parts = _SENTENCE_END.split(text)
        # parts = ["sentence1", ".", "sentence2", ".", "sentence3"]
        # Recombine: sentence1. / sentence2. / sentence3
        sentences: list[str] = []
        i = 0
        while i < len(parts):
            chunk = parts[i]
            if i + 1 < len(parts) and parts[i + 1] in ".!?":
                sentences.append(chunk + parts[i + 1])
                i += 2
            else:
                sentences.append(chunk)
                i += 1

        if len(sentences) <= 1:
            return text

        result_parts: list[str] = []
        pause_count = 0
        max_pauses = 2

        for idx, sentence in enumerate(sentences):
            result_parts.append(sentence.strip())
            if idx < len(sentences) - 1 and pause_count < max_pauses:
                next_s = sentences[idx + 1].strip()
                # Heavier pause before a question or at the last boundary
                if next_s.endswith("?") or (is_question and idx == len(sentences) - 2):
                    result_parts.append(_THINK_PAUSE)
                else:
                    result_parts.append(_SHORT_PAUSE)
                pause_count += 1

        return " ".join(result_parts)

    def _infer_emotion(self, text: str) -> str:
        """
        Derive a simple emotion state from text content.
        Used by Phase 3 avatar bridge to drive MetaHuman blend shapes.
        """
        lower = text.lower()
        thinking_signals = [_THINK_PAUSE.lower(), "[pause:1", "let me think", "hmm"]
        if any(w in lower for w in ["interesting", "great", "good to know", "appreciate", "helpful"]):
            return "engaged"
        if any(w in lower for w in thinking_signals):
            return "thinking"
        return "neutral"


# ─────────────────────────────────────────────────────
#  Default persona — ready to use out of the box
# ─────────────────────────────────────────────────────

DEFAULT_PERSONA = PersonaConfig(
    name="Sarah Mitchell",
    title="Senior Talent Acquisition Lead",
    company="HireIQ Technologies",
    years_experience=11,
    backstory=(
        "I've been recruiting for tech roles for eleven years, the last four at HireIQ Technologies "
        "where I oversee hiring for engineering and data science positions. "
        "I conduct every stage of the interview myself — I find it gives candidates a consistent experience "
        "and gives me the full picture by the time we make a decision."
    ),
    personality_traits=[
        PersonalityTrait.WARM,
        PersonalityTrait.DIRECT,
        PersonalityTrait.CURIOUS,
    ],
    interview_style="conversational but focused — I like to get specific quickly",
    voice_id="female_en_professional_01",
    reference_audio_path=None,
    speech_rate=0.95,
    avatar_asset_id="corporate_female_01",
    avatar_emotion_default="neutral",
    display_name="Sarah Mitchell",
)

_MARCUS = PersonaConfig(
    name="Marcus Johnson",
    title="Engineering Hiring Manager",
    company="HireIQ Technologies",
    years_experience=14,
    backstory=(
        "Fourteen years in software engineering before moving into hiring — "
        "so I interview the way I'd want to be interviewed: direct, no fluff, technically grounded. "
        "I've built and hired five engineering teams and I run every technical screen myself."
    ),
    personality_traits=[
        PersonalityTrait.DIRECT,
        PersonalityTrait.ANALYTICAL,
        PersonalityTrait.FORMAL,
    ],
    interview_style="structured and technical — I want to see how you think, not just what you know",
    voice_id="male_en_professional_01",
    reference_audio_path=None,
    speech_rate=1.0,
    avatar_asset_id="corporate_male_01",
    avatar_emotion_default="neutral",
    display_name="Marcus Johnson",
)

_PRIYA = PersonaConfig(
    name="Priya Sharma",
    title="Technical Recruiter",
    company="HireIQ Technologies",
    years_experience=5,
    backstory=(
        "I joined HireIQ straight out of my CS degree so I understand both sides of the table — "
        "I've written code and I've evaluated hundreds of candidates. "
        "I run fast-paced interviews focused on problem-solving approach, not memorised answers."
    ),
    personality_traits=[
        PersonalityTrait.ANALYTICAL,
        PersonalityTrait.CURIOUS,
        PersonalityTrait.EMPATHETIC,
    ],
    interview_style="energetic and exploratory — I love digging into your reasoning process",
    voice_id="female_en_professional_02",
    reference_audio_path=None,
    speech_rate=1.05,            # slightly faster — younger, energetic delivery
    avatar_asset_id="corporate_female_02",
    avatar_emotion_default="engaged",
    display_name="Priya Sharma",
)

_DAVID = PersonaConfig(
    name="David O'Brien",
    title="Director of Talent Acquisition",
    company="HireIQ Technologies",
    years_experience=22,
    backstory=(
        "Twenty-two years across finance, consulting, and tech recruiting — "
        "I've seen every interview style there is and I run mine the old-fashioned way: "
        "careful, methodical, with high standards for clarity and depth."
    ),
    personality_traits=[
        PersonalityTrait.FORMAL,
        PersonalityTrait.DIRECT,
        PersonalityTrait.ANALYTICAL,
    ],
    interview_style="methodical and precise — I value depth and clear articulation above all",
    voice_id="male_en_professional_02",
    reference_audio_path=None,
    speech_rate=0.90,            # slower, deliberate — senior, unhurried delivery
    avatar_asset_id="corporate_male_02",
    avatar_emotion_default="neutral",
    display_name="David O'Brien",
)

_ZOE = PersonaConfig(
    name="Zoe Kim",
    title="People & Culture Lead",
    company="HireIQ Technologies",
    years_experience=9,
    backstory=(
        "I started in psychology research before moving into HR — so I look at interviews holistically: "
        "technical ability, communication style, how you handle ambiguity, how you collaborate. "
        "I've led culture and hiring at three scale-ups and I bring that lens to every conversation."
    ),
    personality_traits=[
        PersonalityTrait.EMPATHETIC,
        PersonalityTrait.WARM,
        PersonalityTrait.CURIOUS,
    ],
    interview_style="holistic and human — I care as much about how you think as what you produce",
    voice_id="female_en_professional_03",
    reference_audio_path=None,
    speech_rate=0.97,
    avatar_asset_id="corporate_female_03",
    avatar_emotion_default="engaged",
    display_name="Zoe Kim",
)


# ─────────────────────────────────────────────────────
#  Persona pool + weekly rotation
# ─────────────────────────────────────────────────────

ALL_PERSONAS: list[PersonaConfig] = [
    DEFAULT_PERSONA,   # Sarah Mitchell  — female, 30s, warm/direct
    _MARCUS,           # Marcus Johnson  — male,   40s, direct/analytical
    _PRIYA,            # Priya Sharma    — female, 20s, analytical/energetic
    _DAVID,            # David O'Brien   — male,   50s, formal/senior
    _ZOE,              # Zoe Kim         — female, 40s, empathetic/curious
]


def select_persona(applicant_id: str) -> PersonaConfig:
    """
    Return a deterministic but weekly-rotating persona for this applicant.

    Same applicant_id always gets the same persona within a given ISO week,
    but a different one the following week — so repeat visitors never see
    the identical face twice.

    Algorithm:
        key   = "{applicant_id}:{iso_year}:{iso_week}"
        index = sha256(key)[:8] interpreted as hex integer % len(ALL_PERSONAS)
    """
    now = datetime.utcnow()
    iso_year, iso_week, _ = now.isocalendar()
    key = f"{applicant_id}:{iso_year}:{iso_week}"
    digest = hashlib.sha256(key.encode()).hexdigest()
    index = int(digest[:8], 16) % len(ALL_PERSONAS)
    return ALL_PERSONAS[index]
