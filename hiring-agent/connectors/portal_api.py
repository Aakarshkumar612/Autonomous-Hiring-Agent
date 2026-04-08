"""
connectors/portal_api.py
═══════════════════════════════════════════════════════
FastAPI application intake portal.
Candidates apply directly through your own endpoints.

Endpoints:
  POST /apply           → submit application (form data + resume)
  POST /apply/bulk      → upload CSV/Excel of applicants
  GET  /applicants      → list all applicants
  GET  /applicants/{id} → get single applicant
  GET  /health          → health check

Run locally:
  uv run uvicorn connectors.portal_api:app --reload --port 8000

Then open: http://localhost:8000/docs  (auto-generated Swagger UI)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from connectors.csv_ingestor import csv_ingestor
from connectors.resume_parser import resume_parser
from models.applicant import (
    Applicant,
    ApplicationStatus,
    ExperienceLevel,
    Skill,
    TechRole,
)
from utils.logger import logger


# ─────────────────────────────────────────────────────
#  App Setup
# ─────────────────────────────────────────────────────

app = FastAPI(
    title="Autonomous Hiring Agent — Application Portal",
    description=(
        "Submit job applications, upload resumes, and track "
        "applicant status through the AI hiring pipeline."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow frontend / Postman to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────
#  In-memory store (replace with Supabase in production)
# ─────────────────────────────────────────────────────

_applicant_store: dict[str, Applicant] = {}


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _generate_id() -> str:
    return f"APP-{uuid.uuid4().hex[:8].upper()}"


def _parse_role_str(role: str) -> TechRole:
    role = role.strip().lower()
    mapping = {
        "sde": TechRole.SDE,
        "backend": TechRole.BACKEND,
        "frontend": TechRole.FRONTEND,
        "fullstack": TechRole.FULLSTACK,
        "data_engineer": TechRole.DATA_ENGINEER,
        "ml_engineer": TechRole.ML_ENGINEER,
        "data_scientist": TechRole.DATA_SCIENTIST,
        "ai_researcher": TechRole.AI_RESEARCHER,
        "devops": TechRole.DEVOPS,
    }
    return mapping.get(role, TechRole.SDE)


def _parse_exp_level(years: float) -> ExperienceLevel:
    if years == 0:
        return ExperienceLevel.FRESHER
    elif years <= 2:
        return ExperienceLevel.JUNIOR
    elif years <= 5:
        return ExperienceLevel.MID
    elif years <= 8:
        return ExperienceLevel.SENIOR
    return ExperienceLevel.LEAD


def _fix_url(url: Optional[str]) -> Optional[str]:
    if not url or not url.strip():
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


# ─────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Check if the API is running."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "total_applicants": len(_applicant_store),
    }


@app.post("/apply", status_code=status.HTTP_201_CREATED, tags=["Applications"])
async def submit_application(
    # Required fields
    full_name:          str         = Form(...),
    email:              str         = Form(...),
    role_applied:       str         = Form(..., description="sde | backend | frontend | ml_engineer | data_engineer | devops"),
    experience_years:   float       = Form(..., ge=0),

    # Optional fields
    phone:              Optional[str] = Form(default=None),
    location:           Optional[str] = Form(default=None),
    github_url:         Optional[str] = Form(default=None),
    portfolio_url:      Optional[str] = Form(default=None),
    linkedin_url:       Optional[str] = Form(default=None),
    cover_letter:       Optional[str] = Form(default=None),
    education:          Optional[str] = Form(default=None),
    skills_raw:         Optional[str] = Form(default=None, description="Comma-separated skills: Python,FastAPI,Docker"),

    # File upload
    resume:             Optional[UploadFile] = File(default=None),
):
    """
    Submit a single job application.

    Accepts form data + optional resume file (PDF or DOCX).
    Returns the created applicant profile with a unique ID.
    """
    logger.info(f"New application received | {full_name} | {email} | {role_applied}")

    # ── Validate email ────────────────────────
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid email address: {email}"
        )

    # ── Check for duplicate email ─────────────
    existing = [a for a in _applicant_store.values() if a.email == email.lower()]
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application already exists for email: {email}"
        )

    # ── Parse resume if uploaded ──────────────
    resume_text = None
    parsed_github = None
    parsed_skills = []

    if resume:
        allowed_types = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if resume.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Resume must be PDF or DOCX. Got: {resume.content_type}"
            )
        file_bytes = await resume.read()
        file_ext   = resume.filename.split(".")[-1] if resume.filename else "pdf"
        parse_result = resume_parser.parse(file_bytes, file_type=file_ext, filename=resume.filename)

        if parse_result.parse_success:
            resume_text    = parse_result.raw_text
            parsed_github  = parse_result.github_url
            parsed_skills  = parse_result.skills
            logger.info(f"Resume parsed | {full_name} | Skills found: {len(parsed_skills)}")

    # ── Parse skills ──────────────────────────
    skill_names = []
    if skills_raw:
        skill_names = [s.strip() for s in skills_raw.split(",") if s.strip()]
    # Merge with resume-parsed skills
    all_skills = list(set(skill_names + parsed_skills))
    skills = [Skill(name=s) for s in all_skills]

    # ── Build Applicant model ─────────────────
    exp_months = int(experience_years * 12)
    applicant = Applicant(
        id=_generate_id(),
        full_name=full_name.strip(),
        email=email.lower().strip(),
        phone=phone,
        location=location,
        role_applied=_parse_role_str(role_applied),
        experience_level=_parse_exp_level(experience_years),
        total_experience_months=exp_months,
        resume_text=resume_text,
        github_url=_fix_url(github_url or parsed_github),
        portfolio_url=_fix_url(portfolio_url),
        linkedin_url=_fix_url(linkedin_url),
        cover_letter=cover_letter,
        education=education,
        skills=skills,
        status=ApplicationStatus.PENDING,
        source="portal",
    )

    _applicant_store[applicant.id] = applicant

    logger.info(f"Application created | ID: {applicant.id} | {applicant.summary()}")

    return {
        "success":      True,
        "applicant_id": applicant.id,
        "message":      f"Application submitted successfully. Your ID is {applicant.id}",
        "applicant":    applicant.model_dump(mode="json"),
    }


@app.post("/apply/bulk", status_code=status.HTTP_201_CREATED, tags=["Applications"])
async def bulk_upload_applicants(
    file: UploadFile = File(..., description="CSV or Excel file with applicant data"),
):
    """
    Upload a CSV or Excel file containing multiple applicants.

    Required columns: name, email, role, experience
    Optional columns: phone, skills, github, portfolio, linkedin, cover_letter, education, location

    Skills should be pipe-separated: Python|FastAPI|Docker
    """
    allowed_types = {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File must be CSV or Excel. Got: {file.content_type}"
        )

    file_bytes = await file.read()
    file_ext   = file.filename.split(".")[-1] if file.filename else "csv"

    logger.info(f"Bulk upload received | {file.filename} | {len(file_bytes)} bytes")

    result = csv_ingestor.ingest(
        file_bytes=file_bytes,
        file_type=file_ext,
        source_label=f"bulk_{file.filename}",
    )

    # Store all successfully parsed applicants
    for applicant in result.applicants:
        # Skip duplicates
        existing_emails = {a.email for a in _applicant_store.values()}
        if applicant.email not in existing_emails:
            _applicant_store[applicant.id] = applicant

    logger.info(f"Bulk upload stored | {result.summary()}")

    return {
        "success":       True,
        "summary":       result.summary(),
        "total_rows":    result.total_rows,
        "imported":      result.success_count,
        "errors":        result.error_count,
        "skipped":       result.skipped,
        "error_details": result.errors,
    }


@app.get("/applicants", tags=["Applicants"])
async def list_applicants(
    status_filter: Optional[str] = None,
    role_filter:   Optional[str] = None,
    limit:         int           = 100,
    offset:        int           = 0,
):
    """
    List all applicants with optional filters.

    Filter by status: pending | shortlisted | accepted | rejected
    Filter by role:   sde | backend | ml_engineer | data_engineer etc.
    """
    applicants = list(_applicant_store.values())

    if status_filter:
        applicants = [a for a in applicants if a.status.value == status_filter]

    if role_filter:
        applicants = [a for a in applicants if a.role_applied.value == role_filter]

    total = len(applicants)
    paginated = applicants[offset: offset + limit]

    return {
        "total":      total,
        "limit":      limit,
        "offset":     offset,
        "applicants": [a.model_dump(mode="json") for a in paginated],
    }


@app.get("/applicants/{applicant_id}", tags=["Applicants"])
async def get_applicant(applicant_id: str):
    """Get a single applicant by their ID."""
    applicant = _applicant_store.get(applicant_id)
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Applicant not found: {applicant_id}"
        )
    return applicant.model_dump(mode="json")


@app.patch("/applicants/{applicant_id}/status", tags=["Applicants"])
async def update_applicant_status(
    applicant_id: str,
    new_status:   str = Form(..., description="pending | shortlisted | accepted | rejected | on_hold"),
):
    """Update the status of an applicant (called by the orchestrator agent)."""
    applicant = _applicant_store.get(applicant_id)
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Applicant not found: {applicant_id}"
        )

    try:
        applicant.status = ApplicationStatus(new_status)
        _applicant_store[applicant_id] = applicant
        logger.info(f"Status updated | {applicant_id} → {new_status}")
        return {"success": True, "applicant_id": applicant_id, "new_status": new_status}
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status: {new_status}"
        )


@app.get("/stats", tags=["System"])
async def get_stats():
    """Get hiring pipeline statistics."""
    all_applicants = list(_applicant_store.values())
    by_status = {}
    for s in ApplicationStatus:
        by_status[s.value] = sum(1 for a in all_applicants if a.status == s)

    by_role = {}
    for r in TechRole:
        count = sum(1 for a in all_applicants if a.role_applied == r)
        if count > 0:
            by_role[r.value] = count

    return {
        "total_applicants": len(all_applicants),
        "by_status":        by_status,
        "by_role":          by_role,
        "timestamp":        datetime.utcnow().isoformat(),
    }