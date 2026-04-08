"""
connectors/supabase_mcp.py
═══════════════════════════════════════════════════════
Supabase memory connector — Open Brain / MCP memory.
Persists applicants, scores, and interview sessions
to Supabase PostgreSQL.

Tables used:
  applicants       → full applicant profiles
  scores           → scoring results per applicant
  interview_sessions → interview session data
  agent_memory     → key-value store for agent learning

Usage:
  from connectors.supabase_mcp import supabase_store
  await supabase_store.save_applicant(applicant)
  applicants = await supabase_store.get_all_applicants()
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from models.applicant import Applicant, ApplicationStatus
from models.interview import InterviewSession
from models.score import ApplicantScore
from utils.logger import logger

load_dotenv()


# ─────────────────────────────────────────────────────
#  Table Names
# ─────────────────────────────────────────────────────

TABLE_APPLICANTS         = "applicants"
TABLE_SCORES             = "scores"
TABLE_INTERVIEW_SESSIONS = "interview_sessions"
TABLE_AGENT_MEMORY       = "agent_memory"


# ─────────────────────────────────────────────────────
#  Supabase Client
# ─────────────────────────────────────────────────────

def _get_client() -> Client:
    """Create and return Supabase client from env vars."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_KEY must be set in your .env file"
        )
    return create_client(url, key)


