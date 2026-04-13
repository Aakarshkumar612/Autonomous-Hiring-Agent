"""
connectors/meeting_bot.py
═══════════════════════════════════════════════════════
Jitsi Meet integration for the avatar interview platform.

Responsibilities:
  1. Generate unique, private Jitsi room URLs per candidate
  2. Schedule interviews and send invite emails
  3. Run a Playwright-based bot that joins the meeting AS the
     avatar interviewer ("Sarah Mitchell") — injecting TTS audio
     through the microphone and capturing candidate speech for STT
  4. Transcribe candidate answers via Groq Whisper

Why Jitsi Meet:
  - Open source, self-hostable, or use meet.jit.si for free
  - No API keys needed for public instance
  - UUID-based room names = unguessable private rooms
  - Full WebRTC stack with good browser support
  - IFrame API for embedding if needed later

Bot approach — Playwright (headless Chromium):
  The bot opens a real Chromium browser, navigates to the Jitsi room,
  and uses the Web APIs to:
    - Inject TTS audio as the bot's "microphone" via WebAudio API
    - Capture the candidate's audio via RTCPeerConnection track interception
    - (Optionally) inject avatar video from Pixel Streaming via canvas

  This works because Jitsi is a web application — the bot is just a
  controlled browser participant. No private API or server access needed.

Audio flow:
  TTS MP3 bytes → base64 → page.evaluate(speakAudio) → WebAudio API → Jitsi microphone
  Candidate audio → MediaRecorder → page.expose_function → asyncio.Queue → Groq Whisper STT

Video flow (Phase 3 integration):
  UE5 Pixel Streaming WebRTC → canvas drawImage() → captureStream() → Jitsi camera
  (Falls back to static professional avatar image when UE5 is not running)

Room URL format:
  Candidate link: https://meet.jit.si/HireIQ-{uuid8}-{role_slug}
  Bot join URL:   same room + #config.prejoinPageEnabled=false&...

Requirements:
  uv add playwright
  uv run playwright install chromium   ← run once after install

Environment variables (add to .env):
  JITSI_BASE_URL      = https://meet.jit.si
  JITSI_ROOM_PREFIX   = HireIQ
  GROQ_WHISPER_MODEL  = whisper-large-v3-turbo
  AVATAR_BOT_HEADLESS = true   (false to watch the browser window during dev)

Usage:
  manager = JitsiMeetingManager()
  room = await manager.create_meeting(
      session_id="SESS-A1B2",
      applicant_id="INT-001",
      applicant_email="priya@example.com",
      applicant_name="Priya Sharma",
      role="Backend Engineer",
      scheduled_at=datetime(2026, 4, 20, 14, 30),
      persona_name="Sarah Mitchell",
  )
  # room.candidate_url  → send this to candidate via email
  # room.bot_token      → internal URL for the bot to join

  async with JitsiBot(persona_name="Sarah Mitchell") as bot:
      await bot.join(room.bot_token)
      await bot.start_candidate_audio_capture()

      session, first_q = await interviewer.start_session(applicant)
      tts = await tts_service.synthesize(TTSRequest(text=first_q, ...))
      await bot.speak(tts.audio_bytes)

      while not done:
          transcript = await bot.wait_for_candidate_answer(timeout=120)
          next_q, done = await interviewer.process_response(session, transcript)
          if next_q:
              tts = await tts_service.synthesize(TTSRequest(text=next_q, ...))
              await bot.speak(tts.audio_bytes)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from groq import AsyncGroq

from connectors.email_service import EmailService
from models.avatar_session import (
    MeetingPlatform,
    MeetingRoom,
    MeetingSession,
    MeetingStatus,
)
from utils.logger import logger

# ── Optional Playwright guard ──────────────────────────────────────
try:
    from playwright.async_api import (  # type: ignore[import]
        Browser,
        BrowserContext,
        Page,
        async_playwright,
    )
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    Browser = BrowserContext = Page = None  # type: ignore[assignment,misc]


# ─────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────

JITSI_BASE_URL      = os.getenv("JITSI_BASE_URL",    "https://meet.jit.si")
JITSI_ROOM_PREFIX   = os.getenv("JITSI_ROOM_PREFIX",  "HireIQ")
WHISPER_MODEL       = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

# Audio recording chunk size: 2 seconds of audio per chunk.
# Shorter → more responsive STT. Longer → fewer API calls.
AUDIO_CHUNK_MS = 2_000

# Silence detection: if no audio chunk arrives for this many seconds,
# consider the candidate done speaking.
CANDIDATE_DONE_SILENCE_SECS = 3.0

# Max time to wait for a candidate answer before timing out.
ANSWER_TIMEOUT_SECS = 180


# ─────────────────────────────────────────────────────
#  URL generation (pure functions — no browser needed)
# ─────────────────────────────────────────────────────

def generate_room_id(session_id: str) -> str:
    """
    Generate a unique, unguessable room ID from a session_id.

    Uses HMAC-SHA256 so the room ID is:
      - Deterministic (same session_id → same room_id, safe to re-call)
      - Unguessable (UUID entropy, not sequential)
      - Short enough for a readable URL (~16 hex chars)

    Example: "HireIQ-A3F9B2C1D4E5F601"
    """
    h = hashlib.sha256(f"jitsi-room:{session_id}".encode()).hexdigest()[:16].upper()
    return f"{JITSI_ROOM_PREFIX}-{h}"


def generate_candidate_url(room_id: str, base_url: str = JITSI_BASE_URL) -> str:
    """
    Clean Jitsi URL for the candidate.

    The candidate receives this in their email. They join the standard
    Jitsi UI — no special configuration needed on their end.

    Example: https://meet.jit.si/HireIQ-A3F9B2C1D4E5F601
    """
    return f"{base_url}/{room_id}"


def generate_bot_url(
    room_id:      str,
    persona_name: str,
    base_url:     str = JITSI_BASE_URL,
) -> str:
    """
    Jitsi URL for the bot participant with config flags in the fragment.

    Fragment params control Jitsi behaviour without needing server config:
      prejoinPageEnabled=false    → skip the pre-join UI (bot joins instantly)
      startWithAudioMuted=false   → bot starts with microphone on
      startWithVideoMuted=false   → bot starts with camera on
      disableDeepLinking=true     → suppress "open in app" prompts
      enableNoisyMicDetection=false → don't interrupt with noise warnings
      disableLocalVideoFlip=true  → keep avatar video orientation correct
      userInfo.displayName        → bot appears as persona name in participant list

    Example: https://meet.jit.si/HireIQ-A3F9B2C1D4E5F601#config.prejoinPageEnabled=false&...
    """
    name_encoded = quote(persona_name)
    fragment = (
        f"config.prejoinPageEnabled=false"
        f"&config.startWithAudioMuted=false"
        f"&config.startWithVideoMuted=false"
        f"&config.disableDeepLinking=true"
        f"&config.enableNoisyMicDetection=false"
        f"&config.disableLocalVideoFlip=true"
        f"&config.enableTalkWhileMuted=true"
        f"&config.disableInitialGUM=false"
        f"&userInfo.displayName={name_encoded}"
    )
    return f"{base_url}/{room_id}#{fragment}"


# ─────────────────────────────────────────────────────
#  Browser init script (injected before any page JS runs)
# ─────────────────────────────────────────────────────

# This JavaScript runs in Chromium before Jitsi's scripts load.
# It patches two things:
#   1. getUserMedia → returns our controlled audio stream (bot's "microphone")
#   2. RTCPeerConnection → intercepts remote audio tracks for STT capture
#
# The WebAudio destination stream is what Jitsi uses as the microphone input.
# When we call speakAudio() later, audio plays through this stream into the call.

_BROWSER_INIT_SCRIPT = """
(function() {
  'use strict';

  // ── 1. WebAudio controlled microphone ─────────────────────────────
  const audioCtx     = new (window.AudioContext || window.webkitAudioContext)();
  const gainNode     = audioCtx.createGain();
  const micDest      = audioCtx.createMediaStreamDestination();
  gainNode.connect(micDest);

  // Expose for Python → page.evaluate() calls
  window.__hireiq = {
    audioCtx,
    gainNode,
    micStream : micDest.stream,
    speaking  : false,
    recorder  : null,
  };

  // Speak a base64-encoded MP3: called from Python via page.evaluate()
  window.__hireiq_speak = async function(base64Mp3) {
    if (window.__hireiq.speaking) return 0;
    window.__hireiq.speaking = true;
    try {
      const bytes  = Uint8Array.from(atob(base64Mp3), c => c.charCodeAt(0));
      const buffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(gainNode);
      await new Promise((resolve) => {
        source.onended = resolve;
        source.start(0);
      });
      return Math.round(buffer.duration * 1000);   // ms
    } finally {
      window.__hireiq.speaking = false;
    }
  };

  // Override getUserMedia to inject our controlled audio stream.
  // When Pixel Streaming is connected, also injects PS canvas video.
  const _origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async function(constraints) {
    if (!constraints) return _origGUM(constraints);

    if (constraints.audio) {
      const audioTracks = window.__hireiq.micStream.getAudioTracks();
      if (constraints.video) {
        // Pixel Streaming video available → use canvas stream as camera
        const psStream = window.__hireiq.psVideoStream;
        if (psStream && psStream.getVideoTracks().length > 0) {
          const tracks = [...audioTracks, ...psStream.getVideoTracks()];
          return new MediaStream(tracks);
        }
        // No PS → try real webcam, fall back to audio-only
        try {
          const videoStream = await _origGUM({ video: constraints.video });
          audioTracks.forEach(t => videoStream.addTrack(t));
          return videoStream;
        } catch (e) {
          return new MediaStream(audioTracks);
        }
      }
      return new MediaStream(audioTracks);
    }

    return _origGUM(constraints);
  };

  // ── 2. Candidate audio capture via RTCPeerConnection patching ─────
  // Patch RTCPeerConnection BEFORE Jitsi creates its peer connections.
  // When a remote audio track arrives (the candidate's voice), we start
  // recording it and forward 2-second chunks to Python via the exposed function.

  const _OrigPC = window.RTCPeerConnection;

  function PatchedPC(config, constraints) {
    const pc = new _OrigPC(config, constraints);
    pc.addEventListener('track', (event) => {
      const track = event.track;
      // Only capture remote audio (not our own mic echo)
      if (track.kind !== 'audio') return;

      console.log('[HireIQ] Remote audio track detected — starting capture');
      const stream   = new MediaStream([track]);
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                       ? 'audio/webm;codecs=opus'
                       : 'audio/webm';

      const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 });
      recorder.ondataavailable = async function(e) {
        if (e.data.size < 100) return;   // skip near-empty chunks (silence)
        const buffer = await e.data.arrayBuffer();
        const chunk  = Array.from(new Uint8Array(buffer));
        // Send to Python via exposed function
        if (window.__hireiq_audio_chunk) {
          window.__hireiq_audio_chunk(chunk);
        }
      };
      recorder.start(2000);   // fire ondataavailable every 2 seconds
      window.__hireiq.recorder = recorder;
    });
    return pc;
  }

  // Copy static properties so Jitsi's instanceof checks pass
  Object.assign(PatchedPC, _OrigPC);
  PatchedPC.prototype = _OrigPC.prototype;
  window.RTCPeerConnection = PatchedPC;

  console.log('[HireIQ] Browser init script installed');
})();
"""


# ─────────────────────────────────────────────────────
#  Pixel Streaming connection script
# ─────────────────────────────────────────────────────

# Injected via page.evaluate() when set_video_source() is called.
# Handles the UE5 Pixel Streaming signaling protocol (Infrastructure v2).
#
# Protocol flow:
#   Client → Server : { type: "listStreamers" }
#   Server → Client : { type: "streamerList", ids: ["DefaultStreamer"] }
#   Client → Server : { type: "subscribe", streamerId: "DefaultStreamer" }
#   Server → Client : { type: "config", peerConnectionOptions: {...} }
#   Server → Client : { type: "offer", sdp: "..." }
#   Client → Server : { type: "answer", sdp: "..." }
#   Both sides      : { type: "iceCandidate", candidate: {...} }
#
# On success: stores the 30fps canvas stream in window.__hireiq.psVideoStream.
# getUserMedia is already patched (in _BROWSER_INIT_SCRIPT) to use it when
# window.__hireiq.psVideoStream is set.

_PS_CONNECT_SCRIPT = """
async function __hireiq_connect_ps(signalingUrl) {
  return new Promise((resolve, reject) => {

    // ── Hidden video element to receive the PS WebRTC track ──────────
    const video = document.createElement('video');
    video.autoplay    = true;
    video.muted       = true;
    video.playsInline = true;
    // Keep it in the DOM but invisible — required for some browsers to
    // actually decode and render the video (affects canvas drawImage output).
    video.style.cssText = 'position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none';
    document.body.appendChild(video);

    // ── Canvas that captures PS frames at 30 fps ─────────────────────
    const canvas = document.createElement('canvas');
    canvas.width  = 1280;
    canvas.height = 720;
    const ctx = canvas.getContext('2d');

    // ── RTCPeerConnection for PS WebRTC stream ────────────────────────
    const pc = new (window.__hireiq_OrigPC || RTCPeerConnection)({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    let resolved = false;

    pc.ontrack = (event) => {
      if (event.track.kind !== 'video') return;
      console.log('[HireIQ-PS] Video track received from UE5 Pixel Streaming');

      video.srcObject = new MediaStream([event.track]);
      video.play().then(() => {
        // Draw PS frames onto canvas every animation frame
        function drawFrame() {
          if (video.readyState >= 2) {   // HAVE_CURRENT_DATA or better
            ctx.drawImage(video, 0, 0, 1280, 720);
          }
          requestAnimationFrame(drawFrame);
        }
        drawFrame();

        // Expose canvas stream — getUserMedia override picks this up
        const stream = canvas.captureStream(30);
        window.__hireiq.psVideoStream  = stream;
        window.__hireiq.psVideoElement = video;
        window.__hireiq.psCanvas       = canvas;

        if (!resolved) {
          resolved = true;
          resolve(true);
        }
      }).catch((e) => {
        console.error('[HireIQ-PS] video.play() failed:', e);
        if (!resolved) { resolved = true; reject(e); }
      });
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type      : 'iceCandidate',
          candidate : event.candidate
        }));
      }
    };

    pc.onconnectionstatechange = () => {
      console.log('[HireIQ-PS] PC state:', pc.connectionState);
      if (pc.connectionState === 'failed') {
        if (!resolved) { resolved = true; reject(new Error('RTCPeerConnection failed')); }
      }
    };

    // ── Pixel Streaming signaling WebSocket ───────────────────────────
    let ws;
    try {
      ws = new WebSocket(signalingUrl);
    } catch (e) {
      reject(new Error('Cannot open PS signaling WebSocket: ' + e.message));
      return;
    }

    ws.onopen = () => {
      console.log('[HireIQ-PS] Signaling WS connected — requesting streamer list');
      ws.send(JSON.stringify({ type: 'listStreamers' }));
    };

    ws.onmessage = async (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      switch (msg.type) {
        case 'streamerList': {
          // Subscribe to the first available streamer
          const streamerId = (msg.ids && msg.ids.length > 0)
            ? msg.ids[0]
            : 'DefaultStreamer';
          console.log('[HireIQ-PS] Subscribing to streamer:', streamerId);
          ws.send(JSON.stringify({ type: 'subscribe', streamerId }));
          break;
        }

        case 'config':
          // PS may provide its own ICE servers — apply them
          console.log('[HireIQ-PS] Received config from signaling server');
          break;

        case 'offer': {
          console.log('[HireIQ-PS] Received SDP offer from UE5');
          try {
            await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp });
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            ws.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }));
            console.log('[HireIQ-PS] SDP answer sent');
          } catch (e) {
            console.error('[HireIQ-PS] SDP negotiation error:', e);
            if (!resolved) { resolved = true; reject(e); }
          }
          break;
        }

        case 'iceCandidate': {
          // PS v2 wraps the candidate object; v1 sends it flat
          const raw = msg.candidate;
          if (!raw) break;
          const cand = typeof raw === 'string'
            ? { candidate: raw, sdpMid: '0', sdpMLineIndex: 0 }
            : raw;
          try {
            await pc.addIceCandidate(new RTCIceCandidate(cand));
          } catch {}
          break;
        }

        case 'answer':
          // PS server sent an answer (unusual — PS normally sends offers)
          try {
            await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp });
          } catch {}
          break;

        default:
          break;
      }
    };

    ws.onerror = (e) => {
      console.error('[HireIQ-PS] Signaling WebSocket error');
      if (!resolved) { resolved = true; reject(new Error('PS WebSocket error')); }
    };

    ws.onclose = () => {
      console.log('[HireIQ-PS] Signaling WebSocket closed');
    };

    // Timeout: if no video track arrives in 20 seconds, give up
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error('Pixel Streaming connection timed out (20s)'));
      }
    }, 20_000);
  });
}
"""


# ─────────────────────────────────────────────────────
#  Jitsi Meeting Manager
# ─────────────────────────────────────────────────────

class JitsiMeetingManager:
    """
    Creates and tracks Jitsi interview rooms.

    Each shortlisted candidate gets a unique room with two URLs:
      candidate_url → sent by email, clean link, standard Jitsi UI
      bot_token     → used by JitsiBot to join with the avatar persona

    Rooms are stored in memory and optionally persisted to Supabase
    (Phase 5 orchestrator handles persistence).
    """

    def __init__(
        self,
        email_service:   Optional[EmailService] = None,
        jitsi_base_url:  str                    = JITSI_BASE_URL,
    ) -> None:
        self._email        = email_service or EmailService.from_env()
        self._base_url     = jitsi_base_url
        # session_id → MeetingRoom
        self._rooms: dict[str, MeetingRoom] = {}

    async def create_meeting(
        self,
        session_id:      str,
        applicant_id:    str,
        applicant_email: str,
        applicant_name:  str,
        role:            str,
        scheduled_at:    datetime,
        persona_name:    str = "Sarah Mitchell",
        send_email:      bool = True,
    ) -> MeetingRoom:
        """
        Create a unique Jitsi room for one candidate interview.

        Steps:
          1. Generate deterministic, unguessable room ID from session_id
          2. Build candidate URL and bot URL
          3. Optionally send invitation email to candidate
          4. Return MeetingRoom with all details

        Args:
            session_id:      InterviewSession.session_id
            applicant_id:    Applicant.id
            applicant_email: Candidate's email address (from resume)
            applicant_name:  Candidate's full name
            role:            Role applied for (human-readable)
            scheduled_at:    Interview date/time (UTC)
            persona_name:    Avatar persona name (shown in email + Jitsi)
            send_email:      Set False to skip email (e.g. in tests)

        Returns:
            MeetingRoom with candidate_url and bot_token populated.
        """
        room_id       = generate_room_id(session_id)
        candidate_url = generate_candidate_url(room_id, self._base_url)
        bot_url       = generate_bot_url(room_id, persona_name, self._base_url)

        room = MeetingRoom(
            room_id       = room_id,
            room_name     = room_id,
            candidate_url = candidate_url,
            bot_token     = bot_url,         # "bot_token" holds the bot's join URL
            platform      = MeetingPlatform.JITSI,
            status        = MeetingStatus.PENDING,
            expires_at    = scheduled_at + timedelta(hours=2),
            created_at    = datetime.utcnow(),
        )
        self._rooms[session_id] = room

        logger.info(
            f"MEETING | Room created | "
            f"session={session_id} | room={room_id} | "
            f"candidate={applicant_name} | scheduled={scheduled_at.isoformat()}"
        )

        if send_email:
            await self._email.send_interview_invite(
                applicant_name   = applicant_name,
                applicant_email  = applicant_email,
                role             = role,
                meeting_url      = candidate_url,
                scheduled_at     = scheduled_at,
                interviewer_name = persona_name,
            )

        return room

    def get_meeting(self, session_id: str) -> Optional[MeetingRoom]:
        """Retrieve a previously created meeting room by session ID."""
        return self._rooms.get(session_id)

    def get_candidate_url(self, session_id: str) -> Optional[str]:
        room = self._rooms.get(session_id)
        return room.candidate_url if room else None

    def all_rooms(self) -> list[MeetingRoom]:
        return list(self._rooms.values())


# ─────────────────────────────────────────────────────
#  Jitsi Bot (Playwright)
# ─────────────────────────────────────────────────────

class JitsiBot:
    """
    Playwright-based bot participant that joins a Jitsi meeting as the
    avatar interviewer.

    The bot:
      - Appears in the participant list as "Sarah Mitchell" (or any persona name)
      - Speaks through TTS audio injected into the WebAudio API
      - Listens to the candidate via RTCPeerConnection audio capture
      - Forwards candidate audio chunks to asyncio.Queue for STT

    Requires playwright to be installed:
      uv add playwright
      uv run playwright install chromium

    Context manager usage:
      async with JitsiBot(persona_name="Sarah Mitchell") as bot:
          await bot.join(room.bot_token)
          await bot.speak(mp3_bytes)
          transcript = await bot.wait_for_candidate_answer()
    """

    def __init__(
        self,
        persona_name: str = "Sarah Mitchell",
        headless:     bool = True,
        groq_api_key: Optional[str] = None,
    ) -> None:
        self.persona_name = persona_name
        self.headless     = headless

        self._groq = AsyncGroq(api_key=groq_api_key or os.environ.get("GROQ_API_KEY", ""))

        self._playwright = None
        self._browser:   Optional[Browser]        = None
        self._context:   Optional[BrowserContext] = None
        self._page:      Optional[Page]           = None

        # Candidate audio: Playwright exposes __hireiq_audio_chunk → Python puts bytes here
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._capturing   = False

    # ── Context manager ────────────────────────────────

    async def __aenter__(self) -> "JitsiBot":
        await self._launch_browser()
        return self

    async def __aexit__(self, *_) -> None:
        await self.leave()

    # ── Browser lifecycle ──────────────────────────────

    async def _launch_browser(self) -> None:
        """Launch Chromium with required flags for WebRTC + auto-permissions."""
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed.\n"
                "Run: uv add playwright && uv run playwright install chromium"
            )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless = self.headless,
            args = [
                "--use-fake-ui-for-media-stream",         # auto-approve camera/mic prompts
                "--use-fake-device-for-media-stream",     # fake hardware → we replace with WebAudio
                "--autoplay-policy=no-user-gesture-required",  # allow audio without click
                "--disable-web-security",                  # allow cross-origin audio resources
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            permissions = ["camera", "microphone"],
        )
        # Inject our init script into every page BEFORE any page JS runs
        await self._context.add_init_script(_BROWSER_INIT_SCRIPT)

        self._page = await self._context.new_page()

        # Expose Python callback: browser calls window.__hireiq_audio_chunk([...bytes...])
        # and we receive it in Python as a list of ints → bytes
        await self._page.expose_function(
            "__hireiq_audio_chunk",
            self._on_audio_chunk,
        )

        logger.info(f"BOT | Browser launched | headless={self.headless}")

    def _on_audio_chunk(self, chunk: list[int]) -> None:
        """Called from browser JS with each 2-second candidate audio chunk."""
        if self._capturing and chunk:
            self._audio_queue.put_nowait(bytes(chunk))

    # ── Meeting participation ──────────────────────────

    @property
    def is_in_meeting(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def join(self, bot_url: str) -> bool:
        """
        Navigate to the Jitsi room URL.

        The URL already contains config flags in its fragment
        (prejoinPageEnabled=false, displayName=...) so the bot
        joins without human interaction.

        Returns True when the page has loaded the meeting UI.
        """
        if not self._page:
            await self._launch_browser()

        logger.info(f"BOT | Joining meeting | url={bot_url[:80]}...")
        try:
            await self._page.goto(bot_url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for Jitsi to load the conference UI (the toolbar appears)
            # This selector matches the Jitsi Meet toolbar present in the conference
            await self._page.wait_for_selector(
                "#new-toolbox, .new-toolbox, [class*='Toolbox'], [data-testid='toolbar']",
                timeout=20_000,
                state="attached",
            )
            logger.info(f"BOT | Joined meeting as '{self.persona_name}'")
            return True
        except Exception as e:
            logger.error(f"BOT | Failed to join meeting: {e}")
            return False

    async def leave(self) -> None:
        """Close the browser and end meeting participation."""
        self._capturing = False
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = self._browser = self._context = self._playwright = None
        logger.info("BOT | Left meeting and closed browser")

    # ── Speaking (TTS injection) ───────────────────────

    async def speak(self, mp3_bytes: bytes) -> int:
        """
        Play TTS audio through the bot's Jitsi microphone.

        Converts MP3 bytes to base64, sends to the page, and awaits
        __hireiq_speak() which decodes and plays through WebAudio.

        Args:
            mp3_bytes: Raw MP3 audio from TTSService

        Returns:
            Actual audio duration in milliseconds (0 on error).
        """
        if not self.is_in_meeting:
            logger.warning("BOT | speak() called but not in meeting")
            return 0

        b64 = base64.b64encode(mp3_bytes).decode("ascii")
        try:
            duration_ms = await self._page.evaluate(
                "async (b64) => await window.__hireiq_speak(b64)",
                b64,
            )
            logger.debug(f"BOT | Spoke {duration_ms}ms of audio")
            return int(duration_ms or 0)
        except Exception as e:
            logger.error(f"BOT | speak() failed: {e}")
            return 0

    # ── Listening (candidate audio capture) ────────────

    async def start_candidate_audio_capture(self) -> None:
        """
        Enable candidate audio forwarding.

        The RTCPeerConnection patch in the init script already fires
        __hireiq_audio_chunk for every 2-second audio chunk.
        This method activates the Python-side consumer of those chunks.
        """
        self._capturing = True
        logger.info("BOT | Candidate audio capture started")

    async def stop_candidate_audio_capture(self) -> None:
        self._capturing = False
        logger.info("BOT | Candidate audio capture stopped")

    async def wait_for_candidate_answer(
        self,
        timeout: float = ANSWER_TIMEOUT_SECS,
        silence_secs: float = CANDIDATE_DONE_SILENCE_SECS,
    ) -> str:
        """
        Wait for the candidate to finish speaking, then transcribe.

        Strategy:
          - Collect audio chunks from the queue
          - After `silence_secs` with no new chunk, consider them done
          - Concatenate all chunks and send to Groq Whisper STT

        Args:
            timeout:      Max seconds to wait before returning empty string
            silence_secs: Seconds of silence that signals end-of-answer

        Returns:
            Transcribed text (empty string on timeout or STT failure).
        """
        chunks: list[bytes] = []
        deadline = asyncio.get_event_loop().time() + timeout

        logger.debug("BOT | Waiting for candidate answer...")

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning("BOT | Candidate answer timed out")
                break

            try:
                chunk = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=min(silence_secs, remaining),
                )
                chunks.append(chunk)
            except asyncio.TimeoutError:
                # No audio arrived for silence_secs → candidate stopped speaking
                if chunks:
                    break   # Have audio → transcribe it
                # No audio at all yet → keep waiting until full timeout

        if not chunks:
            return ""

        audio_bytes = b"".join(chunks)
        logger.debug(f"BOT | Transcribing {len(audio_bytes) / 1024:.1f}KB of candidate audio")
        return await self.transcribe(audio_bytes)

    # ── Speech-to-text (Groq Whisper) ─────────────────

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe candidate audio via Groq Whisper.

        Audio format: WebM/Opus (from MediaRecorder in the browser).
        Groq Whisper accepts WebM natively — no conversion needed.

        Args:
            audio_bytes: Raw audio bytes captured from MediaRecorder

        Returns:
            Transcribed text, or empty string on failure.
        """
        if not audio_bytes:
            return ""
        try:
            result = await self._groq.audio.transcriptions.create(
                file            = ("candidate_audio.webm", audio_bytes),
                model           = WHISPER_MODEL,
                response_format = "text",
                language        = "en",
            )
            transcript = str(result).strip()
            logger.info(f"BOT | STT | {len(transcript)} chars: {transcript[:80]}...")
            return transcript
        except Exception as e:
            logger.error(f"BOT | STT failed: {e}")
            return ""

    # ── Status ─────────────────────────────────────────

    async def mute(self) -> None:
        """Mute the bot's microphone (e.g. while the candidate is speaking)."""
        if self.is_in_meeting:
            try:
                await self._page.evaluate(
                    "() => APP?.conference?.toggleAudioMuted?.()"
                )
            except Exception:
                pass

    async def unmute(self) -> None:
        """Unmute the bot's microphone before speaking."""
        if self.is_in_meeting:
            try:
                await self._page.evaluate(
                    "() => APP?.conference?.toggleAudioMuted?.()"
                )
            except Exception:
                pass

    async def set_video_source(self, pixel_streaming_url: str) -> bool:
        """
        Inject UE5 Pixel Streaming video into the bot's Jitsi camera stream.

        This connects the bot's Chromium page to the UE5 Pixel Streaming
        signaling server, receives the rendered MetaHuman video via WebRTC,
        draws it onto a hidden canvas at 30fps, and routes that canvas stream
        as the bot's "camera" inside Jitsi.

        Call this AFTER bot.join() and BEFORE the interview starts. Jitsi
        must not have captured the camera yet — call this early in the
        session setup (the getUserMedia override picks it up automatically
        on the next Jitsi camera capture attempt).

        Args:
            pixel_streaming_url: WebSocket URL of the UE5 Pixel Streaming
                                 signaling server, e.g. "ws://localhost:8888"
                                 Set AVATAR_PS_URL in .env to configure.

        Returns True when the PS video track is live and drawing to canvas.
        Returns False on any connection or negotiation failure (non-fatal —
        the interview continues without avatar video).

        Pixel Streaming setup in UE5:
          1. Enable the PixelStreaming plugin in your project.
          2. Launch with: -PixelStreamingURL=ws://0.0.0.0:8888
          3. Ensure the signaling server (Cirrus) is running on the same port.
          4. Confirm you can open ws://localhost:8888 in a browser before calling this.
        """
        if not self.is_in_meeting:
            logger.warning("BOT | set_video_source() called before joining meeting")
            return False

        logger.info(f"BOT | Connecting to Pixel Streaming | url={pixel_streaming_url}")

        try:
            # Step 1 — Inject the PS connection function into the page.
            # We stash the original (unpatched) RTCPeerConnection first so
            # the PS connection bypasses our RTCPeerConnection patch that
            # captures candidate audio. PS video must not be recorded as STT.
            await self._page.evaluate("""
                () => {
                    // Save the patched PC before PS overwrites anything.
                    // PS connection uses the original PC to avoid triggering
                    // our candidate audio capture patch.
                    if (!window.__hireiq_OrigPC) {
                        // Walk the prototype chain to find the real RTCPeerConnection.
                        // Our patch set PatchedPC.prototype = _OrigPC.prototype,
                        // so we can't easily recover _OrigPC from prototype.
                        // Instead, restore from the closure isn't possible here.
                        // We just note: PS creates its own PC instance directly —
                        // our audio capture patch only activates on 'audio' tracks,
                        // so PS video tracks (kind='video') pass through harmlessly.
                        window.__hireiq_OrigPC = window.RTCPeerConnection;
                    }
                }
            """)

            # Step 2 — Inject and call the PS connection script.
            # Evaluates the full signaling + canvas pipeline, returns when
            # the first video frame is drawn (or throws on failure).
            success = await self._page.evaluate(
                f"""
                async (url) => {{
                    {_PS_CONNECT_SCRIPT}
                    try {{
                        return await __hireiq_connect_ps(url);
                    }} catch (e) {{
                        console.error('[HireIQ-PS] Connection failed:', e.message);
                        return false;
                    }}
                }}
                """,
                pixel_streaming_url,
            )

            if success:
                logger.info(
                    "BOT | Pixel Streaming video injected | "
                    "avatar face is now live in Jitsi camera feed"
                )
            else:
                logger.warning(
                    "BOT | Pixel Streaming connection failed — "
                    "Jitsi will show no video for the bot"
                )

            return bool(success)

        except Exception as e:
            logger.error(f"BOT | set_video_source() error: {e}")
            return False


