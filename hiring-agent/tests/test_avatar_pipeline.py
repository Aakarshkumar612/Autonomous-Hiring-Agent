"""
tests/test_avatar_pipeline.py
═══════════════════════════════════════════════════════
Phase 5 — Avatar Interview Pipeline tests.

Tests cover:
  - AvatarInterviewResult dataclass (summary, duration)
  - Emotion selection helper (_choose_emotion)
  - AvatarInterviewPipeline construction
  - _setup_meeting() (Jitsi room creation, no SMTP send)
  - _speak_turn() (mocked TTS + bridge + bot)
  - _run_interview_loop() (mocked interviewer + detections)
  - Full run() end-to-end (everything mocked — no real Groq/Playwright/UE5)
  - build_avatar_pipeline() convenience factory

No real API calls, no network connections, no browser launch.
All external dependencies mocked.

Run with:
    uv run pytest tests/test_avatar_pipeline.py -v
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.avatar_persona import DEFAULT_PERSONA, PersonaConfig
from agents.orchestrator import OrchestratorDecision
from connectors.meeting_bot import generate_candidate_url, generate_room_id
from models.applicant import Applicant, ApplicationStatus, Skill, TechRole
from models.avatar_session import (
    AvatarEmotionState,
    AvatarSessionMetadata,
    LipSyncPacket,
    MeetingPlatform,
    MeetingRoom,
    MeetingStatus,
    TTSResponse,
    TTSStatus,
    VisemeFrame,
)
from models.interview import InterviewSession, SessionStatus
from models.score import ApplicantScore, ScoringStatus
from pipelines.avatar_interview_flow import (
    AvatarInterviewPipeline,
    AvatarInterviewResult,
    _choose_emotion,
    _empty_score,
    build_avatar_pipeline,
)


# ─────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────

@pytest.fixture
def sample_applicant() -> Applicant:
    """A minimal but valid Applicant for testing."""
    return Applicant(
        id                       = "APP-PHASE5-001",
        full_name                = "Priya Sharma",
        email                    = "priya@example.com",
        role_applied             = TechRole.BACKEND,
        status                   = ApplicationStatus.SHORTLISTED,
        skills                   = [
            Skill(name="Python", proficiency=4),
            Skill(name="FastAPI", proficiency=3),
            Skill(name="PostgreSQL", proficiency=3),
        ],
        total_experience_months  = 42,   # 3.5 years
        phone                    = "+91-9000000001",
    )


@pytest.fixture
def sample_score(sample_applicant) -> ApplicantScore:
    return ApplicantScore(
        applicant_id   = sample_applicant.id,
        applicant_name = sample_applicant.full_name,
        status         = ScoringStatus.COMPLETED,
        final_score    = 78.5,
    )


@pytest.fixture
def sample_room() -> MeetingRoom:
    return MeetingRoom(
        room_id       = "HireIQ-TESTROOM0001",
        room_name     = "HireIQ-TESTROOM0001",
        candidate_url = "https://meet.jit.si/HireIQ-TESTROOM0001",
        bot_token     = "https://meet.jit.si/HireIQ-TESTROOM0001#config.prejoinPageEnabled=false",
        platform      = MeetingPlatform.JITSI,
        status        = MeetingStatus.PENDING,
    )


@pytest.fixture
def sample_session(sample_applicant) -> InterviewSession:
    return InterviewSession(
        session_id     = "SESS-PHASE5TST",
        applicant_id   = sample_applicant.id,
        applicant_name = sample_applicant.full_name,
        role_applied   = sample_applicant.role_applied.value,
        status         = SessionStatus.COMPLETED,
        total_rounds   = 3,
    )


@pytest.fixture
def sample_lip_sync() -> LipSyncPacket:
    return LipSyncPacket(
        session_id        = "SESS-PHASE5TST",
        turn_index        = 0,
        audio_duration_ms = 3200,
        frames            = [
            VisemeFrame(time_ms=0,    viseme_id="viseme_sil", weight=0.0),
            VisemeFrame(time_ms=100,  viseme_id="viseme_PP",  weight=0.9),
            VisemeFrame(time_ms=200,  viseme_id="viseme_sil", weight=0.0),
        ],
        emotion_state     = AvatarEmotionState.ENGAGED,
    )


@pytest.fixture
def sample_tts_response(sample_lip_sync) -> TTSResponse:
    return TTSResponse(
        request_id        = "req-test-001",
        session_id        = "SESS-PHASE5TST",
        status            = TTSStatus.READY,
        audio_bytes       = b"\xff\xfb" + b"\x00" * 100,   # fake MP3 bytes
        audio_duration_ms = 3200,
        lip_sync_packet   = sample_lip_sync,
        synthesized_at    = datetime.utcnow(),
    )


def _make_pipeline(
    persona:    PersonaConfig  | None = None,
    tts         = None,
    bridge      = None,
    meetings    = None,
    detector    = None,
    orchestrator = None,
) -> AvatarInterviewPipeline:
    """Build a pipeline with all components mocked."""
    pipeline = AvatarInterviewPipeline(
        persona_config  = persona or DEFAULT_PERSONA,
        tts_service     = tts or MagicMock(),
        avatar_bridge   = bridge or MagicMock(),
        meeting_manager = meetings or MagicMock(),
        detector        = detector or MagicMock(),
        orchestrator    = orchestrator or MagicMock(),
    )
    return pipeline


# ─────────────────────────────────────────────────────
#  AvatarInterviewResult
# ─────────────────────────────────────────────────────

class TestAvatarInterviewResult:

    def test_duration_seconds_none_when_not_completed(self):
        result = AvatarInterviewResult(applicant_id="APP-001")
        assert result.duration_seconds is None

    def test_duration_seconds_calculated(self):
        t0 = datetime(2026, 4, 20, 14, 0, 0)
        t1 = datetime(2026, 4, 20, 14, 45, 30)
        result = AvatarInterviewResult(
            applicant_id = "APP-001",
            started_at   = t0,
            completed_at = t1,
        )
        assert result.duration_seconds == pytest.approx(2730.0)

    def test_summary_with_decision(self):
        decision = OrchestratorDecision(
            applicant_id = "APP-001",
            verdict      = "accept",
            confidence   = 0.92,
            reason       = "Strong technical background",
            next_action  = "send_offer",
        )
        result = AvatarInterviewResult(
            applicant_id  = "APP-001",
            decision      = decision,
            round_scores  = [82.0, 75.0, 88.0],
            total_ai_flags = 0,
            started_at    = datetime(2026, 4, 20, 14, 0, 0),
            completed_at  = datetime(2026, 4, 20, 14, 47, 0),
        )
        summary = result.summary()
        assert "accept" in summary
        assert "send_offer" in summary
        assert "APP-001" in summary

    def test_summary_without_decision(self):
        result = AvatarInterviewResult(applicant_id="APP-002")
        assert "no decision" in result.summary()

    def test_error_field_survives_construction(self):
        result = AvatarInterviewResult(
            applicant_id = "APP-003",
            error        = "Bot failed to join meeting",
        )
        assert result.error == "Bot failed to join meeting"
        assert result.decision is None


# ─────────────────────────────────────────────────────
#  _choose_emotion
# ─────────────────────────────────────────────────────

class TestChooseEmotion:

    def test_opening_turn_always_engaged(self):
        for round_num in (1, 2, 3):
            assert _choose_emotion(round_num, 0) == AvatarEmotionState.ENGAGED

    def test_technical_round_mid_turn_thinking(self):
        assert _choose_emotion(2, 3) == AvatarEmotionState.THINKING

    def test_screening_round_mid_turn_engaged(self):
        assert _choose_emotion(1, 2) == AvatarEmotionState.ENGAGED

    def test_cultural_round_mid_turn_engaged(self):
        assert _choose_emotion(3, 4) == AvatarEmotionState.ENGAGED

    def test_returns_avatar_emotion_state(self):
        emotion = _choose_emotion(1, 0)
        assert isinstance(emotion, AvatarEmotionState)


# ─────────────────────────────────────────────────────
#  _empty_score helper
# ─────────────────────────────────────────────────────

class TestEmptyScore:

    def test_returns_applicant_score(self):
        score = _empty_score("APP-001", "Jane Doe")
        assert isinstance(score, ApplicantScore)

    def test_status_is_skipped(self):
        score = _empty_score("APP-001", "Jane Doe")
        assert score.status == ScoringStatus.SKIPPED

    def test_final_score_is_none(self):
        score = _empty_score("APP-001", "Jane Doe")
        assert score.final_score is None

    def test_ids_set_correctly(self):
        score = _empty_score("APP-TEST", "Test Name")
        assert score.applicant_id   == "APP-TEST"
        assert score.applicant_name == "Test Name"


# ─────────────────────────────────────────────────────
#  Pipeline construction
# ─────────────────────────────────────────────────────

class TestPipelineConstruction:

    def test_defaults_to_sarah_mitchell_persona(self):
        pipeline = _make_pipeline()
        assert pipeline.persona.name == "Sarah Mitchell"

    def test_accepts_custom_persona(self):
        custom = PersonaConfig(
            name="Alex Chen",
            title="Engineering Manager",
            company="Acme Corp",
            years_experience=10,
            backstory="Alex leads platform teams.",
            personality_traits=[],
            interview_style="technical",
            voice_id="male_en_professional_01",
            speech_rate=1.0,
            avatar_asset_id="corporate_male_01",
            avatar_emotion_default="neutral",
        )
        pipeline = _make_pipeline(persona=custom)
        assert pipeline.persona.name == "Alex Chen"

    def test_build_avatar_pipeline_factory(self):
        """build_avatar_pipeline() returns AvatarInterviewPipeline instance."""
        with (
            patch("pipelines.avatar_interview_flow.TTSService.from_persona"),
            patch("pipelines.avatar_interview_flow.AvatarBridge.from_env"),
            patch("pipelines.avatar_interview_flow.build_meeting_manager"),
            patch("pipelines.avatar_interview_flow.DetectorAgent"),
            patch("pipelines.avatar_interview_flow.OrchestratorAgent"),
        ):
            pipeline = build_avatar_pipeline()
            assert isinstance(pipeline, AvatarInterviewPipeline)


# ─────────────────────────────────────────────────────
#  _setup_meeting
# ─────────────────────────────────────────────────────

class TestSetupMeeting:

    @pytest.mark.asyncio
    async def test_creates_meeting_room(self, sample_applicant, sample_room):
        meetings_mock = MagicMock()
        meetings_mock.create_meeting = AsyncMock(return_value=sample_room)

        pipeline = _make_pipeline(meetings=meetings_mock)
        room = await pipeline._setup_meeting(
            applicant    = sample_applicant,
            session_id   = "SESS-TEST001",
            scheduled_at = datetime(2026, 4, 20, 14, 30),
            send_email   = False,
        )

        assert room.room_id == "HireIQ-TESTROOM0001"
        meetings_mock.create_meeting.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_correct_email_flag(self, sample_applicant, sample_room):
        """send_email=True only when email is set AND caller wants it."""
        meetings_mock = MagicMock()
        meetings_mock.create_meeting = AsyncMock(return_value=sample_room)

        pipeline = _make_pipeline(meetings=meetings_mock)
        await pipeline._setup_meeting(
            applicant    = sample_applicant,
            session_id   = "SESS-TEST002",
            scheduled_at = datetime(2026, 4, 20, 14, 30),
            send_email   = True,
        )
        call_kwargs = meetings_mock.create_meeting.call_args.kwargs
        # applicant.email is "priya@example.com" (truthy) → send_email should be True
        assert call_kwargs["send_email"] is True

    @pytest.mark.asyncio
    async def test_defaults_scheduled_at_to_30_minutes_from_now(
        self, sample_applicant, sample_room
    ):
        meetings_mock = MagicMock()
        meetings_mock.create_meeting = AsyncMock(return_value=sample_room)

        pipeline = _make_pipeline(meetings=meetings_mock)
        before = datetime.utcnow()
        await pipeline._setup_meeting(
            applicant    = sample_applicant,
            session_id   = "SESS-TEST003",
            scheduled_at = None,    # ← should default to now + 30 min
            send_email   = False,
        )
        after = datetime.utcnow()

        call_kwargs = meetings_mock.create_meeting.call_args.kwargs
        scheduled = call_kwargs["scheduled_at"]

        # Should be approximately now + 30 minutes
        expected_min = before + timedelta(minutes=29)
        expected_max = after  + timedelta(minutes=31)
        assert expected_min <= scheduled <= expected_max


# ─────────────────────────────────────────────────────
#  _speak_turn
# ─────────────────────────────────────────────────────

class TestSpeakTurn:

    @pytest.mark.asyncio
    async def test_speak_turn_calls_tts_and_coordinator(
        self, sample_tts_response
    ):
        tts_mock      = MagicMock()
        tts_mock.synthesize = AsyncMock(return_value=sample_tts_response)

        bridge_mock   = MagicMock()
        bridge_mock.set_listen_pose = AsyncMock(return_value=True)
        bridge_mock.trigger_speech  = AsyncMock(return_value=True)
        bridge_mock.end_speech      = AsyncMock(return_value=True)
        bridge_mock.send_viseme_packet = AsyncMock(return_value=True)

        bot_mock      = MagicMock()
        bot_mock.speak = AsyncMock(return_value=3200)

        from connectors.avatar_bridge import SpeechTurnCoordinator
        coordinator = SpeechTurnCoordinator(bridge_mock)
        coordinator.prepare = AsyncMock(return_value=True)
        coordinator.start   = AsyncMock(return_value=True)
        coordinator.finish  = AsyncMock()

        avatar_meta = AvatarSessionMetadata(
            session_id   = "SESS-TST",
            applicant_id = "APP-001",
            persona_name = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
        )

        pipeline = _make_pipeline(tts=tts_mock)
        pipeline.bridge = bridge_mock

        await pipeline._speak_turn(
            question_text = "Tell me about yourself.",
            session_id    = "SESS-TST",
            turn_index    = 0,
            round_number  = 1,
            turn_in_round = 0,
            bot           = bot_mock,
            coordinator   = coordinator,
            avatar_meta   = avatar_meta,
        )

        tts_mock.synthesize.assert_awaited_once()
        assert avatar_meta.total_tts_calls == 1

    @pytest.mark.asyncio
    async def test_speak_turn_survives_tts_failure(self):
        """If TTS raises, speak_turn should catch it and set listen pose."""
        tts_mock = MagicMock()
        tts_mock.synthesize = AsyncMock(side_effect=RuntimeError("TTS service down"))

        bridge_mock = MagicMock()
        bridge_mock.set_listen_pose = AsyncMock(return_value=True)

        from connectors.avatar_bridge import SpeechTurnCoordinator
        coordinator = SpeechTurnCoordinator(bridge_mock)

        bot_mock = MagicMock()
        bot_mock.speak = AsyncMock(return_value=0)

        avatar_meta = AvatarSessionMetadata(
            session_id   = "SESS-FAIL",
            applicant_id = "APP-001",
            persona_name = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
        )

        pipeline = _make_pipeline(tts=tts_mock)
        pipeline.bridge = bridge_mock

        # Should NOT raise — non-fatal
        await pipeline._speak_turn(
            question_text = "What's your background?",
            session_id    = "SESS-FAIL",
            turn_index    = 1,
            round_number  = 1,
            turn_in_round = 1,
            bot           = bot_mock,
            coordinator   = coordinator,
            avatar_meta   = avatar_meta,
        )
        # TTS failed → set_listen_pose called to un-freeze avatar
        bridge_mock.set_listen_pose.assert_awaited_once()


# ─────────────────────────────────────────────────────
#  _wait_for_candidate
# ─────────────────────────────────────────────────────

class TestWaitForCandidate:

    @pytest.mark.asyncio
    async def test_returns_true_when_audio_detected(self):
        """Bot queue has audio → candidate detected immediately."""
        bot_mock = MagicMock()
        bot_mock._audio_queue = asyncio.Queue()
        await bot_mock._audio_queue.put(b"\x00" * 100)

        pipeline = _make_pipeline()
        result = await pipeline._wait_for_candidate(bot_mock, timeout=5.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """Empty queue → times out → returns False."""
        bot_mock = MagicMock()
        bot_mock._audio_queue = asyncio.Queue()   # empty

        pipeline = _make_pipeline()
        # Use a very short timeout for speed (2.1s because poll_secs=2.0)
        result = await pipeline._wait_for_candidate(bot_mock, timeout=2.1)
        assert result is False


# ─────────────────────────────────────────────────────
#  Full pipeline run() — end-to-end with all mocks
# ─────────────────────────────────────────────────────

class TestFullPipelineRun:

    def _make_full_mock_pipeline(
        self,
        sample_applicant,
        sample_room,
        sample_session,
        sample_score,
    ) -> AvatarInterviewPipeline:
        """Build a pipeline where every external call is mocked."""

        # Meeting manager
        meetings_mock = MagicMock()
        meetings_mock.create_meeting = AsyncMock(return_value=sample_room)

        # Avatar bridge
        bridge_mock = MagicMock()
        bridge_mock.is_connected = True
        bridge_mock.connect      = AsyncMock(return_value=True)
        bridge_mock.disconnect   = AsyncMock()
        bridge_mock.reset        = AsyncMock(return_value=True)
        bridge_mock.set_idle     = AsyncMock(return_value=True)
        bridge_mock.set_listen_pose  = AsyncMock(return_value=True)
        bridge_mock.set_emotion      = AsyncMock(return_value=True)
        bridge_mock.send_viseme_packet = AsyncMock(return_value=True)
        bridge_mock.trigger_speech   = AsyncMock(return_value=True)
        bridge_mock.end_speech       = AsyncMock(return_value=True)

        # TTS
        lip_sync = LipSyncPacket(
            session_id="SESS-PHASE5TST", turn_index=0,
            audio_duration_ms=1000, frames=[]
        )
        tts_resp = TTSResponse(
            request_id="req-001", session_id="SESS-PHASE5TST",
            status=TTSStatus.READY, audio_bytes=b"\x00" * 50,
            audio_duration_ms=1000, lip_sync_packet=lip_sync,
        )
        tts_mock = MagicMock()
        tts_mock.synthesize = AsyncMock(return_value=tts_resp)

        # Detector
        from agents.detector import DetectionResult
        from models.applicant import AIDetectionVerdict
        det_result = DetectionResult(
            question_id = "Q-001",
            verdict     = AIDetectionVerdict.CLEAN,
            confidence  = 0.1,
            flagged     = False,
        )
        detector_mock = MagicMock()
        detector_mock.detect = AsyncMock(return_value=det_result)

        # Orchestrator
        decision = OrchestratorDecision(
            applicant_id = sample_applicant.id,
            verdict      = "accept",
            confidence   = 0.88,
            reason       = "Strong performance across all rounds",
            next_action  = "send_offer",
        )
        orchestrator_mock = MagicMock()
        orchestrator_mock.decide = AsyncMock(return_value=decision)

        pipeline = AvatarInterviewPipeline(
            persona_config   = DEFAULT_PERSONA,
            tts_service      = tts_mock,
            avatar_bridge    = bridge_mock,
            meeting_manager  = meetings_mock,
            detector         = detector_mock,
            orchestrator     = orchestrator_mock,
        )
        return pipeline

    @pytest.mark.asyncio
    async def test_run_returns_result_on_candidate_no_show(
        self, sample_applicant, sample_room, sample_session, sample_score
    ):
        """
        If the candidate doesn't join within timeout, pipeline returns
        an abandoned result — not an exception.
        """
        pipeline = self._make_full_mock_pipeline(
            sample_applicant, sample_room, sample_session, sample_score
        )

        # Bot: joins OK, but candidate audio queue stays empty → timeout
        bot_mock = MagicMock()
        bot_mock.__aenter__ = AsyncMock(return_value=bot_mock)
        bot_mock.__aexit__  = AsyncMock(return_value=False)
        bot_mock.join       = AsyncMock(return_value=True)
        bot_mock.start_candidate_audio_capture = AsyncMock()
        bot_mock._audio_queue = asyncio.Queue()   # empty

        with patch("pipelines.avatar_interview_flow.build_jitsi_bot", return_value=bot_mock):
            result = await pipeline.run(
                applicant                    = sample_applicant,
                score                        = sample_score,
                send_email                   = False,
                candidate_join_timeout_secs  = 2.1,  # short for speed
            )

        assert result.error == "Candidate did not join the meeting"
        assert result.meeting_room is not None
        assert result.decision is None

    @pytest.mark.asyncio
    async def test_run_returns_error_result_when_bot_fails_to_join(
        self, sample_applicant, sample_room, sample_session, sample_score
    ):
        """
        If bot.join() returns False (Playwright error), pipeline returns
        a result with error set — not an unhandled exception.
        """
        pipeline = self._make_full_mock_pipeline(
            sample_applicant, sample_room, sample_session, sample_score
        )

        bot_mock = MagicMock()
        bot_mock.__aenter__ = AsyncMock(return_value=bot_mock)
        bot_mock.__aexit__  = AsyncMock(return_value=False)
        bot_mock.join       = AsyncMock(return_value=False)   # ← join fails
        bot_mock.start_candidate_audio_capture = AsyncMock()
        bot_mock._audio_queue = asyncio.Queue()

        with patch("pipelines.avatar_interview_flow.build_jitsi_bot", return_value=bot_mock):
            result = await pipeline.run(
                applicant   = sample_applicant,
                score       = sample_score,
                send_email  = False,
                candidate_join_timeout_secs = 2.0,
            )

        assert result.error is not None
        assert "join" in result.error.lower() or "bot" in result.error.lower()
        assert result.completed_at is not None


# ─────────────────────────────────────────────────────
#  Jitsi URL generation (Phase 4 regression)
# ─────────────────────────────────────────────────────

class TestJitsiURLGeneration:
    """
    Phase 4 regression: room ID generation used by the avatar pipeline
    must remain stable — same session_id always produces same room.
    """

    def test_room_id_is_deterministic(self):
        sid = "SESS-AVATARPIPELINE01"
        assert generate_room_id(sid) == generate_room_id(sid)

    def test_room_id_starts_with_prefix(self):
        room_id = generate_room_id("SESS-TEST")
        assert room_id.startswith("HireIQ-")

    def test_candidate_url_contains_room_id(self):
        room_id = generate_room_id("SESS-TEST")
        url     = generate_candidate_url(room_id)
        assert room_id in url

    def test_ten_sessions_produce_ten_unique_rooms(self):
        room_ids = {generate_room_id(f"SESS-{i:04d}") for i in range(10)}
        assert len(room_ids) == 10

    def test_room_id_is_uppercase_hex(self):
        room_id = generate_room_id("SESS-UPPER")
        suffix  = room_id.split("HireIQ-")[1]
        assert suffix == suffix.upper()
        assert all(c in "0123456789ABCDEF" for c in suffix)


# ─────────────────────────────────────────────────────
#  AvatarSessionMetadata
# ─────────────────────────────────────────────────────

class TestAvatarSessionMetadata:

    def test_is_live_returns_true_when_active(self):
        meta = AvatarSessionMetadata(
            session_id    = "SESS-001",
            applicant_id  = "APP-001",
            persona_name  = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
            meeting_status = MeetingStatus.ACTIVE,
        )
        assert meta.is_live() is True

    def test_is_live_returns_false_when_pending(self):
        meta = AvatarSessionMetadata(
            session_id    = "SESS-002",
            applicant_id  = "APP-001",
            persona_name  = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
            meeting_status = MeetingStatus.PENDING,
        )
        assert meta.is_live() is False

    def test_duration_seconds_none_when_not_started(self):
        meta = AvatarSessionMetadata(
            session_id    = "SESS-003",
            applicant_id  = "APP-001",
            persona_name  = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
        )
        assert meta.duration_seconds() is None

    def test_duration_seconds_calculated(self):
        t0  = datetime(2026, 4, 20, 14, 0, 0)
        t1  = datetime(2026, 4, 20, 14, 45, 30)
        meta = AvatarSessionMetadata(
            session_id        = "SESS-004",
            applicant_id      = "APP-001",
            persona_name      = "Sarah Mitchell",
            persona_title     = "Senior Talent Acquisition Lead",
            avatar_started_at = t0,
            avatar_ended_at   = t1,
        )
        assert meta.duration_seconds() == pytest.approx(2730.0)

    def test_tts_calls_counter_increments(self):
        meta = AvatarSessionMetadata(
            session_id    = "SESS-005",
            applicant_id  = "APP-001",
            persona_name  = "Sarah Mitchell",
            persona_title = "Senior Talent Acquisition Lead",
        )
        assert meta.total_tts_calls == 0
        meta.total_tts_calls += 1
        meta.total_tts_calls += 1
        assert meta.total_tts_calls == 2
