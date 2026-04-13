"""
connectors/avatar_bridge.py
═══════════════════════════════════════════════════════
WebSocket control bridge from Python to Unreal Engine MetaHuman.

What this does:
  Sends animation control messages to a running UE5 instance over
  WebSocket so the MetaHuman avatar lip-syncs to TTS audio and
  changes facial expressions during the interview.

What this does NOT do:
  Video streaming. Unreal Engine's Pixel Streaming plugin handles
  broadcasting the rendered avatar video as a WebRTC stream.
  Phase 4 (meeting_bot.py) captures that stream and injects it
  into the Daily.co video call.

Architecture:

  Python (this file)                 Unreal Engine 5
  ─────────────────                  ──────────────────────────────
  AvatarBridge ──WebSocket──────►  Blueprint: WebSocket Server
  send_viseme_packet()               receives VISEME_PACKET
  trigger_speech()                   starts lip-sync animation
  set_emotion()                      blends facial expression
  set_listen_pose()                  plays idle listening anim
                                     │
                                     ▼
                                   Pixel Streaming Plugin
                                     │ WebRTC H.264 stream
                                     ▼
                              meeting_bot.py (Phase 4)
                              injects as bot's video track
                              into Daily.co call

Unreal Engine Blueprint setup (what you need to implement in UE5):
  1. Enable plugins: WebSockets, PixelStreaming, MetaHuman
  2. Create a WebSocket server on ws://0.0.0.0:8765
  3. On message receive: parse JSON, call the appropriate handler:
       VISEME_PACKET    → store frames[], set turn_index
       TRIGGER_SPEECH   → begin frame playback with timestamps
       EMOTION_STATE    → blend to target emotion on background layer
       LISTEN_POSE      → play "attentive listener" anim montage
       IDLE             → play idle anim (breathing, micro-saccades)
       RESET            → snap to neutral, clear queued frames
  4. Frame playback: for each VisemeFrame, at time_ms from audio start,
     call SetMorphTarget(viseme_id, weight) on the MetaHuman mesh.
  5. Pixel Streaming must be running — the bot captures the WebRTC feed.

Message protocol — all JSON, Python → UE5:

  VISEME_PACKET:
    { "type": "VISEME_PACKET", "session_id": "...", "turn_index": 0,
      "audio_duration_ms": 3200, "emotion": "engaged",
      "frames": [{"time_ms": 0, "viseme_id": "viseme_sil", "weight": 0.0}, ...] }

  TRIGGER_SPEECH:
    { "type": "TRIGGER_SPEECH", "turn_index": 0 }

  END_SPEECH:
    { "type": "END_SPEECH", "turn_index": 0 }

  EMOTION_STATE:
    { "type": "EMOTION_STATE", "emotion": "neutral"|"engaged"|"thinking"|"nodding" }

  LISTEN_POSE:
    { "type": "LISTEN_POSE" }

  IDLE:
    { "type": "IDLE" }

  RESET:
    { "type": "RESET" }

  PING:
    { "type": "PING", "ts": 1713000000000 }

Dev mode:
  Set AVATAR_BRIDGE_DEV=true in .env to skip WebSocket entirely.
  All messages are logged instead of sent — lets you develop the
  Python pipeline without UE5 running. Interview audio still works.

Usage:
  bridge = AvatarBridge.from_env()   # reads AVATAR_WS_URL from .env
  await bridge.connect()

  # Before speaking each turn:
  await bridge.send_viseme_packet(tts_response.lip_sync_packet, "engaged")
  await bridge.trigger_speech(turn_index=0)
  # [audio is played by meeting_bot]
  await bridge.end_speech(turn_index=0)
  await bridge.set_listen_pose()

  await bridge.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from enum import Enum
from typing import Optional

import aiohttp

from models.avatar_session import AvatarEmotionState, LipSyncPacket
from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────

WS_URL_DEFAULT          = "ws://localhost:8765/avatar-control"
RECONNECT_MAX_ATTEMPTS  = 5
RECONNECT_BASE_DELAY    = 1.0       # seconds — doubles on each retry
PING_INTERVAL_SECONDS   = 15        # keepalive ping cadence
WS_SEND_TIMEOUT         = 5.0       # seconds before a send is considered failed
WS_CONNECT_TIMEOUT      = 10.0      # seconds to establish WebSocket connection


# ─────────────────────────────────────────────────────
#  Message type enum
# ─────────────────────────────────────────────────────

class BridgeMessageType(str, Enum):
    """All message types understood by the UE5 Blueprint receiver."""
    VISEME_PACKET   = "VISEME_PACKET"   # pre-load lip sync frames for next speech
    TRIGGER_SPEECH  = "TRIGGER_SPEECH"  # start animation (sync with audio playback)
    END_SPEECH      = "END_SPEECH"      # audio done — return to idle
    EMOTION_STATE   = "EMOTION_STATE"   # set background facial expression
    LISTEN_POSE     = "LISTEN_POSE"     # "Sarah is listening" posture + expression
    IDLE            = "IDLE"            # breathing, micro-saccades, rest state
    RESET           = "RESET"           # snap to neutral, clear queued frames
    PING            = "PING"
    PONG            = "PONG"


# ─────────────────────────────────────────────────────
#  Bridge connection state
# ─────────────────────────────────────────────────────

class BridgeState(str, Enum):
    DISCONNECTED    = "disconnected"
    CONNECTING      = "connecting"
    CONNECTED       = "connected"
    RECONNECTING    = "reconnecting"
    CLOSED          = "closed"          # terminal — create a new instance to reconnect


# ─────────────────────────────────────────────────────
#  Avatar Bridge
# ─────────────────────────────────────────────────────

class AvatarBridge:
    """
    WebSocket control bridge from the interview pipeline to UE5 MetaHuman.

    Non-fatal by design: if the bridge is disconnected or UE5 is not
    running, all send operations log a warning and return False instead
    of raising. The interview continues — candidates still receive TTS audio;
    only the avatar's face is not animating.

    Concurrency:
        A single asyncio.Lock serializes all WebSocket sends. This prevents
        interleaved JSON frames if multiple tasks call the bridge concurrently.

    Context manager support:
        async with AvatarBridge.from_env() as bridge:
            await bridge.send_viseme_packet(lip_sync, "engaged")
            await bridge.trigger_speech(turn_index=0)
    """

    def __init__(
        self,
        ws_url:   str  = WS_URL_DEFAULT,
        dev_mode: bool = False,
    ) -> None:
        """
        Args:
            ws_url:   WebSocket URL of the UE5 control server.
                      Must match the URL the Blueprint's WebSocket plugin
                      is listening on. Default: ws://localhost:8765/avatar-control
            dev_mode: When True, all sends are logged and no WebSocket
                      connection is made. Safe for running without UE5.
        """
        self.ws_url   = ws_url
        self.dev_mode = dev_mode

        self._ws:               Optional[aiohttp.ClientWebSocketResponse] = None
        self._session:          Optional[aiohttp.ClientSession]           = None
        self._state:            BridgeState = BridgeState.DISCONNECTED
        self._send_lock:        asyncio.Lock = asyncio.Lock()
        self._keepalive_task:   Optional[asyncio.Task] = None
        self._reconnect_count:  int = 0
        self._messages_sent:    int = 0
        self._last_pong_ts:     float = 0.0

    @classmethod
    def from_env(cls) -> "AvatarBridge":
        """
        Build from environment variables.

        AVATAR_WS_URL      — WebSocket URL (default: ws://localhost:8765/avatar-control)
        AVATAR_BRIDGE_DEV  — "true" to enable dev mode (default: false)
        """
        ws_url   = os.getenv("AVATAR_WS_URL", WS_URL_DEFAULT)
        dev_mode = os.getenv("AVATAR_BRIDGE_DEV", "false").lower() == "true"
        return cls(ws_url=ws_url, dev_mode=dev_mode)

    # ── Context manager ────────────────────────────────

    async def __aenter__(self) -> "AvatarBridge":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    # ── Connection lifecycle ───────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._state == BridgeState.CONNECTED and self._ws is not None

    async def connect(self) -> bool:
        """
        Establish the WebSocket connection to UE5.

        Returns True on success, False on failure (dev_mode always returns True).
        Does nothing if already connected.
        """
        if self.dev_mode:
            logger.info("BRIDGE | Dev mode — WebSocket connection skipped")
            self._state = BridgeState.CONNECTED
            return True

        if self.is_connected:
            return True

        self._state = BridgeState.CONNECTING
        logger.info(f"BRIDGE | Connecting to {self.ws_url}")

        try:
            timeout = aiohttp.ClientTimeout(total=WS_CONNECT_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._ws = await self._session.ws_connect(
                self.ws_url,
                heartbeat=PING_INTERVAL_SECONDS,
            )
            self._state = BridgeState.CONNECTED
            self._reconnect_count = 0
            logger.info("BRIDGE | Connected to UE5 avatar control server")

            # Start keepalive loop in the background
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name="avatar_bridge_keepalive"
            )
            return True

        except Exception as e:
            self._state = BridgeState.DISCONNECTED
            logger.warning(f"BRIDGE | Connection failed: {e} — avatar will not animate")
            await self._cleanup_session()
            return False

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection and stop the keepalive task."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        await self._cleanup_session()
        self._state = BridgeState.CLOSED
        logger.info(f"BRIDGE | Disconnected | messages_sent={self._messages_sent}")

    async def _cleanup_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws      = None
        self._session = None

    # ── High-level animation control ──────────────────

    async def send_viseme_packet(
        self,
        lip_sync:      LipSyncPacket,
        emotion_state: AvatarEmotionState = AvatarEmotionState.ENGAGED,
    ) -> bool:
        """
        Pre-load lip sync frames for the next speech turn into UE5.

        Call this BEFORE triggering audio playback so UE5 has the full
        animation timeline ready to execute on TRIGGER_SPEECH.

        Args:
            lip_sync:      LipSyncPacket from TTSService (Phase 2)
            emotion_state: Background facial expression during speech

        Returns True if sent successfully.
        """
        payload = {
            "session_id":        lip_sync.session_id,
            "turn_index":        lip_sync.turn_index,
            "audio_duration_ms": lip_sync.audio_duration_ms,
            "emotion":           emotion_state.value,
            "frames": [
                {
                    "time_ms":   frame.time_ms,
                    "viseme_id": frame.viseme_id,
                    "weight":    frame.weight,
                }
                for frame in lip_sync.frames
            ],
        }
        result = await self._send(BridgeMessageType.VISEME_PACKET, payload)
        if result:
            logger.debug(
                f"BRIDGE | Viseme packet sent | "
                f"turn={lip_sync.turn_index} | "
                f"frames={len(lip_sync.frames)} | "
                f"duration={lip_sync.audio_duration_ms}ms | "
                f"emotion={emotion_state.value}"
            )
        return result

    async def trigger_speech(self, turn_index: int) -> bool:
        """
        Signal UE5 to start the pre-loaded lip sync animation NOW.

        Call this at the same instant you begin audio playback in Daily.co
        (Phase 4). UE5 will play viseme frames according to their time_ms
        offsets, keeping avatar lips in sync with the audio.

        Args:
            turn_index: Must match the turn_index from the preceding
                        send_viseme_packet() call.
        """
        return await self._send(
            BridgeMessageType.TRIGGER_SPEECH,
            {"turn_index": turn_index},
        )

    async def end_speech(self, turn_index: int) -> bool:
        """
        Signal UE5 that audio playback has finished for this turn.
        UE5 stops the lip sync animation and blends back to idle.
        """
        return await self._send(
            BridgeMessageType.END_SPEECH,
            {"turn_index": turn_index},
        )

    async def set_emotion(self, emotion: AvatarEmotionState) -> bool:
        """
        Set the avatar's background facial expression.

        UE5 blends to this expression on the face's emotion layer
        (separate from the lip sync layer). Call between turns to
        communicate Sarah's reaction to the candidate's answer.

        neutral  → professional resting face
        engaged  → slight smile, eyes bright — for positive answers
        thinking → slight head tilt, contemplative — before a hard question
        nodding  → active listening agreement animation
        """
        return await self._send(
            BridgeMessageType.EMOTION_STATE,
            {"emotion": emotion.value},
        )

    async def set_listen_pose(self) -> bool:
        """
        Put the avatar in "active listening" posture.

        Call after end_speech() while waiting for the candidate's response.
        UE5 plays an attentive pose: slight forward lean, engaged expression,
        natural eye contact behaviour.
        """
        return await self._send(BridgeMessageType.LISTEN_POSE, {})

    async def set_idle(self) -> bool:
        """
        Return avatar to idle state.

        UE5 plays the idle animation: breathing, micro-saccades, blinks.
        Call during silence periods (e.g. waiting for session to start).
        """
        return await self._send(BridgeMessageType.IDLE, {})

    async def reset(self) -> bool:
        """
        Snap avatar to neutral and clear any queued animation frames in UE5.
        Use on session start and after any error recovery.
        """
        return await self._send(BridgeMessageType.RESET, {})

    # ── Low-level send ─────────────────────────────────

    async def _send(
        self,
        message_type: BridgeMessageType,
        payload: dict,
    ) -> bool:
        """
        Serialize and send one JSON message to UE5.

        Thread-safe via asyncio.Lock. Non-fatal: returns False instead
        of raising on any error. Attempts one reconnect if disconnected.

        In dev_mode: logs the message and returns True without sending.
        """
        message = {"type": message_type.value, **payload}

        if self.dev_mode:
            logger.debug(f"BRIDGE [DEV] | {json.dumps(message, separators=(',', ':'))[:200]}")
            return True

        if not self.is_connected:
            logger.warning(
                f"BRIDGE | Not connected — attempting reconnect before send | "
                f"type={message_type.value}"
            )
            reconnected = await self._attempt_reconnect()
            if not reconnected:
                logger.warning(f"BRIDGE | Send dropped (no connection) | type={message_type.value}")
                return False

        async with self._send_lock:
            try:
                json_str = json.dumps(message, separators=(",", ":"))
                await asyncio.wait_for(
                    self._ws.send_str(json_str),
                    timeout=WS_SEND_TIMEOUT,
                )
                self._messages_sent += 1
                return True
            except asyncio.TimeoutError:
                logger.warning(f"BRIDGE | Send timeout | type={message_type.value}")
                self._state = BridgeState.DISCONNECTED
                return False
            except Exception as e:
                logger.warning(f"BRIDGE | Send failed | type={message_type.value} | {e}")
                self._state = BridgeState.DISCONNECTED
                return False

    # ── Reconnection ───────────────────────────────────

    async def _attempt_reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.
        Called automatically when a send fails on a disconnected bridge.
        Returns True if reconnection succeeded.
        """
        if self._reconnect_count >= RECONNECT_MAX_ATTEMPTS:
            logger.error(
                f"BRIDGE | Max reconnect attempts ({RECONNECT_MAX_ATTEMPTS}) reached — "
                f"avatar will not animate for the remainder of this session"
            )
            self._state = BridgeState.CLOSED
            return False

        self._state = BridgeState.RECONNECTING
        delay = RECONNECT_BASE_DELAY * (2 ** self._reconnect_count)
        self._reconnect_count += 1

        logger.info(
            f"BRIDGE | Reconnect attempt {self._reconnect_count}/{RECONNECT_MAX_ATTEMPTS} "
            f"in {delay:.1f}s"
        )
        await asyncio.sleep(delay)
        await self._cleanup_session()
        return await self.connect()

    # ── Keepalive ──────────────────────────────────────

    async def _keepalive_loop(self) -> None:
        """
        Send periodic PING messages to keep the WebSocket alive.
        Runs as a background asyncio task. Exits cleanly on cancellation.

        aiohttp's heartbeat parameter handles TCP keepalive automatically,
        but we also send application-level PINGs so UE5's Blueprint can
        confirm liveness and log the connection health.
        """
        while self.is_connected:
            try:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                if not self.is_connected:
                    break
                ts_ms = int(time.time() * 1000)
                await self._send(BridgeMessageType.PING, {"ts": ts_ms})
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"BRIDGE | Keepalive error: {e}")
                break


