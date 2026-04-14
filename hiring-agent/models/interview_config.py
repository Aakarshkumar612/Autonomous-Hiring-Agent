"""
models/interview_config.py
═══════════════════════════════════════════════════════
Recruiter-configurable interview question settings.

Recruiters can:
  • Set how many DSA problems to assign (count + per-difficulty breakdown)
  • Set how many SQL problems to assign
  • Enable/disable behavioral, HR, managerial, and technical rounds
  • Provide custom questions for each round
  • Upload files (PDF/DOCX/image/TXT) whose content is parsed into questions

A RecruiterInterviewConfig is referenced by config_id at session-creation
time so each session knows which question distribution to use.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────
#  Sub-models
# ─────────────────────────────────────────────────────

class DifficultyBreakdown(BaseModel):
    """How many problems of each difficulty to include."""
    easy:   int = Field(default=1, ge=0, le=10)
    medium: int = Field(default=1, ge=0, le=10)
    hard:   int = Field(default=0, ge=0, le=10)

    @property
    def total(self) -> int:
        return self.easy + self.medium + self.hard


class DSAQuestionConfig(BaseModel):
    """Configuration for the DSA (algorithm) portion of the interview."""
    difficulties: DifficultyBreakdown = Field(default_factory=DifficultyBreakdown)
    # Optionally pin specific problem IDs (overrides random selection)
    pinned_problem_ids: list[str] = Field(default_factory=list)

    @property
    def total_count(self) -> int:
        return self.difficulties.total


class SQLQuestionConfig(BaseModel):
    """Configuration for the SQL portion of the interview."""
    count:      int   = Field(default=1, ge=0, le=5)
    difficulty: str   = Field(default="medium")   # easy | medium | hard
    pinned_problem_ids: list[str] = Field(default_factory=list)

    @field_validator("difficulty")
    @classmethod
    def _valid_difficulty(cls, v: str) -> str:
        allowed = {"easy", "medium", "hard"}
        if v not in allowed:
            raise ValueError(f"difficulty must be one of {allowed}")
        return v


class RoundConfig(BaseModel):
    """
    Config for a non-coding interview round (behavioral / HR / managerial /
    technical). custom_questions are populated from file uploads or manual
    entry by the recruiter.
    """
    enabled:          bool       = False
    custom_questions: list[str]  = Field(default_factory=list)

    @property
    def question_count(self) -> int:
        return len(self.custom_questions)


# ─────────────────────────────────────────────────────
#  Main config model
# ─────────────────────────────────────────────────────

class RecruiterInterviewConfig(BaseModel):
    """
    Complete interview configuration owned by a recruiter.
    One recruiter can have multiple named configs.
    """
    config_id:   str
    recruiter_id: str
    name:        str                    # e.g. "Senior Backend Engineer Round"

    dsa:         DSAQuestionConfig   = Field(default_factory=DSAQuestionConfig)
    sql:         SQLQuestionConfig   = Field(default_factory=SQLQuestionConfig)
    behavioral:  RoundConfig         = Field(default_factory=RoundConfig)
    hr:          RoundConfig         = Field(default_factory=RoundConfig)
    managerial:  RoundConfig         = Field(default_factory=RoundConfig)
    technical:   RoundConfig         = Field(default_factory=RoundConfig)

    # All questions extracted from uploaded files (merged across uploads)
    extracted_questions: list[str] = Field(default_factory=list)

    created_at:  datetime = Field(default_factory=datetime.utcnow)
    updated_at:  datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────
#  Request / response schemas
# ─────────────────────────────────────────────────────

class CreateInterviewConfigRequest(BaseModel):
    name:       str
    dsa:        Optional[DSAQuestionConfig]  = None
    sql:        Optional[SQLQuestionConfig]  = None
    behavioral: Optional[RoundConfig]        = None
    hr:         Optional[RoundConfig]        = None
    managerial: Optional[RoundConfig]        = None
    technical:  Optional[RoundConfig]        = None


class UploadQuestionsResponse(BaseModel):
    """Returned after a file upload + question extraction."""
    config_id:           str
    filename:            str
    file_type:           str          # pdf | docx | image | txt
    extracted_count:     int
    total_questions:     int          # cumulative across all uploads for this config
    extracted_questions: list[str]    # the newly extracted questions from this file