# ─────────────────────────────────────────────────────
#  SQL Schema (run once to set up tables)
# ─────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Applicants table
CREATE TABLE IF NOT EXISTS applicants (
    id                      TEXT PRIMARY KEY,
    full_name               TEXT NOT NULL,
    email                   TEXT UNIQUE NOT NULL,
    phone                   TEXT,
    location                TEXT,
    role_applied            TEXT NOT NULL,
    experience_level        TEXT,
    total_experience_months INTEGER DEFAULT 0,
    resume_url              TEXT,
    resume_text             TEXT,
    github_url              TEXT,
    portfolio_url           TEXT,
    linkedin_url            TEXT,
    cover_letter            TEXT,
    education               TEXT,
    skills                  JSONB DEFAULT '[]',
    status                  TEXT DEFAULT 'pending',
    source                  TEXT DEFAULT 'portal',
    applied_at              TIMESTAMPTZ DEFAULT NOW(),
    raw_data                JSONB,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Scores table
CREATE TABLE IF NOT EXISTS scores (
    id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    applicant_id        TEXT REFERENCES applicants(id) ON DELETE CASCADE,
    final_score         FLOAT,
    grade               TEXT,
    rank                INTEGER,
    percentile          FLOAT,
    dimension_scores    JSONB DEFAULT '[]',
    strengths           JSONB DEFAULT '[]',
    weaknesses          JSONB DEFAULT '[]',
    overall_summary     TEXT,
    recommendation      TEXT,
    model_used          TEXT,
    status              TEXT DEFAULT 'pending',
    scored_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Interview sessions table
CREATE TABLE IF NOT EXISTS interview_sessions (
    session_id          TEXT PRIMARY KEY,
    applicant_id        TEXT REFERENCES applicants(id) ON DELETE CASCADE,
    applicant_name      TEXT,
    role_applied        TEXT,
    current_round       INTEGER DEFAULT 1,
    total_rounds        INTEGER DEFAULT 3,
    status              TEXT DEFAULT 'scheduled',
    interview_type      TEXT DEFAULT 'screening',
    messages            JSONB DEFAULT '[]',
    questions           JSONB DEFAULT '[]',
    responses           JSONB DEFAULT '[]',
    round_summaries     JSONB DEFAULT '[]',
    final_score         FLOAT,
    final_verdict       TEXT,
    total_ai_flags      INTEGER DEFAULT 0,
    model_used          TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Agent memory table (key-value store for learner agent)
CREATE TABLE IF NOT EXISTS agent_memory (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    agent       TEXT,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
"""


# ─────────────────────────────────────────────────────
#  Supabase Store
# ─────────────────────────────────────────────────────

class SupabaseStore:
    """
    Supabase persistence layer for the hiring agent.
    Handles CRUD for applicants, scores, and sessions.
    """

    def __init__(self) -> None:
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        """Lazy-init Supabase client."""
        if self._client is None:
            self._client = _get_client()
        return self._client

    def is_connected(self) -> bool:
        """Check if Supabase connection is working."""
        try:
            self.client.table(TABLE_APPLICANTS).select("id").limit(1).execute()
            return True
        except Exception as e:
            logger.error(f"Supabase connection failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  Applicants
    # ─────────────────────────────────────────────

    def save_applicant(self, applicant: Applicant) -> bool:
        """
        Insert or update an applicant in Supabase.
        Returns True on success.
        """
        try:
            data = {
                "id":                       applicant.id,
                "full_name":                applicant.full_name,
                "email":                    applicant.email,
                "phone":                    applicant.phone,
                "location":                 applicant.location,
                "role_applied":             applicant.role_applied.value,
                "experience_level":         applicant.experience_level.value,
                "total_experience_months":  applicant.total_experience_months,
                "resume_url":               applicant.resume_url,
                "resume_text":              applicant.resume_text,
                "github_url":               applicant.github_url,
                "portfolio_url":            applicant.portfolio_url,
                "linkedin_url":             applicant.linkedin_url,
                "cover_letter":             applicant.cover_letter,
                "education":                applicant.education,
                "skills":                   json.dumps([s.model_dump() for s in applicant.skills]),
                "status":                   applicant.status.value,
                "source":                   applicant.source,
                "applied_at":               applicant.applied_at.isoformat(),
                "updated_at":               datetime.utcnow().isoformat(),
            }
            self.client.table(TABLE_APPLICANTS).upsert(data).execute()
            logger.info(f"Applicant saved | {applicant.id} | {applicant.full_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save applicant {applicant.id}: {e}")
            return False

    def get_applicant(self, applicant_id: str) -> Optional[dict]:
        """Fetch a single applicant by ID."""
        try:
            res = (
                self.client
                .table(TABLE_APPLICANTS)
                .select("*")
                .eq("id", applicant_id)
                .single()
                .execute()
            )
            return res.data
        except Exception as e:
            logger.error(f"Failed to get applicant {applicant_id}: {e}")
            return None

    def get_all_applicants(
        self,
        status: Optional[str] = None,
        role: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Fetch all applicants with optional filters.
        Returns list of raw dicts from Supabase.
        """
        try:
            query = self.client.table(TABLE_APPLICANTS).select("*")
            if status:
                query = query.eq("status", status)
            if role:
                query = query.eq("role_applied", role)
            query = query.limit(limit).order("applied_at", desc=True)
            res = query.execute()
            return res.data or []
        except Exception as e:
            logger.error(f"Failed to fetch applicants: {e}")
            return []

    def update_applicant_status(
        self,
        applicant_id: str,
        new_status: ApplicationStatus,
    ) -> bool:
        """Update applicant status."""
        try:
            self.client.table(TABLE_APPLICANTS).update({
                "status":     new_status.value,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", applicant_id).execute()
            logger.info(f"Status updated | {applicant_id} → {new_status.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to update status for {applicant_id}: {e}")
            return False

    def count_applicants(self, status: Optional[str] = None) -> int:
        """Return total applicant count, optionally filtered by status."""
        try:
            query = self.client.table(TABLE_APPLICANTS).select("id", count="exact")
            if status:
                query = query.eq("status", status)
            res = query.execute()
            return res.count or 0
        except Exception as e:
            logger.error(f"Failed to count applicants: {e}")
            return 0

    # ─────────────────────────────────────────────
    #  Scores
    # ─────────────────────────────────────────────

    def save_score(self, score: ApplicantScore) -> bool:
        """Save or update scoring result for an applicant."""
        try:
            data = {
                "applicant_id":     score.applicant_id,
                "final_score":      score.final_score,
                "grade":            score.grade.value if score.grade else None,
                "rank":             score.rank,
                "percentile":       score.percentile,
                "dimension_scores": json.dumps([d.model_dump() for d in score.dimension_scores]),
                "strengths":        json.dumps(score.strengths),
                "weaknesses":       json.dumps(score.weaknesses),
                "overall_summary":  score.overall_summary,
                "recommendation":   score.recommendation,
                "model_used":       score.model_used,
                "status":           score.status.value,
                "scored_at":        score.scored_at.isoformat() if score.scored_at else None,
            }
            self.client.table(TABLE_SCORES).upsert(data).execute()
            logger.info(
                f"Score saved | {score.applicant_id} | "
                f"Score: {score.final_score} | Grade: {score.grade}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save score for {score.applicant_id}: {e}")
            return False

    def get_score(self, applicant_id: str) -> Optional[dict]:
        """Fetch score for a specific applicant."""
        try:
            res = (
                self.client
                .table(TABLE_SCORES)
                .select("*")
                .eq("applicant_id", applicant_id)
                .single()
                .execute()
            )
            return res.data
        except Exception as e:
            logger.error(f"Failed to get score for {applicant_id}: {e}")
            return None

    def get_top_scored(self, limit: int = 50) -> list[dict]:
        """Return top N applicants by score, descending."""
        try:
            res = (
                self.client
                .table(TABLE_SCORES)
                .select("*")
                .order("final_score", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"Failed to get top scored: {e}")
            return []

    # ─────────────────────────────────────────────
    #  Interview Sessions
    # ─────────────────────────────────────────────

    def save_session(self, session: InterviewSession) -> bool:
        """Save or update an interview session."""
        try:
            data = {
                "session_id":       session.session_id,
                "applicant_id":     session.applicant_id,
                "applicant_name":   session.applicant_name,
                "role_applied":     session.role_applied,
                "current_round":    session.current_round,
                "total_rounds":     session.total_rounds,
                "status":           session.status.value,
                "interview_type":   session.interview_type.value,
                "messages":         json.dumps([m.model_dump(mode="json") for m in session.messages]),
                "questions":        json.dumps([q.model_dump(mode="json") for q in session.questions]),
                "responses":        json.dumps([r.model_dump(mode="json") for r in session.responses]),
                "round_summaries":  json.dumps([s.model_dump(mode="json") for s in session.round_summaries]),
                "final_score":      session.final_score,
                "final_verdict":    session.final_verdict,
                "total_ai_flags":   session.total_ai_flags,
                "model_used":       session.model_used,
                "started_at":       session.started_at.isoformat() if session.started_at else None,
                "completed_at":     session.completed_at.isoformat() if session.completed_at else None,
            }
            self.client.table(TABLE_INTERVIEW_SESSIONS).upsert(data).execute()
            logger.info(f"Session saved | {session.session_id} | {session.summary()}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")
            return False

    def get_session(self, session_id: str) -> Optional[dict]:
        """Fetch an interview session by ID."""
        try:
            res = (
                self.client
                .table(TABLE_INTERVIEW_SESSIONS)
                .select("*")
                .eq("session_id", session_id)
                .single()
                .execute()
            )
            return res.data
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            return None

    def get_sessions_for_applicant(self, applicant_id: str) -> list[dict]:
        """Fetch all interview sessions for an applicant."""
        try:
            res = (
                self.client
                .table(TABLE_INTERVIEW_SESSIONS)
                .select("*")
                .eq("applicant_id", applicant_id)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"Failed to get sessions for {applicant_id}: {e}")
            return []

    # ─────────────────────────────────────────────
    #  Agent Memory (key-value store)
    # ─────────────────────────────────────────────

    def memory_set(self, key: str, value: dict, agent: str = "system") -> bool:
        """Store a key-value pair in agent memory."""
        try:
            self.client.table(TABLE_AGENT_MEMORY).upsert({
                "key":        key,
                "value":      json.dumps(value),
                "agent":      agent,
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Memory set failed for key '{key}': {e}")
            return False

    def memory_get(self, key: str) -> Optional[dict]:
        """Retrieve a value from agent memory."""
        try:
            res = (
                self.client
                .table(TABLE_AGENT_MEMORY)
                .select("value")
                .eq("key", key)
                .single()
                .execute()
            )
            if res.data:
                return json.loads(res.data["value"])
            return None
        except Exception as e:
            logger.error(f"Memory get failed for key '{key}': {e}")
            return None

    def memory_delete(self, key: str) -> bool:
        """Delete a key from agent memory."""
        try:
            self.client.table(TABLE_AGENT_MEMORY).delete().eq("key", key).execute()
            return True
        except Exception as e:
            logger.error(f"Memory delete failed for key '{key}': {e}")
            return False

    def print_schema(self) -> None:
        """Print the SQL schema to run in Supabase SQL editor."""
        print("\n" + "="*60)
        print("Run this SQL in your Supabase SQL Editor:")
        print("="*60)
        print(SCHEMA_SQL)
        print("="*60 + "\n")


# ─────────────────────────────────────────────────────
#  Global Instance
# ─────────────────────────────────────────────────────

supabase_store = SupabaseStore()