# ─────────────────────────────────────────────────────
#  Speech turn coordinator
# ─────────────────────────────────────────────────────

class SpeechTurnCoordinator:
    """
    Coordinates a single avatar speech turn end-to-end.

    Wraps the three-step sequence:
      1. send_viseme_packet()  — pre-load animation into UE5
      2. trigger_speech()      — start animation (sync with audio)
      3. end_speech()          — animation done, return to idle

    Used by AvatarInterviewOrchestrator (Phase 5) to keep
    Phase 4 (audio playback) and Phase 3 (animation) in sync.

    Usage:
        coordinator = SpeechTurnCoordinator(bridge)
        async with coordinator.speech_turn(lip_sync, emotion, turn_index):
            await meeting_bot.play_audio(tts_response.audio_bytes)
        # end_speech() + set_listen_pose() called automatically on exit
    """

    def __init__(self, bridge: AvatarBridge) -> None:
        self.bridge = bridge

    async def prepare(
        self,
        lip_sync:      LipSyncPacket,
        emotion_state: AvatarEmotionState = AvatarEmotionState.ENGAGED,
    ) -> bool:
        """Pre-load viseme frames. Call before starting audio playback."""
        return await self.bridge.send_viseme_packet(lip_sync, emotion_state)

    async def start(self, turn_index: int) -> bool:
        """Start avatar animation. Call at the same instant audio playback begins."""
        return await self.bridge.trigger_speech(turn_index)

    async def finish(self, turn_index: int) -> None:
        """Call when audio playback ends. Transitions avatar to listen pose."""
        await self.bridge.end_speech(turn_index)
        await self.bridge.set_listen_pose()

    async def speak(
        self,
        lip_sync:      LipSyncPacket,
        emotion_state: AvatarEmotionState,
        audio_play_coro,
    ) -> None:
        """
        Execute a complete speech turn: prepare → start → play audio → finish.

        Args:
            lip_sync:       LipSyncPacket from TTSService
            emotion_state:  Avatar expression during speech
            audio_play_coro: Coroutine that plays audio (from Phase 4 meeting_bot).
                             Animation starts when this coroutine starts,
                             ends when it returns.

        Example:
            await coordinator.speak(
                lip_sync      = tts_response.lip_sync_packet,
                emotion_state = AvatarEmotionState.ENGAGED,
                audio_play_coro = meeting_bot.play_audio(tts_response.audio_bytes),
            )
        """
        turn_index = lip_sync.turn_index

        # Pre-load frames into UE5 before audio starts
        await self.prepare(lip_sync, emotion_state)

        # Start animation + audio simultaneously
        await asyncio.gather(
            self.start(turn_index),
            audio_play_coro,
        )

        # Audio finished → transition avatar to listen pose
        await self.finish(turn_index)
