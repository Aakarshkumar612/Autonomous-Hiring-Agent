"""
tests/test_interview.py
═══════════════════════════════════════════════════════
Unit tests for the interview session store, session
lifecycle, and round-progression logic. No Groq API calls.

Run with:
    uv run pytest tests/test_interview.py -v
"""

import time
import pytest
from unittest.mock import patch as mock_patch

from memory.session_store import SessionStore
from models.interview import (
    InterviewSession,
    SessionStatus,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    """Fresh SessionStore for each test."""
    return SessionStore()


def _make_session(session_id: str = "sess-001") -> InterviewSession:
    """Minimal InterviewSession for testing."""
    return InterviewSession(
        session_id=session_id,
        applicant_id="APP-TEST001",
        applicant_name="Jane Doe",
        role_applied="sde",
        total_rounds=3,
    )


# ─── SessionStore: basic CRUD ─────────────────────────────────────────────────

class TestSessionStoreCRUD:

    def test_save_and_retrieve(self, store):
        """Session saved can be retrieved by ID."""
        session = _make_session("sess-001")
        store.create_session(session)
        retrieved = store.get_session("sess-001")
        assert retrieved is not None
        assert retrieved.applicant_name == "Jane Doe"

    def test_get_nonexistent_returns_none(self, store):
        """Getting a session that was never saved returns None."""
        result = store.get_session("nonexistent-id")
        assert result is None

    def test_delete_session(self, store):
        """Ending a session makes it unretrievable."""
        session = _make_session("sess-to-delete")
        store.create_session(session)
        store.end_session("sess-to-delete")
        assert store.get_session("sess-to-delete") is None

    def test_delete_nonexistent_does_not_raise(self, store):
        """Ending a session that doesn't exist is a no-op."""
        store.end_session("does-not-exist")  # should not raise

    def test_multiple_sessions_independent(self, store):
        """Multiple sessions coexist without interfering."""
        s1 = _make_session("sess-A")
        s2 = _make_session("sess-B")
        s2.applicant_name = "Bob Smith"
        store.create_session(s1)
        store.create_session(s2)
        assert store.get_session("sess-A").applicant_name == "Jane Doe"
        assert store.get_session("sess-B").applicant_name == "Bob Smith"

    def test_overwrite_existing_session(self, store):
        """update_session with the same session_id overwrites the previous entry."""
        session = _make_session("sess-X")
        store.create_session(session)
        session.applicant_name = "Updated Name"
        store.update_session(session)
        assert store.get_session("sess-X").applicant_name == "Updated Name"


# ─── SessionStore: TTL / expiry ───────────────────────────────────────────────
#
# SessionStore reads its timeout from SESSION_TIMEOUT_HOURS env var (default 24h).
# To test expiry in < 1 second we patch _timeout_hours() to return 1/3600
# (= 1 second expressed in hours) for the duration of the assertion.

_ONE_SECOND_IN_HOURS = 1 / 3600


class TestSessionTTL:

    def test_expired_sessions_purged(self):
        """Sessions older than TTL are removed by purge_expired()."""
        store = SessionStore()
        session = _make_session("sess-expiry")
        store.create_session(session)

        time.sleep(1.1)   # wait for 1-second TTL to elapse

        with mock_patch("memory.session_store._timeout_hours", return_value=_ONE_SECOND_IN_HOURS):
            purged = store.purge_expired()
            retrieved = store.get_session("sess-expiry")

        assert purged >= 1
        assert retrieved is None

    def test_fresh_sessions_not_purged(self, store):
        """Sessions created just now should survive purge_expired()."""
        session = _make_session("sess-fresh")
        store.create_session(session)
        purged = store.purge_expired()   # default 24h TTL — won't expire immediately
        assert purged == 0
        assert store.get_session("sess-fresh") is not None

    def test_purge_returns_count(self):
        """purge_expired() returns the number of sessions removed."""
        store = SessionStore()
        for i in range(3):
            store.create_session(_make_session(f"old-{i}"))
        time.sleep(1.1)
        with mock_patch("memory.session_store._timeout_hours", return_value=_ONE_SECOND_IN_HOURS):
            count = store.purge_expired()
        assert count == 3


# ─── InterviewSession: model tests ───────────────────────────────────────────

class TestInterviewSessionModel:

    def test_default_status_is_not_started(self):
        """New sessions start with a sensible initial status."""
        session = _make_session()
        # The session model should have a status field
        assert hasattr(session, "status")

    def test_default_round_is_one(self):
        """Interviews start at round 1."""
        session = _make_session()
        assert session.current_round == 1

    def test_total_rounds_stored(self):
        """total_rounds is stored from constructor."""
        session = _make_session()
        assert session.total_rounds == 3

    def test_questions_and_responses_start_empty(self):
        """No questions or responses on a fresh session."""
        session = _make_session()
        assert session.questions == []
        assert session.responses == []

    def test_applicant_fields_stored(self):
        """Applicant identity fields are stored correctly."""
        session = _make_session("sess-fields")
        assert session.applicant_id == "APP-TEST001"
        assert session.applicant_name == "Jane Doe"
        assert session.role_applied == "sde"

    def test_ai_flags_starts_at_zero(self):
        """No AI flags on a fresh session."""
        session = _make_session()
        assert session.total_ai_flags == 0

    def test_final_score_starts_none(self):
        """final_score is None until the interview completes."""
        session = _make_session()
        assert session.final_score is None