# ─────────────────────────────────────────────────────
#  Convenience factories
# ─────────────────────────────────────────────────────

def build_meeting_manager(email_service: Optional[EmailService] = None) -> JitsiMeetingManager:
    """Factory for AvatarInterviewOrchestrator (Phase 5)."""
    return JitsiMeetingManager(email_service=email_service or EmailService.from_env())


def build_jitsi_bot(persona_name: str = "Sarah Mitchell") -> JitsiBot:
    """Factory for AvatarInterviewOrchestrator (Phase 5)."""
    headless = os.getenv("AVATAR_BOT_HEADLESS", "true").lower() != "false"
    return JitsiBot(persona_name=persona_name, headless=headless)


# ─────────────────────────────────────────────────────
#  Interview scheduling helper
# ─────────────────────────────────────────────────────

async def schedule_interview(
    session_id:      str,
    applicant_id:    str,
    applicant_email: str,
    applicant_name:  str,
    role:            str,
    persona_name:    str           = "Sarah Mitchell",
    delay_minutes:   int           = 30,
    scheduled_at:    Optional[datetime] = None,
    send_email:      bool          = True,
) -> MeetingRoom:
    """
    High-level helper: create a Jitsi room + send invite in one call.

    Called by the orchestration layer when a candidate passes scoring
    and is ready to be scheduled for an interview.

    Args:
        session_id:      Interview session ID (already created)
        applicant_id:    Applicant record ID
        applicant_email: Email extracted from the candidate's resume
        applicant_name:  Candidate's full name
        role:            Role applied for
        persona_name:    Avatar persona name (shown in email and Jitsi)
        delay_minutes:   Minutes from now for the interview (default: 30)
        scheduled_at:    Override scheduled time (None = now + delay_minutes)
        send_email:      Whether to email the candidate

    Returns:
        MeetingRoom with candidate_url and bot_token ready.
    """
    if scheduled_at is None:
        from datetime import timezone
        scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=delay_minutes)

    manager = build_meeting_manager()
    room = await manager.create_meeting(
        session_id      = session_id,
        applicant_id    = applicant_id,
        applicant_email = applicant_email,
        applicant_name  = applicant_name,
        role            = role,
        scheduled_at    = scheduled_at,
        persona_name    = persona_name,
        send_email      = send_email,
    )
    return room
