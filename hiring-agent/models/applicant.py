"""
models/applicant.py
═══════════════════════════════════════════════════════
Core data model for the Autonomous Hiring Agent.
Covers tech roles: SDE, Data Engineering, ML/AI.

All models use Pydantic v2 for validation & serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ─────────────────────────────────────────────────────
#  Enums
# ─────────────────────────────────────────────────────

class TechRole(str, Enum):
    """Supported tech roles for screening."""
    SDE             = "sde"               # Software Development Engineer
    DATA_ENGINEER   = "data_engineer"
    ML_ENGINEER     = "ml_engineer"
    DATA_SCIENTIST  = "data_scientist"
    AI_RESEARCHER   = "ai_researcher"
    BACKEND         = "backend"
    FRONTEND        = "frontend"
    FULLSTACK       = "fullstack"
    DEVOPS          = "devops"


class ExperienceLevel(str, Enum):
    """Candidate experience bracket."""
    FRESHER     = "fresher"       # 0 years
    JUNIOR      = "junior"        # 0–2 years
    MID         = "mid"           # 2–5 years
    SENIOR      = "senior"        # 5–8 years
    LEAD        = "lead"          # 8+ years


class ApplicationStatus(str, Enum):
    """
    Simple status — quick pass/fail tracking.
    Used alongside DetailedStatus for full picture.
    """
    PENDING   = "pending"
    SHORTLISTED = "shortlisted"
    ACCEPTED  = "accepted"
    REJECTED  = "rejected"
    ON_HOLD   = "on_hold"


class InterviewRound(str, Enum):
    """Which interview round the applicant is currently in."""
    NOT_STARTED   = "not_started"
    ROUND_1       = "round_1"       # initial screening
    ROUND_2       = "round_2"       # technical deep-dive
    ROUND_3       = "round_3"       # culture / final round
    COMPLETED     = "completed"


class AIDetectionVerdict(str, Enum):
    """Result of AI/plagiarism detection on responses."""
    CLEAN       = "clean"           # human written
    SUSPICIOUS  = "suspicious"      # borderline
    AI_GENERATED = "ai_generated"   # flagged as AI


# ─────────────────────────────────────────────────────
#  Sub-models
# ─────────────────────────────────────────────────────

class WorkExperience(BaseModel):
    """A single work experience entry."""
    company:        str
    role:           str
    duration_months: int            = Field(ge=0)
    description:    Optional[str]   = None
    tech_stack:     list[str]       = Field(default_factory=list)

    @field_validator("duration_months")
    @classmethod
    def duration_must_be_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Duration cannot be negative")
        return v


class Skill(BaseModel):
    """A skill with optional proficiency level (1–5)."""
    name:        str
    proficiency: Optional[int] = Field(default=None, ge=1, le=5)
    # 1=beginner, 2=elementary, 3=intermediate, 4=advanced, 5=expert


class RoundScore(BaseModel):
    """Score details for a single interview round."""
    round:               InterviewRound
    score:               Optional[float]    = Field(default=None, ge=0, le=100)
    ai_verdict:          AIDetectionVerdict = AIDetectionVerdict.CLEAN
    ai_confidence:       Optional[float]    = Field(default=None, ge=0.0, le=1.0)
    interviewer_notes:   Optional[str]      = None
    completed_at:        Optional[datetime] = None


class DetailedStatus(BaseModel):
    """
    Detailed tracking — round-by-round scores + current stage.
    Used alongside the simple ApplicationStatus.
    """
    current_round:   InterviewRound             = InterviewRound.NOT_STARTED
    rounds_completed: list[RoundScore]          = Field(default_factory=list)
    total_score:     Optional[float]            = Field(default=None, ge=0, le=100)
    rank:            Optional[int]              = None   # rank among all applicants
    scorer_notes:    Optional[str]              = None
    final_verdict:   Optional[ApplicationStatus] = None
    last_updated:    datetime                   = Field(default_factory=datetime.utcnow)

    def average_score(self) -> Optional[float]:
        """Compute average score across all completed rounds."""
        scores = [r.score for r in self.rounds_completed if r.score is not None]
        return round(sum(scores) / len(scores), 2) if scores else None


# ─────────────────────────────────────────────────────
#  Core Applicant Model
# ─────────────────────────────────────────────────────

class Applicant(BaseModel):
    """
    Full applicant profile for tech role screening.

    Covers:
    - Personal & contact info
    - Resume / CV path or URL
    - GitHub & portfolio links
    - Work experience & skills
    - Cover letter
    - Application status (simple + detailed)
    - AI detection flags
    """

    # ── Identity ──────────────────────────────────
    id:             str                 = Field(..., description="Unique applicant ID from Internshala")
    full_name:      str                 = Field(..., min_length=2, max_length=100)
    email:          str                 = Field(..., description="Primary contact email")
    phone:          Optional[str]       = None
    location:       Optional[str]       = None

    # ── Role Applied For ──────────────────────────
    role_applied:   TechRole
    experience_level: ExperienceLevel  = ExperienceLevel.FRESHER
    applied_at:     datetime            = Field(default_factory=datetime.utcnow)

    # ── Resume / CV ───────────────────────────────
    resume_url:     Optional[str]       = Field(default=None, description="Link to resume/CV")
    resume_text:    Optional[str]       = Field(default=None, description="Extracted text from resume")

    # ── GitHub & Portfolio ────────────────────────
    github_url:     Optional[str]       = Field(default=None, description="GitHub profile URL")
    portfolio_url:  Optional[str]       = Field(default=None, description="Portfolio / personal site URL")
    linkedin_url:   Optional[str]       = Field(default=None, description="LinkedIn profile URL")

    # ── Cover Letter ──────────────────────────────
    cover_letter:   Optional[str]       = Field(default=None, description="Raw cover letter text")

    # ── Work Experience & Skills ──────────────────
    work_experience: list[WorkExperience] = Field(default_factory=list)
    skills:          list[Skill]          = Field(default_factory=list)
    total_experience_months: int          = Field(default=0, ge=0)
    education:       Optional[str]        = None  # e.g. "B.Tech CSE, IIT Delhi, 2023"

    # ── Status Tracking ───────────────────────────
    status:          ApplicationStatus   = ApplicationStatus.PENDING
    detailed_status: DetailedStatus      = Field(default_factory=DetailedStatus)

    # ── Metadata ──────────────────────────────────
    source:          str                 = "internshala"
    raw_data:        Optional[dict]      = Field(default=None, description="Original API response")

    # ── Validators ────────────────────────────────
    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError(f"Invalid email address: {v}")
        return v.lower().strip()

    @field_validator("github_url", "portfolio_url", "linkedin_url", "resume_url")
    @classmethod
    def url_must_start_with_http(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {v}")
        return v

    @field_validator("total_experience_months", mode="before")
    @classmethod
    def compute_experience(cls, v: int, info) -> int:
        """Auto-compute total experience from work_experience if not provided."""
        if v == 0 and "work_experience" in (info.data or {}):
            return sum(exp.duration_months for exp in info.data["work_experience"])
        return v

    # ── Helpers ───────────────────────────────────
    def total_experience_years(self) -> float:
        """Return total experience in years (rounded to 1 decimal)."""
        return round(self.total_experience_months / 12, 1)

    def skill_names(self) -> list[str]:
        """Return flat list of skill names."""
        return [s.name for s in self.skills]

    def is_shortlisted(self) -> bool:
        return self.status == ApplicationStatus.SHORTLISTED

    def is_rejected(self) -> bool:
        return self.status == ApplicationStatus.REJECTED

    def has_github(self) -> bool:
        return self.github_url is not None

    def has_portfolio(self) -> bool:
        return self.portfolio_url is not None

    def summary(self) -> str:
        """One-line summary for logging and agent prompts."""
        return (
            f"[{self.id}] {self.full_name} | {self.role_applied.value} | "
            f"{self.total_experience_years()}yrs | "
            f"Status: {self.status.value} | "
            f"Round: {self.detailed_status.current_round.value}"
        )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "INT-2024-001",
                "full_name": "Aakarsh Kumar",
                "email": "aakarsh@example.com",
                "phone": "+91-9876543210",
                "location": "Ghaziabad, UP",
                "role_applied": "sde",
                "experience_level": "junior",
                "resume_url": "https://example.com/resume.pdf",
                "github_url": "https://github.com/aakarsh",
                "portfolio_url": "https://aakarsh.dev",
                "cover_letter": "I am passionate about building scalable systems...",
                "skills": [
                    {"name": "Python", "proficiency": 4},
                    {"name": "FastAPI", "proficiency": 3},
                ],
                "work_experience": [
                    {
                        "company": "TechCorp",
                        "role": "Backend Intern",
                        "duration_months": 6,
                        "tech_stack": ["Python", "Django", "PostgreSQL"]
                    }
                ],
                "status": "pending",
            }
        }
    }