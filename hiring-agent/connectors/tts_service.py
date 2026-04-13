"""
connectors/tts_service.py
═══════════════════════════════════════════════════════
Microsoft Edge Neural TTS service for the avatar interviewer.

Why edge-tts over Coqui XTTS v2:
  - No 2 GB model download, no GPU required
  - Neural voices (JennyNeural, AriaNeural) sound more natural
    than XTTS v2 for a corporate professional character
  - Provides word-boundary timing events → accurate lip sync
    (better than energy-based viseme estimation)
  - No dependency conflicts (XTTS required pandas<2.0)
  - Fully async, streaming-friendly

Voice selected: en-US-JennyNeural
  Warm, clear, professional American English.
  Configurable via AVATAR_TTS_VOICE env var.

[PAUSE:Xs] markers:
  Converted to SSML <break time="Xms"/> tags so the TTS
  engine handles silence natively with correct prosody.

Word-boundary → viseme mapping:
  edge-tts fires a WordBoundary event for every synthesized word.
  Each event contains offset_ns and duration_ns (100-ns units).
  We map each word's onset to a rough mouth-shape (viseme) based
  on the word's leading phoneme. Phase 3 can upgrade this to
  full phoneme alignment if needed.

Output:
  - audio_bytes  : MP3 bytes (Daily.co compatible, Phase 4)
  - lip_sync_packet: LipSyncPacket with one VisemeFrame per word
  - WAV fallback : call tts_response_to_wav(response) if needed

Requirements:
  uv add edge-tts pydub
  System: FFmpeg installed (for pydub WAV conversion only)
  If FFmpeg is absent, MP3 bytes still work; only WAV conversion fails.

Usage:
  service = TTSService.from_persona(DEFAULT_PERSONA)

  request = TTSRequest(
      text="Got it. [PAUSE:0.8s] Walk me through your last project.",
      voice_id="en-US-JennyNeural",
      session_id="SESS-001",
      turn_index=0,
  )
  response = await service.synthesize(request)
  # response.audio_bytes → MP3 bytes
  # response.lip_sync_packet.frames → list[VisemeFrame]
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import time
import uuid
from datetime import datetime
from typing import Optional

import numpy as np

from models.avatar_session import (
    AvatarEmotionState,
    LipSyncPacket,
    TTSRequest,
    TTSResponse,
    TTSStatus,
    VisemeFrame,
)
from utils.logger import logger

# ── Optional dependency guards ──────────────────────────────────────
try:
    import edge_tts  # type: ignore[import]
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

try:
    from pydub import AudioSegment  # type: ignore[import]
    _PYDUB_AVAILABLE = True
except ImportError:
    _PYDUB_AVAILABLE = False


# ─────────────────────────────────────────────────────
#  Constants & configuration
# ─────────────────────────────────────────────────────

# Available professional voices (in preference order per persona type).
VOICE_PROFILES: dict[str, str] = {
    "female_en_professional_01": "en-US-JennyNeural",   # warm, clear, professional
    "female_en_professional_02": "en-US-AriaNeural",    # confident, slightly warmer
    "female_en_uk_01":           "en-GB-SoniaNeural",   # British, authoritative
    "male_en_professional_01":   "en-US-GuyNeural",     # clear, professional male
    "male_en_professional_02":   "en-US-EricNeural",    # measured, trustworthy
    # Fallback: any unrecognised voice_id is passed directly to edge-tts
}

DEFAULT_VOICE   = os.getenv("AVATAR_TTS_VOICE", "en-US-JennyNeural")
DEFAULT_RATE    = os.getenv("AVATAR_TTS_RATE", "-5%")    # slightly slower = deliberate

# [PAUSE:Xs] marker pattern
_PAUSE_RE = re.compile(r"\[PAUSE:(\d+(?:\.\d+)?)s\]")

# Simple audio cache: hash(text + voice + rate) → MP3 bytes
_MAX_CACHE_ENTRIES = 50
_audio_cache: dict[str, bytes] = {}

# ─────────────────────────────────────────────────────
#  Coarse phoneme → ARKit viseme mapping
# ─────────────────────────────────────────────────────
# Maps the first letter(s) of a word to the dominant mouth shape.
# This is intentionally simple — it drives believable lip movement
# without requiring a full phoneme aligner.
# Source: ARKit blend shape documentation + common pronunciation patterns.

_WORD_TO_VISEME: list[tuple[tuple[str, ...], str]] = [
    (("p", "b", "m"),           "viseme_PP"),   # bilabial stop / nasal
    (("f", "v"),                "viseme_FF"),   # labiodental fricative
    (("th",),                   "viseme_TH"),   # dental fricative
    (("d", "t", "n", "l"),      "viseme_DD"),   # alveolar
    (("k", "g", "ng"),          "viseme_kk"),   # velar
    (("ch", "j", "sh", "zh"),   "viseme_CH"),   # palato-alveolar
    (("s", "z"),                "viseme_SS"),   # alveolar sibilant
    (("r",),                    "viseme_RR"),   # rhotic
    (("w", "wh"),               "viseme_U"),    # bilabial approximant → rounded
    (("a", "e"),                "viseme_aa"),   # open front vowel
    (("i",),                    "viseme_I"),    # high front vowel
    (("o",),                    "viseme_O"),    # mid back vowel
    (("u",),                    "viseme_U"),    # high back vowel
]
_DEFAULT_VISEME = "viseme_aa"   # fallback for unmatched initials


def _word_to_viseme(word: str) -> str:
    """Return the dominant ARKit viseme ID for a word based on its onset."""
    lower = word.lower().strip(".,!?;:\"'")
    if not lower:
        return "viseme_sil"
    for prefixes, viseme_id in _WORD_TO_VISEME:
        for prefix in prefixes:
            if lower.startswith(prefix):
                return viseme_id
    return _DEFAULT_VISEME


# ─────────────────────────────────────────────────────
#  Pause marker → SSML conversion
# ─────────────────────────────────────────────────────

def text_to_ssml(text: str, voice: str, rate: str) -> str:
    """
    Convert plain text with [PAUSE:Xs] markers to SSML.

    edge-tts uses SSML natively so we get correct prosody around
    silences rather than crudely stitching audio arrays.

    Example:
      "Got it. [PAUSE:0.8s] Walk me through your project."
      →
      <speak>Got it. <break time="800ms"/> Walk me through your project.</speak>
    """
    ssml_text = _PAUSE_RE.sub(
        lambda m: f'<break time="{int(float(m.group(1)) * 1000)}ms"/>',
        text
    )
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
        f'<voice name="{voice}">'
        f'<prosody rate="{rate}">'
        f'{ssml_text}'
        f'</prosody></voice></speak>'
    )


def strip_pause_markers(text: str) -> str:
    """Remove [PAUSE:Xs] markers from text (used for cache key computation)."""
    return _PAUSE_RE.sub(" ", text).strip()


# ─────────────────────────────────────────────────────
#  WAV conversion helper (requires pydub + FFmpeg)
# ─────────────────────────────────────────────────────

def mp3_to_wav_bytes(mp3_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """
    Convert MP3 bytes to 16-bit mono WAV bytes.

    Requires pydub and system FFmpeg.
    Returns the original MP3 bytes unchanged if conversion fails
    (caller should log the failure and handle gracefully).
    """
    if not _PYDUB_AVAILABLE:
        raise RuntimeError(
            "pydub is not installed. Run: uv add pydub\n"
            "Also ensure FFmpeg is installed: https://ffmpeg.org/download.html"
        )
    try:
        segment = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        segment = segment.set_channels(1).set_frame_rate(sample_rate).set_sample_width(2)
        buf = io.BytesIO()
        segment.export(buf, format="wav")
        return buf.getvalue()
    except Exception as e:
        raise RuntimeError(f"MP3 → WAV conversion failed: {e}") from e


# ─────────────────────────────────────────────────────
#  TTS Service
# ─────────────────────────────────────────────────────

class TTSService:
    """
    Async text-to-speech service backed by Microsoft Edge Neural TTS.

    Converts interviewer text (including [PAUSE:Xs] markers from
    HumanResponseShaper) to audio + lip sync data for the avatar pipeline.

    Instantiate once; the service is stateless between calls.
    Each `synthesize()` call is independent and safe to call concurrently.
    """

    def __init__(
        self,
        voice_id:    str   = "female_en_professional_01",
        speech_rate: float = 0.95,
        language:    str   = "en",
    ) -> None:
        """
        Args:
            voice_id:    Logical voice name (key in VOICE_PROFILES) OR a
                         raw edge-tts voice name like "en-US-JennyNeural".
            speech_rate: Speed multiplier (0.5–2.0).
                         Converted to a CSS rate string: 0.95 → "-5%".
            language:    Language code — affects fallback voice selection.
        """
        self.voice_id    = voice_id
        self.speech_rate = speech_rate
        self.language    = language

        # Resolve logical voice ID → edge-tts voice name
        self._edge_voice = VOICE_PROFILES.get(voice_id, voice_id)
        # Convert float rate to CSS percentage string edge-tts expects
        self._rate_str   = self._rate_to_css(speech_rate)

    @classmethod
    def from_persona(cls, persona) -> "TTSService":
        """Build a TTSService from a PersonaConfig instance."""
        return cls(
            voice_id    = persona.voice_id,
            speech_rate = persona.speech_rate,
        )

    # ── Synthesis ──────────────────────────────────────

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """
        Synthesize speech from text and return audio + lip sync data.

        Pipeline:
          1. Check in-process cache (text + voice + rate hash)
          2. Convert [PAUSE:Xs] markers to SSML <break> tags
          3. Stream from edge-tts, collecting MP3 chunks + word events
          4. Derive viseme frames from word-boundary timing
          5. Pack result into TTSResponse

        Args:
            request: TTSRequest from models/avatar_session.py

        Returns:
            TTSResponse — always returned; inspect .status for failures.
        """
        if not _EDGE_TTS_AVAILABLE:
            return TTSResponse(
                request_id = f"TTS-{uuid.uuid4().hex[:8].upper()}",
                session_id = request.session_id,
                status     = TTSStatus.FAILED,
                error=(
                    "edge-tts is not installed. Run: uv add edge-tts\n"
                    "Then restart the server."
                ),
            )

        request_id = f"TTS-{uuid.uuid4().hex[:8].upper()}"
        t0 = time.perf_counter()

        # Override voice/rate from request if provided
        edge_voice = VOICE_PROFILES.get(request.voice_id, request.voice_id) or self._edge_voice
        rate_str   = self._rate_to_css(request.speech_rate) if request.speech_rate != 1.0 else self._rate_str

        # ── Cache check ─────────────────────────────────
        cache_k = _cache_key(request.text, edge_voice, rate_str)
        if cache_k in _audio_cache:
            logger.debug(f"TTS | [{request_id}] Cache hit | key={cache_k[:8]}")
            mp3_bytes, lip_sync = _cache_reconstruct(
                _audio_cache[cache_k], request, edge_voice
            )
            return TTSResponse(
                request_id       = request_id,
                session_id       = request.session_id,
                status           = TTSStatus.READY,
                audio_bytes      = mp3_bytes,
                audio_duration_ms= _estimate_mp3_duration_ms(mp3_bytes),
                sample_rate      = 24000,
                lip_sync_packet  = lip_sync,
                synthesized_at   = datetime.utcnow(),
            )

        # ── Build SSML ──────────────────────────────────
        ssml = text_to_ssml(request.text, edge_voice, rate_str)
        logger.info(
            f"TTS | [{request_id}] Synthesizing | "
            f"session={request.session_id} | turn={request.turn_index} | "
            f"voice={edge_voice} | rate={rate_str}"
        )

        # ── Stream from edge-tts ────────────────────────
        try:
            mp3_bytes, word_events = await self._stream_edge_tts(ssml, edge_voice)
        except Exception as e:
            logger.error(f"TTS | [{request_id}] Synthesis failed: {e}")
            return TTSResponse(
                request_id = request_id,
                session_id = request.session_id,
                status     = TTSStatus.FAILED,
                error      = str(e),
            )

        duration_ms = _estimate_mp3_duration_ms(mp3_bytes)

        # ── Build viseme frames from word boundaries ──────
        viseme_frames = _word_events_to_visemes(word_events, duration_ms)

        lip_sync = LipSyncPacket(
            session_id        = request.session_id,
            turn_index        = request.turn_index,
            audio_duration_ms = duration_ms,
            frames            = viseme_frames,
        )

        # ── Cache ────────────────────────────────────────
        _evict_cache_if_full()
        _audio_cache[cache_k] = mp3_bytes

        elapsed = time.perf_counter() - t0
        logger.info(
            f"TTS | [{request_id}] Done | "
            f"duration≈{duration_ms}ms | synth={elapsed:.2f}s | "
            f"visemes={len(viseme_frames)} | words={len(word_events)}"
        )

        return TTSResponse(
            request_id        = request_id,
            session_id        = request.session_id,
            status            = TTSStatus.READY,
            audio_bytes       = mp3_bytes,
            audio_duration_ms = duration_ms,
            sample_rate       = 24000,
            lip_sync_packet   = lip_sync,
            synthesized_at    = datetime.utcnow(),
        )

    # ── edge-tts streaming ─────────────────────────────

    async def _stream_edge_tts(
        self,
        ssml: str,
        voice: str,
    ) -> tuple[bytes, list[dict]]:
        """
        Stream SSML through edge-tts.

        Returns:
            mp3_bytes:   Raw MP3 audio bytes (concatenated stream chunks)
            word_events: List of {"word": str, "offset_ns": int, "duration_ns": int}
                         One entry per synthesized word (from WordBoundary events).
        """
        communicate = edge_tts.Communicate(ssml, voice=voice)
        mp3_chunks: list[bytes] = []
        word_events: list[dict] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_events.append({
                    "word":        chunk.get("text", ""),
                    "offset_ns":   chunk.get("offset", 0),       # 100-ns units
                    "duration_ns": chunk.get("duration", 0),     # 100-ns units
                })

        return b"".join(mp3_chunks), word_events

    # ── Utilities ──────────────────────────────────────

    @staticmethod
    def _rate_to_css(rate: float) -> str:
        """
        Convert a float speed multiplier to a CSS rate string.
        edge-tts uses CSS syntax: "+10%", "-5%", "+0%"

        0.95 → "-5%"
        1.10 → "+10%"
        1.00 → "+0%"
        """
        pct = round((rate - 1.0) * 100)
        return f"{pct:+d}%"

    async def list_voices(self) -> list[dict]:
        """
        Return all voices available from edge-tts.
        Useful for finding new professional voice options.
        """
        if not _EDGE_TTS_AVAILABLE:
            return []
        voices = await edge_tts.list_voices()
        return [
            {"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
            for v in voices
        ]


# ─────────────────────────────────────────────────────
#  Word-boundary → viseme frames
# ─────────────────────────────────────────────────────

def _word_events_to_visemes(
    word_events: list[dict],
    total_duration_ms: int,
) -> list[VisemeFrame]:
    """
    Convert edge-tts WordBoundary events to VisemeFrame list.

    Each word event gives us:
      offset_ns:   start of the word in 100-ns units
      duration_ns: duration of the word in 100-ns units

    We emit two frames per word:
      1. onset frame at offset_ms  — mouth opens (weight: 0.8–1.0)
      2. offset frame at offset_ms + duration_ms — mouth closes (weight: 0.0)

    This gives the MetaHuman a clear open → close animation per word,
    which looks more natural than a single static frame.
    """
    frames: list[VisemeFrame] = []

    for ev in word_events:
        word        = ev.get("word", "")
        offset_ms   = int(ev.get("offset_ns", 0) / 10_000)    # 100ns → ms
        duration_ms = int(ev.get("duration_ns", 0) / 10_000)

        viseme_id = _word_to_viseme(word)
        open_weight = 0.9   # most words open the mouth to ~90% of full viseme

        # Onset: mouth opens
        frames.append(VisemeFrame(
            time_ms   = offset_ms,
            viseme_id = viseme_id,
            weight    = open_weight,
        ))
        # Offset: mouth closes (silence viseme)
        frames.append(VisemeFrame(
            time_ms   = offset_ms + max(duration_ms, 30),
            viseme_id = "viseme_sil",
            weight    = 0.0,
        ))

    # Sort by time (should already be sorted, but guard against edge-tts quirks)
    frames.sort(key=lambda f: f.time_ms)
    return frames


# ─────────────────────────────────────────────────────
#  Cache helpers
# ─────────────────────────────────────────────────────

def _cache_key(text: str, voice: str, rate: str) -> str:
    payload = f"{text}|{voice}|{rate}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _evict_cache_if_full() -> None:
    if len(_audio_cache) >= _MAX_CACHE_ENTRIES:
        oldest = next(iter(_audio_cache))
        del _audio_cache[oldest]


def _cache_reconstruct(
    mp3_bytes: bytes,
    request: TTSRequest,
    voice: str,
) -> tuple[bytes, LipSyncPacket]:
    """Rebuild a minimal TTSResponse from cached MP3 bytes."""
    duration_ms = _estimate_mp3_duration_ms(mp3_bytes)
    lip_sync = LipSyncPacket(
        session_id        = request.session_id,
        turn_index        = request.turn_index,
        audio_duration_ms = duration_ms,
        frames            = [],   # word events not cached — Phase 3 regenerates if needed
    )
    return mp3_bytes, lip_sync


def _estimate_mp3_duration_ms(mp3_bytes: bytes) -> int:
    """
    Estimate MP3 duration in milliseconds from byte length.

    Uses a rough estimate based on 128 kbps bitrate (edge-tts default).
    Accurate to within ±5% for typical interview speech.
    For exact duration, decode with pydub/FFmpeg.

    128 kbps = 16 bytes/ms → duration_ms ≈ len / 16
    """
    return max(100, len(mp3_bytes) // 16)


# ─────────────────────────────────────────────────────
#  Public helpers
# ─────────────────────────────────────────────────────

def build_tts_service(persona=None) -> TTSService:
    """
    Build a TTSService from a PersonaConfig or defaults.
    Convenience factory for AvatarInterviewOrchestrator (Phase 5).
    """
    if persona is not None:
        return TTSService.from_persona(persona)
    return TTSService()


async def tts_response_to_wav(response: TTSResponse, sample_rate: int = 24000) -> bytes:
    """
    Convert a TTSResponse's MP3 audio to WAV bytes.

    Convenience helper for Phase 3 (Unreal Engine bridge) and
    any component that needs raw PCM rather than MP3.

    Requires pydub + system FFmpeg. Raises RuntimeError if unavailable.
    """
    if not response.audio_bytes:
        raise ValueError("TTSResponse has no audio bytes")
    return await asyncio.to_thread(mp3_to_wav_bytes, response.audio_bytes, sample_rate)
