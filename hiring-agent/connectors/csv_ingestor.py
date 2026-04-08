"""
connectors/csv_ingestor.py
═══════════════════════════════════════════════════════
Bulk applicant ingestion from CSV and Excel files.
Converts spreadsheet rows → validated Applicant models.

Supported formats:
  - CSV  (.csv)
  - Excel (.xlsx, .xls)

Expected columns (flexible — maps common variations):
  name, email, phone, role, experience, skills,
  github, portfolio, linkedin, cover_letter,
  education, location

Usage:
  result = csv_ingestor.ingest(file_bytes, file_type='csv')
  for applicant in result.applicants:
      print(applicant.summary())
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from models.applicant import (
    Applicant,
    ApplicationStatus,
    ExperienceLevel,
    Skill,
    TechRole,
)
from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Column Name Mapping
# ─────────────────────────────────────────────────────

COLUMN_MAP: dict[str, str] = {
    "name": "name", "full_name": "name", "fullname": "name",
    "candidate_name": "name", "applicant_name": "name",
    "email": "email", "email_address": "email", "mail": "email",
    "phone": "phone", "mobile": "phone", "phone_number": "phone", "contact": "phone",
    "role": "role", "position": "role", "job_title": "role",
    "applied_for": "role", "applying_for": "role",
    "experience": "experience", "exp": "experience", "years": "experience",
    "experience_years": "experience", "yrs": "experience",
    "skills": "skills", "tech_skills": "skills", "technologies": "skills", "stack": "skills",
    "github": "github", "github_url": "github", "github_profile": "github",
    "portfolio": "portfolio", "portfolio_url": "portfolio",
    "website": "portfolio", "personal_site": "portfolio",
    "linkedin": "linkedin", "linkedin_url": "linkedin", "linkedin_profile": "linkedin",
    "cover_letter": "cover_letter", "cover letter": "cover_letter",
    "motivation": "cover_letter", "message": "cover_letter",
    "education": "education", "degree": "education", "qualification": "education",
    "location": "location", "city": "location", "address": "location", "place": "location",
}

# ─────────────────────────────────────────────────────
#  Role Mapping
# ─────────────────────────────────────────────────────

ROLE_MAP: dict[str, TechRole] = {
    "sde": TechRole.SDE, "software engineer": TechRole.SDE,
    "software developer": TechRole.SDE,
    "backend": TechRole.BACKEND, "backend engineer": TechRole.BACKEND,
    "backend developer": TechRole.BACKEND,
    "frontend": TechRole.FRONTEND, "frontend engineer": TechRole.FRONTEND,
    "frontend developer": TechRole.FRONTEND,
    "fullstack": TechRole.FULLSTACK, "full stack": TechRole.FULLSTACK,
    "full-stack": TechRole.FULLSTACK,
    "data engineer": TechRole.DATA_ENGINEER, "data engineering": TechRole.DATA_ENGINEER,
    "ml engineer": TechRole.ML_ENGINEER, "machine learning": TechRole.ML_ENGINEER,
    "ml": TechRole.ML_ENGINEER,
    "data scientist": TechRole.DATA_SCIENTIST, "data science": TechRole.DATA_SCIENTIST,
    "ai researcher": TechRole.AI_RESEARCHER, "ai engineer": TechRole.AI_RESEARCHER,
    "devops": TechRole.DEVOPS, "devops engineer": TechRole.DEVOPS,
}


# ─────────────────────────────────────────────────────
#  Ingest Result
# ─────────────────────────────────────────────────────

@dataclass
class IngestResult:
    """Result of a bulk CSV/Excel ingestion."""
    source_label:   str
    file_type:      str
    total_rows:     int                 = 0
    applicants:     list[Applicant]     = field(default_factory=list)
    errors:         list[dict]          = field(default_factory=list)
    skipped:        int                 = 0
    ingested_at:    datetime            = field(default_factory=datetime.utcnow)

    @property
    def success_count(self) -> int:
        return len(self.applicants)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        return (
            f"Ingest [{self.source_label}] | "
            f"Total: {self.total_rows} | "
            f"Success: {self.success_count} | "
            f"Errors: {self.error_count} | "
            f"Skipped: {self.skipped}"
        )


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    rename = {}
    for col in df.columns:
        if col in COLUMN_MAP:
            rename[col] = COLUMN_MAP[col]
    return df.rename(columns=rename)


def _parse_role(raw: str) -> TechRole:
    raw = str(raw).strip().lower()
    for key, role in ROLE_MAP.items():
        if key in raw:
            return role
    return TechRole.SDE


def _parse_experience_level(years: float) -> ExperienceLevel:
    if years == 0:
        return ExperienceLevel.FRESHER
    elif years <= 2:
        return ExperienceLevel.JUNIOR
    elif years <= 5:
        return ExperienceLevel.MID
    elif years <= 8:
        return ExperienceLevel.SENIOR
    else:
        return ExperienceLevel.LEAD


def _parse_skills(raw: str) -> list[Skill]:
    if not raw or (isinstance(raw, float)):
        return []
    raw = str(raw)
    if "|" in raw:
        parts = raw.split("|")
    elif "," in raw:
        parts = raw.split(",")
    elif ";" in raw:
        parts = raw.split(";")
    else:
        parts = [raw]
    return [Skill(name=s.strip()) for s in parts if s.strip()]


def _safe_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float)):
        try:
            import math
            if math.isnan(val):
                return None
        except Exception:
            pass
    val = str(val).strip()
    return val if val and val.lower() != "nan" else None


def _fix_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _generate_id(name: str, index: int) -> str:
    prefix = name[:3].upper() if name else "APP"
    return f"CSV-{prefix}{index:04d}"


# ─────────────────────────────────────────────────────
#  Row → Applicant
# ─────────────────────────────────────────────────────

def _row_to_applicant(row: pd.Series, index: int, source_label: str) -> Applicant:
    name  = _safe_str(row.get("name")) or f"Applicant_{index}"
    email = _safe_str(row.get("email"))

    if not email or "@" not in email:
        raise ValueError(f"Invalid or missing email: '{email}'")

    exp_raw = row.get("experience", 0)
    try:
        exp_years = float(str(exp_raw).strip())
    except (ValueError, TypeError):
        exp_years = 0.0

    exp_months = int(exp_years * 12)
    exp_level  = _parse_experience_level(exp_years)
    role       = _parse_role(row.get("role", "sde"))
    skills     = _parse_skills(row.get("skills", ""))
    github     = _fix_url(_safe_str(row.get("github")))
    portfolio  = _fix_url(_safe_str(row.get("portfolio")))
    linkedin   = _fix_url(_safe_str(row.get("linkedin")))

    return Applicant(
        id=_generate_id(name, index),
        full_name=name,
        email=email.lower().strip(),
        phone=_safe_str(row.get("phone")),
        location=_safe_str(row.get("location")),
        role_applied=role,
        experience_level=exp_level,
        total_experience_months=exp_months,
        skills=skills,
        github_url=github,
        portfolio_url=portfolio,
        linkedin_url=linkedin,
        cover_letter=_safe_str(row.get("cover_letter")),
        education=_safe_str(row.get("education")),
        status=ApplicationStatus.PENDING,
        source=source_label,
    )


# ─────────────────────────────────────────────────────
#  Core CSV Ingestor
# ─────────────────────────────────────────────────────

class CSVIngestor:
    """
    Ingests bulk applicant data from CSV or Excel files.

    Usage:
        result = csv_ingestor.ingest(file_bytes, file_type='csv')
    """

    SUPPORTED_TYPES = {"csv", "xlsx", "xls"}

    def ingest(
        self,
        file_bytes: bytes,
        file_type: str,
        source_label: str = "csv_upload",
    ) -> IngestResult:
        file_type = file_type.lower().strip(".")
        result = IngestResult(source_label=source_label, file_type=file_type)

        if file_type not in self.SUPPORTED_TYPES:
            result.errors.append({"row": 0, "error": f"Unsupported file type: {file_type}"})
            return result

        try:
            if file_type == "csv":
                df = pd.read_csv(io.BytesIO(file_bytes))
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))

            df = _normalize_columns(df)
            result.total_rows = len(df)

            logger.info(
                f"CSV ingest started | Source: {source_label} | "
                f"Rows: {result.total_rows} | Type: {file_type}"
            )

            for idx, row in df.iterrows():
                row_num = int(idx) + 2

                if row.isna().all():
                    result.skipped += 1
                    continue

                try:
                    applicant = _row_to_applicant(row, int(idx), source_label)
                    result.applicants.append(applicant)

                except ValueError as e:
                    result.errors.append({
                        "row":   row_num,
                        "name":  _safe_str(row.get("name", f"Row {row_num}")),
                        "error": str(e),
                    })
                    logger.warning(f"Row {row_num} skipped: {e}")

                except Exception as e:
                    result.errors.append({
                        "row":   row_num,
                        "name":  _safe_str(row.get("name", f"Row {row_num}")),
                        "error": f"Unexpected error: {e}",
                    })
                    logger.error(f"Row {row_num} failed: {e}")

            logger.info(f"CSV ingest complete | {result.summary()}")

        except Exception as e:
            result.errors.append({"row": 0, "error": f"File parse failed: {e}"})
            logger.error(f"CSV ingest failed for {source_label}: {e}")

        return result

    def ingest_from_path(self, file_path: str, source_label: str = "file_upload") -> IngestResult:
        """Ingest from a local file path. Useful for testing."""
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            result = IngestResult(source_label=source_label, file_type="")
            result.errors.append({"row": 0, "error": f"File not found: {file_path}"})
            return result
        return self.ingest(
            file_bytes=path.read_bytes(),
            file_type=path.suffix,
            source_label=source_label,
        )


# ─────────────────────────────────────────────────────
#  Global Instance
# ─────────────────────────────────────────────────────

csv_ingestor = CSVIngestor()