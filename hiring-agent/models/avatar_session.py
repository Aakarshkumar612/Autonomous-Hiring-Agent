"""
models/avatar_session.py
═══════════════════════════════════════════════════════
Data models for the avatar interview system.

Covers all phases of the avatar pipeline:
  Phase 1 — AvatarSessionMetadata (links persona to interview session)
  Phase 2 — TTSRequest / TTSResponse (Coqui TTS service contract)
  Phase 3 — VisemeFrame / LipSyncPacket (Unreal Engine bridge)
  Phase 4 — MeetingRoom / MeetingSession (Daily.co video call)

These models are stubs for Phases 2-4 and will be fully
implemented when those connectors are built. Having the
models here now means the orchestration layer can reference
them without circular imports.

All models use Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────
#  Enums
# ─────────────────────────────────────────────────────

class MeetingPlatform(str, Enum):
    """Supported video call platforms."""
    DAILY_CO    = "daily_co"    # Primary — free tier, native bot API
    JITSI       = "jitsi"       # Fallback — self-hosted, unlimited


class MeetingStatus(str, Enum):
    """Lifecycle state of a video meeting room."""
    PENDING     = "pending"     # Room created, candidate not yet joined
    ACTIVE      = "active"      # Interview in progress
    COMPLETED   = "completed"   # Interview finished normally
    ABANDONED   = "abandoned"   # Candidate dropped off
    FAILED      = "failed"      # Technical failure


class TTSStatus(str, Enum):
    """Status of a TTS synthesis request."""
    PENDING     = "pending"
    SYNTHESIZING = "synthesizing"
    READY       = "ready"
    FAILED      = "failed"


class AvatarEmotionState(str, Enum):
    """
    MetaHuman facial expression states.
    Sent to Unreal Engine via avatar_bridge (Phase 3).
    Maps to blend shape presets defined in the UE5 project.
    """
    NEUTRAL     = "neutral"     # default resting face
    ENGAGED     = "engaged"     # slight smile, attentive
    THINKING    = "thinking"    # slight head tilt, contemplative
    NODDING     = "nodding"     # agreement / active listening
    SURPRISED   = "surprised"   # raised brows — for unexpected answers


# ─────────────────────────────────────────────────────
#  Phase 1 — Avatar session metadata
# ─────────────────────────────────────────────────────

class AvatarSessionMetadata(BaseModel):
    """
    Links a persona and avatar configuration to an InterviewSession.

    One AvatarSessionMetadata exists per interview.
    It is created when the avatar interview starts and updated
    as the session progresses through phases.

    Stored alongside the InterviewSession in Supabase.
    """

    # ── Links ──────────────────────────────────────────
    session_id:         str                         # FK → InterviewSession.session_id
    applicant_id:       str                         # FK → Applicant.id
    persona_name:       str                         # e.g. "Sarah Mitchell"
    persona_title:      str                         # e.g. "Senior Talent Acquisition Lead"

    # ── Avatar config ──────────────────────────────────
    avatar_asset_id:    str     = "corporate_female_01"
    voice_id:           str     = "female_en_professional_01"
    current_emotion:    AvatarEmotionState = AvatarEmotionState.NEUTRAL

    # ── Meeting ────────────────────────────────────────
    meeting_platform:   MeetingPlatform     = MeetingPlatform.DAILY_CO
    meeting_room_id:    Optional[str]       = None  # set by Phase 4
    meeting_room_url:   Optional[str]       = None  # candidate invite link
    meeting_status:     MeetingStatus       = MeetingStatus.PENDING

    # ── Timing ────────────────────────────────────────
    avatar_started_at:  Optional[datetime]  = None
    avatar_ended_at:    Optional[datetime]  = None

    # ── Stats ──────────────────────────────────────────
    total_tts_calls:    int = 0             # how many times TTS was invoked
    total_pauses_ms:    int = 0             # cumulative pause duration in ms
    ai_tells_stripped:  int = 0            # how many AI tell patterns were removed

    created_at:         datetime = Field(default_factory=datetime.utcnow)

    def is_live(self) -> bool:
        return self.meeting_status == MeetingStatus.ACTIVE

    def duration_seconds(self) -> Optional[float]:
        if self.avatar_started_at and self.avatar_ended_at:
            return round((self.avatar_ended_at - self.avatar_started_at).total_seconds(), 2)
        return None


# ─────────────────────────────────────────────────────
#  Phase 2 — TTS models (Coqui XTTS v2)
# ─────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    """
    Request to the Coqui TTS service.
    Created by the avatar interview pipeline for each interviewer turn.

    [PAUSE:Xs] markers in `text` are extracted by tts_service
    and converted to silence segments in the output audio.
    """

    text:                   str     = Field(..., min_length=1, description="Text to synthesize (may contain [PAUSE:Xs] markers)")
    voice_id:               str     = Field(default="female_en_professional_01")
    reference_audio_path:   Optional[str] = None    # XTTS v2 voice cloning source
    speech_rate:            float   = Field(default=1.0, ge=0.5, le=2.0)
    language:               str     = Field(default="en")
    session_id:             str     = Field(..., description="Links audio to the interview session")
    turn_index:             int     = Field(default=0, description="Turn number within the session — used for caching")


class TTSResponse(BaseModel):
    """
    Response from the Coqui TTS service.
    Contains the synthesized audio and lip sync metadata.
    """

    request_id:             str
    session_id:             str
    status:                 TTSStatus       = TTSStatus.PENDING
    audio_bytes:            Optional[bytes] = None      # WAV audio
    audio_duration_ms:      Optional[int]   = None      # total duration including pauses
    sample_rate:            int             = 22050
    lip_sync_packet:        Optional["LipSyncPacket"] = None  # Phase 3
    error:                  Optional[str]   = None
    synthesized_at:         Optional[datetime] = None


# ─────────────────────────────────────────────────────
#  Phase 3 — Lip sync / avatar bridge models
# ─────────────────────────────────────────────────────

class VisemeFrame(BaseModel):
    """
    A single viseme (mouth shape) frame for MetaHuman lip sync.

    Sent to Unreal Engine over WebSocket at the start of each
    TTS audio playback. UE5 interpolates between frames to
    produce smooth lip animation.

    Timing is in milliseconds from the start of the audio clip.
    Viseme IDs map to Unreal Engine's built-in ARKit blend shapes
    (e.g. "viseme_sil", "viseme_PP", "viseme_FF", ...).
    """

    time_ms:    int     = Field(..., ge=0, description="Timestamp in ms from audio start")
    viseme_id:  str     = Field(..., description="ARKit viseme blend shape name")
    weight:     float   = Field(..., ge=0.0, le=1.0, description="Blend shape weight 0–1")


class LipSyncPacket(BaseModel):
    """
    Full lip sync data for one TTS audio clip.
    Sent to avatar_bridge (Phase 3) alongside the audio bytes.
    """

    session_id:     str
    turn_index:     int
    audio_duration_ms: int
    frames:         list[VisemeFrame]   = Field(default_factory=list)
    emotion_state:  AvatarEmotionState  = AvatarEmotionState.NEUTRAL


# ─────────────────────────────────────────────────────
#  Phase 4 — Video meeting models (Daily.co)
# ─────────────────────────────────────────────────────

class MeetingRoom(BaseModel):
    """
    A Daily.co video meeting room created for one interview session.

    Created by meeting_bot.py (Phase 4) before the interview starts.
    The candidate receives `candidate_url` via email.
    The bot joins via `bot_token` (a private meeting token).
    """

    room_id:            str
    room_name:          str                         # Daily.co room name (URL slug)
    candidate_url:      str                         # public link sent to candidate
    bot_token:          str                         # private token for bot participant
    platform:           MeetingPlatform = MeetingPlatform.DAILY_CO
    status:             MeetingStatus   = MeetingStatus.PENDING
    max_participants:   int             = 2          # candidate + bot only
    expires_at:         Optional[datetime] = None
    created_at:         datetime        = Field(default_factory=datetime.utcnow)


class MeetingSession(BaseModel):
    """
    Active video call state for a live avatar interview.

    Tracks who has joined, audio/video stream status,
    and links back to the interview session and meeting room.
    """

    session_id:         str                         # FK → InterviewSession.session_id
    room_id:            str                         # FK → MeetingRoom.room_id
    platform:           MeetingPlatform = MeetingPlatform.DAILY_CO
    status:             MeetingStatus   = MeetingStatus.PENDING

    # ── Participant state ──────────────────────────────
    candidate_joined:   bool            = False
    bot_joined:         bool            = False
    candidate_joined_at: Optional[datetime] = None
    bot_joined_at:      Optional[datetime]  = None

    # ── Stream health ──────────────────────────────────
    avatar_video_active: bool           = False     # Pixel Streaming → Daily.co
    tts_audio_active:    bool           = False     # Coqui audio → Daily.co
    stt_active:          bool           = False     # candidate audio → Groq Whisper

    # ── Timing ────────────────────────────────────────
    started_at:         Optional[datetime] = None
    ended_at:           Optional[datetime] = None

    def both_participants_present(self) -> bool:
        return self.candidate_joined and self.bot_joined

    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.ended_at:
            return round((self.ended_at - self.started_at).total_seconds(), 2)
        return None
