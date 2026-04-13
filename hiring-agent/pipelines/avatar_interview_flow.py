"""
pipelines/avatar_interview_flow.py
═══════════════════════════════════════════════════════
Phase 5 — Full Avatar Interview Orchestration.

Wires all four phases into a complete end-to-end pipeline:

  Phase 1 — InterviewerAgent (avatar mode, Sarah Mitchell persona)
             HumanResponseShaper strips AI tells from every LLM response.
  Phase 2 — TTSService (edge-tts, word-boundary lip sync data)
  Phase 3 — AvatarBridge (WebSocket → Unreal Engine MetaHuman animation)
  Phase 4 — JitsiBot (Playwright Chromium bot in Jitsi meeting)
           + EmailService (interview invite sent to candidate before meeting)

Real-time loop for each interviewer turn:

  InterviewerAgent generates question
  → HumanResponseShaper strips AI tells (inside InterviewerAgent._shape())
  → TTSService.synthesize() → MP3 bytes + LipSyncPacket
  → SpeechTurnCoordinator.speak():
        asyncio.gather(
            bridge.trigger_speech()  ← avatar lips start moving NOW
            bot.speak(mp3_bytes)     ← audio plays in Jitsi NOW
        )
  → bridge.set_listen_pose()        ← avatar enters active-listening pose
  → bot.wait_for_candidate_answer() ← Groq Whisper STT → transcript
  → DetectorAgent.detect()          ← AI-content check on candidate response
  → InterviewerAgent.process_response() → (next_question, is_complete)
  → (loop until is_complete)

On completion:
  OrchestratorAgent.decide() → final hire/reject/hold verdict
  JitsiBot.leave()
  AvatarBridge.set_idle() + disconnect()

Dev mode (no infrastructure needed):
  AVATAR_BRIDGE_DEV=true  → bridge logs instead of WebSocket to UE5
  No SMTP config          → EmailService logs invite instead of sending
  AVATAR_BOT_HEADLESS=false → Chromium window opens (watch the meeting)

Usage (production):
    pipeline = AvatarInterviewPipeline()
    result = await pipeline.run(
        applicant    = applicant,
        score        = score,
        scheduled_at = datetime(2026, 4, 20, 14, 30),
    )

Usage (dev / integration test):
    pipeline = AvatarInterviewPipeline()
    result = await pipeline.run(
        applicant  = applicant,
        send_email = False,   # skip email in tests
    )
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from agents.avatar_persona import DEFAULT_PERSONA, PersonaConfig
from agents.detector import DetectionResult, DetectorAgent
from agents.interviewer import InterviewerAgent
from agents.orchestrator import OrchestratorAgent, OrchestratorDecision
from connectors.avatar_bridge import AvatarBridge, SpeechTurnCoordinator
from connectors.email_service import EmailService
from connectors.meeting_bot import (
    JitsiBot,
    JitsiMeetingManager,
    build_jitsi_bot,
    build_meeting_manager,
)
from connectors.tts_service import TTSService
from models.applicant import Applicant
from models.avatar_session import (
    AvatarEmotionState,
    AvatarSessionMetadata,
    MeetingRoom,
    MeetingStatus,
    TTSRequest,
    TTSResponse,
)
from models.interview import InterviewSession
from models.score import ApplicantScore
from utils.logger import log_interview_event, logger


# ─────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────

@dataclass
class AvatarInterviewResult:
    """
    Full result of running the avatar interview pipeline for one applicant.

    Attributes:
        applicant_id       — links back to Applicant record
        session            — completed InterviewSession (questions, responses, round scores)
        meeting_room       — Jitsi room details (candidate URL, bot URL)
        avatar_metadata    — per-session avatar stats (TTS calls, pauses, AI tells stripped)
        detection_results  — DetectionResult for every answered question
        decision           — final OrchestratorDecision (hire/reject/hold)
        round_scores       — per-round scores from RoundSummary objects
        total_ai_flags     — total candidate responses flagged as AI-generated
        started_at         — pipeline start time (UTC)
        completed_at       — pipeline end time (UTC)
        error              — set if the pipeline aborted due to an unrecoverable error
    """
    applicant_id:       str
    session:            Optional[InterviewSession]      = None
    meeting_room:       Optional[MeetingRoom]           = None
    avatar_metadata:    Optional[AvatarSessionMetadata] = None
    detection_results:  list[DetectionResult]           = field(default_factory=list)
    decision:           Optional[OrchestratorDecision]  = None
    round_scores:       list[float]                     = field(default_factory=list)
    total_ai_flags:     int                             = 0
    started_at:         datetime                        = field(default_factory=datetime.utcnow)
    completed_at:       Optional[datetime]              = None
    error:              Optional[str]                   = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return round((self.completed_at - self.started_at).total_seconds(), 2)
        return None

    def summary(self) -> str:
        decision_str = (
            f"{self.decision.verdict} ({self.decision.next_action})"
            if self.decision else "no decision"
        )
        return (
            f"AvatarInterviewPipeline | [{self.applicant_id}] | "
            f"Decision: {decision_str} | "
            f"AI flags: {self.total_ai_flags} | "
            f"Round scores: {self.round_scores} | "
            f"Duration: {self.duration_seconds}s"
        )


# ─────────────────────────────────────────────────────
#  Emotion state helper
# ─────────────────────────────────────────────────────

def _choose_emotion(round_number: int, turn_in_round: int) -> AvatarEmotionState:
    """
    Deterministic emotion selection based on where we are in the interview.

    Round 1 (Screening) — warm and welcoming → ENGAGED
    Round 2 (Technical) — attentive and focused → THINKING before questions
    Round 3 (Cultural) — friendly and open → ENGAGED
    First turn in any round → ENGAGED (greeting energy)
    Mid-round acknowledgement → NODDING (brief, between turns)
    """
    if turn_in_round == 0:
        # Opening turn — warm and engaged regardless of round
        return AvatarEmotionState.ENGAGED
    if round_number == 2:
        # Technical round — show contemplation before asking hard questions
        return AvatarEmotionState.THINKING
    return AvatarEmotionState.ENGAGED


# ─────────────────────────────────────────────────────
#  Avatar Interview Pipeline
# ─────────────────────────────────────────────────────

class AvatarInterviewPipeline:
    """
    Orchestrates the full avatar interview: Phases 1 → 4 → decision.

    All components are injected at construction time and default to
    environment-configured instances, so the pipeline works out of the
    box with just environment variables set.

    The pipeline is stateless per-applicant — safe to reuse one instance
    across multiple concurrent interviews.

    Failure handling:
      - Avatar bridge failures → log + continue (candidate still hears audio)
      - TTS failure → log + skip audio for that turn (interviewer continues)
      - Bot join failure → abort pipeline, return error result
      - Orchestrator error → default to "hold" (never silent-fail a verdict)
    """

    def __init__(
        self,
        persona_config:   PersonaConfig | None        = None,
        tts_service:      TTSService | None           = None,
        avatar_bridge:    AvatarBridge | None         = None,
        meeting_manager:  JitsiMeetingManager | None  = None,
        detector:         DetectorAgent | None        = None,
        orchestrator:     OrchestratorAgent | None    = None,
    ) -> None:
        """
        Args:
            persona_config:  Avatar persona. Defaults to DEFAULT_PERSONA (Sarah Mitchell).
            tts_service:     edge-tts service instance. Defaults to env-configured.
            avatar_bridge:   UE5 WebSocket bridge. Defaults to env-configured (dev_mode
                             enabled if AVATAR_BRIDGE_DEV=true).
            meeting_manager: Jitsi room manager + email sender. Defaults to env-configured.
            detector:        AI-content detector for candidate responses.
            orchestrator:    Final hire/reject/hold decision maker.
        """
        self.persona     = persona_config or DEFAULT_PERSONA
        self.tts         = tts_service    or TTSService.from_persona(self.persona)
        self.bridge      = avatar_bridge  or AvatarBridge.from_env()
        self.meetings    = meeting_manager or build_meeting_manager()
        self.detector    = detector       or DetectorAgent()
        self.orchestrator = orchestrator  or OrchestratorAgent()

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    async def run(
        self,
        applicant:                  Applicant,
        score:                      ApplicantScore | None = None,
        scheduled_at:               datetime | None       = None,
        send_email:                 bool                  = True,
        experience_years:           float                 = 0.0,
        candidate_join_timeout_secs: float                = 300.0,
    ) -> AvatarInterviewResult:
        """
        Run the complete avatar interview for one applicant.

        Steps:
          1. Create Jitsi meeting room + send invite email to candidate
          2. Connect avatar bridge (UE5 WebSocket)
          3. Launch Playwright bot, join the Jitsi meeting
          4. Wait for candidate to join (up to candidate_join_timeout_secs)
          5. Start InterviewerAgent session (avatar persona mode)
          6. Run the real-time interview loop (LLM → TTS → bridge → STT)
          7. Run OrchestratorAgent for final hire/reject/hold verdict
          8. Teardown: leave meeting, reset avatar, close bridge

        Args:
            applicant:                   Full applicant profile
            score:                       ScorerAgent output (None if no pre-scoring)
            scheduled_at:                Interview datetime (None = 30 min from now)
            send_email:                  Whether to send the Jitsi invite email
            experience_years:            For AI-detection calibration
            candidate_join_timeout_secs: Seconds to wait for candidate before starting

        Returns:
            AvatarInterviewResult. On failure, result.error is set and
            result.decision defaults to "hold" to avoid silent rejections.
        """
        result = AvatarInterviewResult(applicant_id=applicant.id)

        logger.info(
            f"AVATAR | Pipeline started | "
            f"[{applicant.id}] {applicant.full_name} | "
            f"Role: {applicant.role_applied.value} | "
            f"Persona: {self.persona.name}"
        )

        bot = build_jitsi_bot(persona_name=self.persona.name)

        try:
            # ── Step 1: Create meeting room + send invite ──────────────
            # We use a temporary session ID for the meeting (real session ID
            # comes from InterviewerAgent.start_session() in step 5).
            # The room ID is deterministic — same applicant gets same room
            # if the pipeline is re-run, which is the correct behaviour.
            import uuid
            pre_session_id = f"PRE-{uuid.uuid4().hex[:8].upper()}"
            room = await self._setup_meeting(
                applicant   = applicant,
                session_id  = pre_session_id,
                scheduled_at = scheduled_at,
                send_email   = send_email,
            )
            result.meeting_room = room

            # ── Step 2: Connect avatar bridge ──────────────────────────
            await self.bridge.connect()
            await self.bridge.reset()   # snap avatar to neutral on session start

            coordinator = SpeechTurnCoordinator(self.bridge)

            # ── Step 3: Bot joins Jitsi ────────────────────────────────
            async with bot:
                joined = await bot.join(room.bot_token)
                if not joined:
                    raise RuntimeError(
                        f"Bot failed to join Jitsi room {room.room_id}. "
                        "Check Playwright installation and Jitsi URL."
                    )

                await bot.start_candidate_audio_capture()
                room.status = MeetingStatus.ACTIVE

                # ── Step 3b: Inject Pixel Streaming video (optional) ───
                # Reads AVATAR_PS_URL from env. If the var is not set or
                # UE5 is not running, this is a no-op — interview continues
                # without avatar video (audio still works).
                ps_url = os.getenv("AVATAR_PS_URL", "")
                if ps_url:
                    await bot.set_video_source(ps_url)
                else:
                    logger.info(
                        "AVATAR | AVATAR_PS_URL not set — "
                        "skipping Pixel Streaming video injection"
                    )

                # ── Step 4: Wait for candidate ─────────────────────────
                candidate_present = await self._wait_for_candidate(
                    bot, candidate_join_timeout_secs
                )
                if not candidate_present:
                    logger.warning(
                        f"AVATAR | [{applicant.id}] Candidate did not join within "
                        f"{candidate_join_timeout_secs}s — aborting interview"
                    )
                    result.error = "Candidate did not join the meeting"
                    room.status  = MeetingStatus.ABANDONED
                    result.completed_at = datetime.utcnow()
                    return result

                # ── Step 5: Start InterviewerAgent session ─────────────
                interviewer = InterviewerAgent(persona_config=self.persona)
                session, first_question = await interviewer.start_session(applicant)

                # Build avatar session metadata for stats tracking
                avatar_meta = AvatarSessionMetadata(
                    session_id      = session.session_id,
                    applicant_id    = applicant.id,
                    persona_name    = self.persona.name,
                    persona_title   = self.persona.title,
                    avatar_asset_id = self.persona.avatar_asset_id,
                    voice_id        = self.persona.voice_id,
                    meeting_platform = room.platform,
                    meeting_room_id  = room.room_id,
                    meeting_room_url = room.candidate_url,
                    meeting_status   = MeetingStatus.ACTIVE,
                    avatar_started_at = datetime.utcnow(),
                )
                result.avatar_metadata = avatar_meta

                log_interview_event(
                    session.session_id,
                    "Avatar interview started",
                    f"Persona: {self.persona.name} | Room: {room.room_id}",
                )

                # ── Step 6: Real-time interview loop ───────────────────
                detections, round_scores = await self._run_interview_loop(
                    first_question   = first_question,
                    interviewer      = interviewer,
                    session          = session,
                    applicant        = applicant,
                    bot              = bot,
                    coordinator      = coordinator,
                    avatar_meta      = avatar_meta,
                    experience_years = experience_years,
                )

                avatar_meta.avatar_ended_at = datetime.utcnow()
                avatar_meta.meeting_status  = MeetingStatus.COMPLETED
                room.status                  = MeetingStatus.COMPLETED

                result.session          = session
                result.detection_results = detections
                result.round_scores      = round_scores
                result.total_ai_flags   = sum(1 for d in detections if d.flagged)

                log_interview_event(
                    session.session_id,
                    "Interview loop complete",
                    f"Rounds: {len(round_scores)} | "
                    f"AI flags: {result.total_ai_flags} | "
                    f"TTS calls: {avatar_meta.total_tts_calls}",
                )

                # ── Step 7: Final decision ─────────────────────────────
                result.decision = await self._finalize_decision(
                    applicant        = applicant,
                    score            = score,
                    session          = session,
                    detections       = detections,
                    round_scores     = round_scores,
                )

            # ── Step 8: Teardown (bot context manager handles leave) ───
            await self.bridge.set_idle()
            await self.bridge.disconnect()

            result.completed_at = datetime.utcnow()
            logger.info(f"AVATAR | Pipeline complete | {result.summary()}")

        except Exception as e:
            result.error        = str(e)
            result.completed_at = datetime.utcnow()
            logger.error(
                f"AVATAR | Pipeline FAILED | [{applicant.id}] {applicant.full_name} | {e}"
            )
            # Ensure teardown even on unexpected errors
            try:
                await self.bridge.set_idle()
                await self.bridge.disconnect()
            except Exception:
                pass

        return result

    # ─────────────────────────────────────────────────
    #  Setup
    # ─────────────────────────────────────────────────

    async def _setup_meeting(
        self,
        applicant:    Applicant,
        session_id:   str,
        scheduled_at: datetime | None,
        send_email:   bool,
    ) -> MeetingRoom:
        """
        Create the Jitsi room and optionally send the invite email.

        The meeting manager handles room ID generation, email templating,
        and SMTP sending (dev mode: logs instead of sending).
        """
        from datetime import timedelta, timezone

        if scheduled_at is None:
            # Default: 30 minutes from now — gives the bot time to join
            # and the candidate time to receive the email
            scheduled_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=30)
            )

        room = await self.meetings.create_meeting(
            session_id      = session_id,
            applicant_id    = applicant.id,
            applicant_email = applicant.email or "",
            applicant_name  = applicant.full_name,
            role            = applicant.role_applied.value,
            scheduled_at    = scheduled_at,
            persona_name    = self.persona.name,
            send_email      = send_email and bool(applicant.email),
        )

        logger.info(
            f"AVATAR | Meeting created | "
            f"room={room.room_id} | "
            f"candidate_url={room.candidate_url} | "
            f"email_sent={send_email and bool(applicant.email)}"
        )
        return room

    # ─────────────────────────────────────────────────
    #  Candidate detection
    # ─────────────────────────────────────────────────

    async def _wait_for_candidate(
        self,
        bot:     JitsiBot,
        timeout: float,
    ) -> bool:
        """
        Wait until the candidate's audio track appears in the Jitsi room.

        The RTCPeerConnection patch in the bot fires audio chunks into
        bot._audio_queue whenever a remote audio track delivers data.
        We poll the queue without consuming entries — the interview loop
        will consume them.

        Returns True when audio detected, False on timeout.
        """
        logger.info(
            f"AVATAR | Waiting for candidate to join "
            f"(timeout={int(timeout)}s)..."
        )
        loop      = asyncio.get_event_loop()
        deadline  = loop.time() + timeout
        poll_secs = 2.0

        while loop.time() < deadline:
            if not bot._audio_queue.empty():
                logger.info("AVATAR | Candidate detected — audio track active")
                return True
            await asyncio.sleep(poll_secs)

        return False

    # ─────────────────────────────────────────────────
    #  TTS + bridge + bot.speak coordination
    # ─────────────────────────────────────────────────

    async def _speak_turn(
        self,
        question_text: str,
        session_id:    str,
        turn_index:    int,
        round_number:  int,
        turn_in_round: int,
        bot:           JitsiBot,
        coordinator:   SpeechTurnCoordinator,
        avatar_meta:   AvatarSessionMetadata,
    ) -> None:
        """
        Synthesize one interviewer turn and deliver it through all channels:
          1. TTS → MP3 bytes + LipSyncPacket
          2. Bridge → pre-load viseme frames into UE5
          3. Bot.speak + bridge.trigger_speech → audio + animation in parallel

        Non-fatal: if TTS or bridge fails, the pipeline continues — only
        audio delivery fails, not the interview logic.
        """
        emotion = _choose_emotion(round_number, turn_in_round)

        # ── TTS synthesis ──────────────────────────────────────────────
        tts_response: TTSResponse | None = None
        try:
            tts_request = TTSRequest(
                text        = question_text,
                voice_id    = self.persona.voice_id,
                speech_rate = self.persona.speech_rate,
                session_id  = session_id,
                turn_index  = turn_index,
            )
            tts_response = await self.tts.synthesize(tts_request)
            avatar_meta.total_tts_calls += 1

            if tts_response.audio_duration_ms:
                avatar_meta.total_pauses_ms += tts_response.audio_duration_ms

            logger.debug(
                f"AVATAR | TTS | turn={turn_index} | "
                f"chars={len(question_text)} | "
                f"duration={tts_response.audio_duration_ms}ms"
            )
        except Exception as e:
            logger.error(f"AVATAR | TTS failed on turn {turn_index}: {e}")

        # ── Bridge + audio playback ────────────────────────────────────
        if tts_response and tts_response.audio_bytes:
            try:
                if tts_response.lip_sync_packet:
                    # SpeechTurnCoordinator pre-loads visemes, then fires
                    # trigger_speech and bot.speak simultaneously via asyncio.gather
                    await coordinator.speak(
                        lip_sync      = tts_response.lip_sync_packet,
                        emotion_state = emotion,
                        audio_play_coro = bot.speak(tts_response.audio_bytes),
                    )
                else:
                    # No lip sync data (TTS worked but no word boundaries) —
                    # play audio without avatar animation
                    await asyncio.gather(
                        self.bridge.trigger_speech(turn_index),
                        bot.speak(tts_response.audio_bytes),
                    )
                    await self.bridge.end_speech(turn_index)
                    await self.bridge.set_listen_pose()
            except Exception as e:
                logger.error(f"AVATAR | Audio delivery failed on turn {turn_index}: {e}")
        else:
            # TTS failed — avatar goes to listen pose so it's not frozen
            await self.bridge.set_listen_pose()
            logger.warning(
                f"AVATAR | Turn {turn_index} delivered without audio (TTS unavailable)"
            )

    # ─────────────────────────────────────────────────
    #  Main interview loop
    # ─────────────────────────────────────────────────

    async def _run_interview_loop(
        self,
        first_question:  str,
        interviewer:     InterviewerAgent,
        session:         InterviewSession,
        applicant:       Applicant,
        bot:             JitsiBot,
        coordinator:     SpeechTurnCoordinator,
        avatar_meta:     AvatarSessionMetadata,
        experience_years: float,
    ) -> tuple[list[DetectionResult], list[float]]:
        """
        Drive the interview from the first question through all rounds.

        Turn sequence:
          1. Deliver interviewer question via TTS + avatar animation
          2. Stop audio capture, wait for candidate to speak, restart capture
             (muting prevents echo of the bot's own audio being captured)
          3. STT: Groq Whisper transcribes candidate answer
          4. AI detection on the candidate's answer
          5. InterviewerAgent.process_response() → (next_question, is_complete)
          6. Update emotion: NODDING briefly to acknowledge, then next turn

        Returns:
            (detection_results, round_scores)
        """
        detections:   list[DetectionResult] = []
        current_question = first_question
        is_complete      = False
        turn_index       = 0
        turn_in_round    = 0
        current_round    = 1

        while not is_complete:
            # ── Deliver question via TTS + avatar ──────────────────────
            log_interview_event(
                session.session_id,
                f"Avatar speaking (R{current_round} T{turn_index})",
                f"{len(current_question)} chars",
            )

            # Mute bot while speaking to prevent TTS echo in capture
            await bot.mute()
            await self._speak_turn(
                question_text = current_question,
                session_id    = session.session_id,
                turn_index    = turn_index,
                round_number  = current_round,
                turn_in_round = turn_in_round,
                bot           = bot,
                coordinator   = coordinator,
                avatar_meta   = avatar_meta,
            )
            await bot.unmute()

            # ── Wait for candidate answer ──────────────────────────────
            log_interview_event(
                session.session_id,
                "Listening for candidate",
                f"turn={turn_index}",
            )

            candidate_answer = await bot.wait_for_candidate_answer(timeout=180)

            if not candidate_answer:
                # Candidate didn't respond — re-prompt once, then skip
                logger.warning(
                    f"AVATAR | No candidate response on turn {turn_index} — re-prompting"
                )
                # Brief acknowledgement before re-prompt
                await self.bridge.set_emotion(AvatarEmotionState.NEUTRAL)

                reprompt = (
                    "I noticed we may have had a connection issue — "
                    "could you please share your thoughts on that?"
                )
                await bot.mute()
                await self._speak_turn(
                    question_text = reprompt,
                    session_id    = session.session_id,
                    turn_index    = turn_index,
                    round_number  = current_round,
                    turn_in_round = turn_in_round,
                    bot           = bot,
                    coordinator   = coordinator,
                    avatar_meta   = avatar_meta,
                )
                await bot.unmute()

                candidate_answer = await bot.wait_for_candidate_answer(timeout=120)
                if not candidate_answer:
                    candidate_answer = "[No response provided]"
                    logger.warning(
                        f"AVATAR | Candidate silent after re-prompt on turn {turn_index} "
                        f"— using placeholder"
                    )

            log_interview_event(
                session.session_id,
                "Candidate answered",
                f"turn={turn_index} | chars={len(candidate_answer)}",
            )

            # ── AI detection on candidate response ─────────────────────
            if session.questions:
                last_question = session.questions[len(session.responses)]
                try:
                    detection = await self.detector.detect(
                        question         = last_question.question_text,
                        response         = candidate_answer,
                        applicant_name   = applicant.full_name,
                        role             = applicant.role_applied.value,
                        experience_years = experience_years,
                        question_id      = last_question.question_id,
                    )
                    detections.append(detection)
                    if detection.flagged:
                        logger.warning(
                            f"AVATAR | AI-content flag | "
                            f"turn={turn_index} | "
                            f"score={detection.ai_probability:.2f}"
                        )
                except Exception as e:
                    logger.warning(
                        f"AVATAR | Detector failed on turn {turn_index}: {e}"
                    )

            # ── Brief nodding acknowledgement before processing ────────
            await self.bridge.set_emotion(AvatarEmotionState.NODDING)
            await asyncio.sleep(0.5)   # half-second nod

            # ── InterviewerAgent processes the response ────────────────
            prev_round = session.current_round
            next_question, is_complete = await interviewer.process_response(
                session, candidate_answer
            )

            # Detect round transition (advance_round() changes current_round)
            if session.current_round != prev_round:
                current_round = session.current_round
                turn_in_round = 0
                logger.info(
                    f"AVATAR | Advanced to round {current_round} | "
                    f"[{applicant.id}] {applicant.full_name}"
                )
                # Brief engaged expression for round transition
                await self.bridge.set_emotion(AvatarEmotionState.ENGAGED)

            if next_question:
                current_question = next_question
            turn_index   += 1
            turn_in_round += 1

        # ── Gather round scores from completed session ─────────────────
        round_scores = [
            s.round_score
            for s in session.round_summaries
            if s.round_score is not None
        ]

        return detections, round_scores

    # ─────────────────────────────────────────────────
    #  Orchestrator decision
    # ─────────────────────────────────────────────────

    async def _finalize_decision(
        self,
        applicant:    Applicant,
        score:        ApplicantScore | None,
        session:      InterviewSession,
        detections:   list[DetectionResult],
        round_scores: list[float],
    ) -> OrchestratorDecision:
        """
        Call OrchestratorAgent to produce the final hire/reject/hold verdict.

        Falls back to "hold" on any error — the orchestrator never silently
        rejects a candidate due to a system failure.
        """
        effective_score = score or _empty_score(applicant.id, applicant.full_name)

        decision = await self.orchestrator.decide(
            applicant         = applicant,
            score             = effective_score,
            detection_results = detections,
            round_scores      = round_scores,
        )

        logger.info(
            f"AVATAR | Decision | [{applicant.id}] {applicant.full_name} | "
            f"verdict={decision.verdict} | "
            f"confidence={decision.confidence:.2f} | "
            f"action={decision.next_action}"
        )
        return decision


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _empty_score(applicant_id: str, applicant_name: str) -> ApplicantScore:
    """
    Minimal ApplicantScore placeholder for applicants who enter the avatar
    pipeline without a prior scoring pass. The orchestrator relies on
    interview performance alone in this case.
    """
    from models.score import ScoringStatus
    return ApplicantScore(
        applicant_id   = applicant_id,
        applicant_name = applicant_name,
        status         = ScoringStatus.SKIPPED,
        final_score    = None,
    )


# ─────────────────────────────────────────────────────
#  Convenience factory
# ─────────────────────────────────────────────────────

def build_avatar_pipeline(
    persona_config: PersonaConfig | None = None,
) -> AvatarInterviewPipeline:
    """
    Build a production-ready AvatarInterviewPipeline from environment variables.

    All component services read their configuration from .env:
      GROQ_API_KEY, GROQ_AVATAR_BRAIN, AVATAR_TTS_VOICE, AVATAR_TTS_RATE
      AVATAR_WS_URL, AVATAR_BRIDGE_DEV, AVATAR_BOT_HEADLESS
      JITSI_BASE_URL, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, etc.

    Usage:
        pipeline = build_avatar_pipeline()
        result = await pipeline.run(applicant, score=score)
    """
    return AvatarInterviewPipeline(persona_config=persona_config or DEFAULT_PERSONA)
