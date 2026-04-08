"""
memory/session_store.py
═══════════════════════════════════════════════════════
In-memory session store for active interview sessions.

Tracks live interviews across their full lifecycle:
  SCHEDULED → IN_PROGRESS → COMPLETED / ABANDONED / FAILED

Sessions auto-expire after SESSION_TIMEOUT_HOURS (default 24h)
from the .env file. Expired sessions are removed lazily
on the next read/write access.

Supabase persistence is handled separately by
agents/interviewer.py → connectors/supabase_mcp.py.
This store is for fast in-process lookups only.

Usage:
    store = SessionStore()
    session_id = store.create_session(session)
    session    = store.get_session(session_id)
    store.update_session(session)
    store.end_session(session_id)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models.interview import InterviewSession, SessionStatus
from utils.logger import logger

_DEFAULT_TIMEOUT_HOURS = 24.0


def _timeout_hours() -> float:
    """Read SESSION_TIMEOUT_HOURS from .env at call time."""
    try:
        return float(os.getenv("SESSION_TIMEOUT_HOURS", _DEFAULT_TIMEOUT_HOURS))
    except ValueError:
        return _DEFAULT_TIMEOUT_HOURS


# ─────────────────────────────────────────────────────
#  Session entry (internal wrapper)
# ─────────────────────────────────────────────────────

@dataclass
class _SessionEntry:
    """Internal wrapper around InterviewSession with TTL tracking."""
    session:      InterviewSession
    created_at:   float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)

    def is_expired(self, timeout_hours: float) -> bool:
        """Check if the session has exceeded its timeout since creation."""
        elapsed_hours = (time.monotonic() - self.created_at) / 3600
        return elapsed_hours >= timeout_hours

    def touch(self) -> None:
        """Update last access time."""
        self.last_accessed = time.monotonic()


# ─────────────────────────────────────────────────────
#  Session Store
# ─────────────────────────────────────────────────────

class SessionStore:
    """
    Fast in-memory store for active interview sessions.

    Designed for a single async event loop — not thread-safe
    for multi-process deployments (use Supabase for that).

    Expiry is lazy: sessions are only removed when accessed
    or when purge_expired() is explicitly called.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionEntry] = {}
        logger.debug("SessionStore initialized (in-memory)")

    # ─────────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────────

    def _is_expired(self, entry: _SessionEntry) -> bool:
        return entry.is_expired(_timeout_hours())

    def _prune_if_expired(self, session_id: str) -> bool:
        """
        Remove a session if expired. Returns True if expired and removed.
        """
        entry = self._sessions.get(session_id)
        if entry and self._is_expired(entry):
            del self._sessions[session_id]
            logger.debug(f"SessionStore | Expired & removed [{session_id}]")
            return True
        return False

    # ─────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────

    def create_session(self, session: InterviewSession) -> str:
        """
        Register a new interview session in the store.

        Args:
            session — the InterviewSession to track

        Returns:
            session_id (same as session.session_id)
        """
        session_id = session.session_id
        self._sessions[session_id] = _SessionEntry(session=session)
        logger.info(
            f"SessionStore | Created [{session_id}] | "
            f"Applicant: {session.applicant_name} | "
            f"Role: {session.role_applied}"
        )
        return session_id

    def get_session(self, session_id: str) -> InterviewSession | None:
        """
        Retrieve an active session by ID.

        Returns None if:
          - session does not exist
          - session has expired (and is lazily removed)
        """
        if self._prune_if_expired(session_id):
            return None

        entry = self._sessions.get(session_id)
        if not entry:
            return None

        entry.touch()
        return entry.session

    def update_session(self, session: InterviewSession) -> bool:
        """
        Replace the stored session with an updated version.

        Returns False if the session_id is unknown or expired.
        Use this after every round advancement or response recorded.
        """
        session_id = session.session_id
        if self._prune_if_expired(session_id):
            logger.warning(
                f"SessionStore | update_session: [{session_id}] expired — cannot update"
            )
            return False

        entry = self._sessions.get(session_id)
        if not entry:
            logger.warning(
                f"SessionStore | update_session: [{session_id}] not found"
            )
            return False

        entry.session = session
        entry.touch()
        logger.debug(
            f"SessionStore | Updated [{session_id}] | "
            f"Round: {session.current_round} | "
            f"Status: {session.status.value}"
        )
        return True

    def end_session(self, session_id: str) -> bool:
        """
        Mark a session as completed and remove it from the active store.

        The session has already been persisted to Supabase by the
        InterviewerAgent — this just frees in-memory space.

        Returns True if the session was found and removed.
        """
        if session_id in self._sessions:
            session = self._sessions[session_id].session
            del self._sessions[session_id]
            logger.info(
                f"SessionStore | Ended [{session_id}] | "
                f"Applicant: {session.applicant_name} | "
                f"Final score: {session.final_score}"
            )
            return True

        logger.debug(f"SessionStore | end_session: [{session_id}] not found")
        return False

    def abandon_session(self, session_id: str) -> bool:
        """
        Mark the session as ABANDONED (applicant dropped off).
        Updates session status before removing from store.
        """
        entry = self._sessions.get(session_id)
        if entry:
            entry.session.status = SessionStatus.ABANDONED
            del self._sessions[session_id]
            logger.warning(
                f"SessionStore | ABANDONED [{session_id}] | "
                f"Applicant: {entry.session.applicant_name}"
            )
            return True
        return False

    def purge_expired(self) -> int:
        """
        Eagerly remove all expired sessions.

        Call this periodically (e.g. via a background task) to
        prevent the store from growing unbounded.

        Returns the number of sessions removed.
        """
        timeout = _timeout_hours()
        expired_ids = [
            sid for sid, entry in self._sessions.items()
            if entry.is_expired(timeout)
        ]
        for sid in expired_ids:
            del self._sessions[sid]

        if expired_ids:
            logger.info(
                f"SessionStore | Purged {len(expired_ids)} expired session(s)"
            )
        return len(expired_ids)

    # ─────────────────────────────────────────────────
    #  Read-only helpers
    # ─────────────────────────────────────────────────

    def active_count(self) -> int:
        """Return the number of currently tracked (non-expired) sessions."""
        timeout = _timeout_hours()
        return sum(
            1 for entry in self._sessions.values()
            if not entry.is_expired(timeout)
        )

    def get_all_active(self) -> list[InterviewSession]:
        """Return all non-expired sessions."""
        timeout = _timeout_hours()
        return [
            entry.session
            for entry in self._sessions.values()
            if not entry.is_expired(timeout)
        ]

    def stats(self) -> dict:
        """Return summary statistics about the session store."""
        all_entries = list(self._sessions.values())
        timeout     = _timeout_hours()
        active      = [e for e in all_entries if not e.is_expired(timeout)]
        return {
            "total_tracked":  len(all_entries),
            "active":         len(active),
            "expired":        len(all_entries) - len(active),
            "timeout_hours":  timeout,
            "checked_at":     datetime.utcnow().isoformat(),
        }
