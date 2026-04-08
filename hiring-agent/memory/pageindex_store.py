"""
memory/pageindex_store.py
═══════════════════════════════════════════════════════
PageIndex RAG store for the Autonomous Hiring Agent.

PageIndex is a reasoning-based retrieval approach —
NOT embedding-based. Instead of vector similarity,
we store structured profiles and use the LLM's reasoning
to find relevant matches based on query intent.

This store holds applicant profiles, scores, and
interview summaries in memory. Supabase persistence
is handled separately via connectors/supabase_mcp.py.

Usage:
    store = PageIndexStore()
    store.add_applicant(applicant, score)
    profile = store.get_applicant("APP-001")
    matches = store.search_similar_profiles("senior Python backend 5 years")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models.applicant import Applicant
from models.interview import InterviewSession
from models.score import ApplicantScore
from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Profile record stored in the index
# ─────────────────────────────────────────────────────

@dataclass
class ApplicantProfile:
    """
    Flattened, searchable profile for a single applicant.
    Combines Applicant + ApplicantScore + optional session.
    """
    applicant_id:       str
    full_name:          str
    email:              str
    role:               str
    experience_years:   float
    skills:             list[str]
    score:              Optional[float]     = None
    grade:              Optional[str]       = None
    recommendation:     Optional[str]       = None
    strengths:          list[str]           = field(default_factory=list)
    weaknesses:         list[str]           = field(default_factory=list)
    ai_flags:           int                 = 0
    interview_score:    Optional[float]     = None
    status:             str                 = "pending"
    github_url:         Optional[str]       = None
    portfolio_url:      Optional[str]       = None
    education:          Optional[str]       = None
    added_at:           datetime            = field(default_factory=datetime.utcnow)

    def searchable_text(self) -> str:
        """
        Build a flat searchable string for keyword/reasoning-based retrieval.
        Combines all meaningful fields into a single text blob.
        """
        parts = [
            f"Name: {self.full_name}",
            f"Role: {self.role}",
            f"Experience: {self.experience_years} years",
            f"Skills: {', '.join(self.skills)}",
            f"Score: {self.score or 'N/A'}",
            f"Grade: {self.grade or 'N/A'}",
            f"Recommendation: {self.recommendation or 'N/A'}",
            f"Status: {self.status}",
        ]
        if self.strengths:
            parts.append(f"Strengths: {', '.join(self.strengths)}")
        if self.weaknesses:
            parts.append(f"Weaknesses: {', '.join(self.weaknesses)}")
        if self.education:
            parts.append(f"Education: {self.education}")
        if self.github_url:
            parts.append(f"GitHub: {self.github_url}")
        return " | ".join(parts)

    def to_dict(self) -> dict:
        return {
            "applicant_id":     self.applicant_id,
            "full_name":        self.full_name,
            "email":            self.email,
            "role":             self.role,
            "experience_years": self.experience_years,
            "skills":           self.skills,
            "score":            self.score,
            "grade":            self.grade,
            "recommendation":   self.recommendation,
            "strengths":        self.strengths,
            "weaknesses":       self.weaknesses,
            "ai_flags":         self.ai_flags,
            "interview_score":  self.interview_score,
            "status":           self.status,
            "github_url":       self.github_url,
            "portfolio_url":    self.portfolio_url,
            "education":        self.education,
            "added_at":         self.added_at.isoformat(),
        }


# ─────────────────────────────────────────────────────
#  PageIndex Store
# ─────────────────────────────────────────────────────

class PageIndexStore:
    """
    In-memory reasoning-based retrieval store for applicant profiles.

    PageIndex philosophy: store structured text, retrieve by reasoning
    about relevance — not by vector distance. This works well for
    structured hiring data where the fields are known and explicit.

    Thread-safety: This is a simple in-memory dict, designed to be
    used within a single async event loop. Not thread-safe for
    multi-process deployments (use Supabase for that).
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ApplicantProfile] = {}
        logger.debug("PageIndexStore initialized (in-memory)")

    # ─────────────────────────────────────────────────
    #  Write operations
    # ─────────────────────────────────────────────────

    def add_applicant(
        self,
        applicant: Applicant,
        score: ApplicantScore | None = None,
        session: InterviewSession | None = None,
    ) -> ApplicantProfile:
        """
        Add or update an applicant profile in the index.
        Merges score and session data if provided.
        """
        profile = ApplicantProfile(
            applicant_id=applicant.id,
            full_name=applicant.full_name,
            email=applicant.email,
            role=applicant.role_applied.value,
            experience_years=applicant.total_experience_years(),
            skills=applicant.skill_names(),
            status=applicant.status.value,
            github_url=applicant.github_url,
            portfolio_url=applicant.portfolio_url,
            education=applicant.education,
        )

        if score:
            profile.score          = score.final_score
            profile.grade          = score.grade.value if score.grade else None
            profile.recommendation = score.recommendation
            profile.strengths      = score.strengths or []
            profile.weaknesses     = score.weaknesses or []

        if session:
            profile.interview_score = session.final_score
            profile.ai_flags        = session.total_ai_flags

        self._profiles[applicant.id] = profile
        logger.debug(
            f"PageIndex | Added [{applicant.id}] {applicant.full_name} | "
            f"Score: {profile.score} | Role: {profile.role}"
        )
        return profile

    def update_status(self, applicant_id: str, status: str) -> bool:
        """Update the status of an existing profile."""
        if applicant_id not in self._profiles:
            logger.warning(f"PageIndex | update_status: {applicant_id} not found")
            return False
        self._profiles[applicant_id].status = status
        logger.debug(f"PageIndex | Status updated | {applicant_id} → {status}")
        return True

    def remove(self, applicant_id: str) -> bool:
        """Remove a profile from the index."""
        if applicant_id in self._profiles:
            del self._profiles[applicant_id]
            logger.debug(f"PageIndex | Removed [{applicant_id}]")
            return True
        return False

    # ─────────────────────────────────────────────────
    #  Read operations
    # ─────────────────────────────────────────────────

    def get_applicant(self, applicant_id: str) -> ApplicantProfile | None:
        """Retrieve a profile by applicant ID."""
        return self._profiles.get(applicant_id)

    def get_all(self) -> list[ApplicantProfile]:
        """Return all profiles in the index."""
        return list(self._profiles.values())

    def count(self) -> int:
        """Return total number of profiles in the index."""
        return len(self._profiles)

    def search_similar_profiles(
        self,
        query: str,
        top_k: int = 10,
        role_filter: str | None = None,
        min_score: float | None = None,
    ) -> list[ApplicantProfile]:
        """
        Reasoning-based profile search.

        Instead of vector similarity, this uses keyword matching
        on the searchable_text() blob. The caller (typically a pipeline
        or the orchestrator) uses this to find comparable candidates
        for benchmarking, deduplication, or ranking context.

        Args:
            query       — free-text query (e.g. "senior Python backend 5 years")
            top_k       — maximum number of results to return
            role_filter — restrict to a specific role (e.g. "sde")
            min_score   — only return profiles with score >= this value

        Returns:
            List of ApplicantProfile sorted by keyword relevance score.
        """
        query_terms = query.lower().split()
        candidates  = list(self._profiles.values())

        # Apply hard filters first
        if role_filter:
            candidates = [p for p in candidates if p.role == role_filter]
        if min_score is not None:
            candidates = [p for p in candidates if p.score is not None and p.score >= min_score]

        # Score by keyword overlap with searchable_text
        def relevance(profile: ApplicantProfile) -> int:
            text = profile.searchable_text().lower()
            return sum(1 for term in query_terms if term in text)

        ranked = sorted(candidates, key=relevance, reverse=True)
        results = ranked[:top_k]

        logger.debug(
            f"PageIndex | search '{query[:50]}' | "
            f"Candidates: {len(candidates)} | Results: {len(results)}"
        )
        return results

    def get_top_scored(
        self,
        limit: int = 50,
        role_filter: str | None = None,
    ) -> list[ApplicantProfile]:
        """Return top N profiles by score, descending."""
        profiles = list(self._profiles.values())
        if role_filter:
            profiles = [p for p in profiles if p.role == role_filter]

        scored = [p for p in profiles if p.score is not None]
        return sorted(scored, key=lambda p: p.score or 0, reverse=True)[:limit]

    def get_by_status(self, status: str) -> list[ApplicantProfile]:
        """Return all profiles with the given status."""
        return [p for p in self._profiles.values() if p.status == status]

    def stats(self) -> dict:
        """Return summary statistics about the index."""
        profiles = list(self._profiles.values())
        scored   = [p for p in profiles if p.score is not None]
        return {
            "total":         len(profiles),
            "scored":        len(scored),
            "avg_score":     round(sum(p.score for p in scored) / len(scored), 2) if scored else None,
            "shortlisted":   sum(1 for p in profiles if p.status == "shortlisted"),
            "rejected":      sum(1 for p in profiles if p.status == "rejected"),
            "pending":       sum(1 for p in profiles if p.status == "pending"),
            "ai_flagged":    sum(1 for p in profiles if p.ai_flags > 0),
        }
