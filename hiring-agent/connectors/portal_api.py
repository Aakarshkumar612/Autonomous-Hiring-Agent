"""
connectors/portal_api.py
═══════════════════════════════════════════════════════
FastAPI application intake portal.
Candidates apply directly through your own endpoints.

Endpoints:
  POST /apply                        → submit application (form data + resume)
  POST /apply/bulk                   → upload CSV/Excel of applicants
  GET  /applicants                   → list all applicants
  GET  /applicants/{id}              → get single applicant
  PATCH /applicants/{id}/status      → update applicant status
  GET  /stats                        → pipeline stats by status/role
  GET  /health                       → health check

  POST /interview/{applicant_id}/start   → start an interview session
  POST /interview/{session_id}/respond   → submit one response, get next question
  GET  /interview/{session_id}/status    → check current session state

Run locally:
  uv run uvicorn connectors.portal_api:app --reload --port 8000

Then open: http://localhost:8000/docs  (auto-generated Swagger UI)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agents.chat_agent import chat_agent
from connectors.csv_ingestor import csv_ingestor
from connectors.resume_parser import resume_parser
from connectors.supabase_mcp import supabase_store
from utils.document_validator import document_validator
from models.applicant import (
    Applicant,
    ApplicationStatus,
    ExperienceLevel,
    Skill,
    TechRole,
)
from utils.logger import logger

# Imported here for type annotations; the actual instance is created lazily
# to avoid reading GROQ_API_KEY before load_dotenv() runs.
from pipelines.interview_flow import InterviewPipeline

from pipelines.proctoring_pipeline import get_proctoring_pipeline

# DSA platform imports (lazy to avoid circular deps at import time)
from models.dsa_problem import (
    CheatEventType,
    DSAProblem,
    DSASession,
    ProblemDifficulty,
    ProblemType,
    ProgrammingLanguage,
    TestCase,
)
from models.subscription import Feature, TierType, TIER_CONFIGS
from models.interview_config import (
    RecruiterInterviewConfig,
    CreateInterviewConfigRequest,
    DSAQuestionConfig,
    SQLQuestionConfig,
    RoundConfig,
    UploadQuestionsResponse,
)


# ─────────────────────────────────────────────────────
#  App Setup
# ─────────────────────────────────────────────────────

@asynccontextmanager
async def _portal_lifespan(app: FastAPI):
    """
    On startup: warm the in-memory cache from Supabase so applicants submitted
    in previous sessions are available immediately without a DB hit per request.

    Why this matters: _applicant_store is a dict — fast O(1) reads, zero latency.
    Supabase is the persistent source of truth. We load once at startup so the
    rest of the server's life runs from the fast in-memory cache.
    """
    try:
        rows = await asyncio.to_thread(supabase_store.get_all_applicants)
        loaded = 0
        for row in rows or []:
            try:
                applicant = _applicant_from_row(row)
                _applicant_store[applicant.id] = applicant
                _email_index[applicant.email] = applicant.id   # keep index in sync
                loaded += 1
            except Exception as exc:
                logger.warning(f"PORTAL | Skipping malformed Supabase row: {exc}")
        logger.info(f"PORTAL | Loaded {loaded} applicants from Supabase on startup")
    except Exception as exc:
        logger.warning(f"PORTAL | Supabase warm-up failed (continuing with empty cache): {exc}")
    yield


app = FastAPI(
    title="Autonomous Hiring Agent — Application Portal",
    description=(
        "Submit job applications, upload resumes, and track "
        "applicant status through the AI hiring pipeline."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_portal_lifespan,
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
#  In-memory stores (replace with Supabase in production)
# ─────────────────────────────────────────────────────

_applicant_store: dict[str, Applicant] = {}

# Secondary index: email (lowercase) → applicant_id.
# Keeps duplicate checks O(1) instead of O(n) over the full store.
_email_index: dict[str, str] = {}

# Hard cap on the portal in-memory store — mirrors the PageIndex ceiling.
# Both stores use the same MAX_APPLICANTS env var so they stay in sync.
# Why a portal-side cap in addition to the PageIndex cap:
#   The portal store (_applicant_store) is separate from PageIndexStore.
#   Without its own cap it could grow unbounded, consuming memory and
#   slowing every list/filter O(n) scan indefinitely.
_PORTAL_CAP: int = int(os.getenv("MAX_APPLICANTS", "1000"))

# Near-cap threshold: log a warning when store reaches 90% capacity.
_NEAR_CAP_RATIO: float = 0.9

# Maps session_id → applicant_id so respond/status endpoints can
# look up the applicant without re-fetching from Supabase.
_session_store: dict[str, str] = {}

# Lazily initialised — avoids reading GROQ_API_KEY before load_dotenv().
_pipeline: Optional[InterviewPipeline] = None


def _get_pipeline() -> InterviewPipeline:
    """Return the shared InterviewPipeline instance, creating it on first call."""
    global _pipeline
    if _pipeline is None:
        _pipeline = InterviewPipeline()
        logger.info("InterviewPipeline initialised (lazy)")
    return _pipeline


# ─────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────

def _generate_id() -> str:
    return f"APP-{uuid.uuid4().hex[:8].upper()}"


def _applicant_from_row(row: dict) -> Applicant:
    """
    Reconstruct a minimal Applicant from a raw Supabase row.
    Used when warming the in-memory cache from Supabase on startup.
    """
    import json as _json
    skills_raw = row.get("skills") or []
    if isinstance(skills_raw, str):
        skills_raw = _json.loads(skills_raw)
    skills = [
        Skill(**s) if isinstance(s, dict) else Skill(name=str(s))
        for s in skills_raw
    ]
    return Applicant(
        id=row["id"],
        full_name=row["full_name"],
        email=row["email"],
        phone=row.get("phone"),
        location=row.get("location"),
        role_applied=TechRole(row.get("role_applied", "sde")),
        experience_level=ExperienceLevel(row.get("experience_level", "fresher")),
        total_experience_months=row.get("total_experience_months", 0),
        resume_text=row.get("resume_text"),
        github_url=row.get("github_url"),
        portfolio_url=row.get("portfolio_url"),
        linkedin_url=row.get("linkedin_url"),
        cover_letter=row.get("cover_letter"),
        education=row.get("education"),
        skills=skills,
        status=ApplicationStatus(row.get("status", "pending")),
        source=row.get("source", "portal"),
    )


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
    """Check if the API is running and report portal store capacity."""
    count     = len(_applicant_store)
    usage_pct = round(count / _PORTAL_CAP * 100, 1) if _PORTAL_CAP else 0.0
    return {
        "status":           "healthy",
        "timestamp":        datetime.utcnow().isoformat(),
        "total_applicants": count,
        "cap":              _PORTAL_CAP,
        "cap_usage_pct":    usage_pct,
        "is_near_cap":      count >= int(_PORTAL_CAP * _NEAR_CAP_RATIO),
        "is_full":          count >= _PORTAL_CAP,
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

    # ── Check for duplicate email — O(1) via index ───
    if email.lower() in _email_index:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application already exists for email: {email}"
        )

    # ── Enforce portal store cap ──────────────────────────────────────
    # Reject before doing any work (file read, LLM call) so we don't waste
    # tokens/time on an applicant we would have to discard anyway.
    current_count = len(_applicant_store)
    if current_count >= _PORTAL_CAP:
        logger.error(
            f"PORTAL | CAP REACHED ({_PORTAL_CAP}) | "
            f"Rejecting application from {email}. "
            f"Raise MAX_APPLICANTS env var to accept more applicants."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"The application portal has reached its capacity limit "
                f"({_PORTAL_CAP} applicants). No new applications are being accepted "
                f"at this time. Please try again later or contact support."
            ),
        )

    # Near-cap advisory — log once per submission when above 90%.
    if current_count >= int(_PORTAL_CAP * _NEAR_CAP_RATIO):
        logger.warning(
            f"PORTAL | NEAR CAP | {current_count}/{_PORTAL_CAP} applicants stored "
            f"({current_count / _PORTAL_CAP * 100:.0f}%). "
            f"Consider raising MAX_APPLICANTS."
        )

    # ── Parse resume if uploaded ──────────────
    resume_text = None
    parsed_github = None
    parsed_skills = []

    if resume:
        # Accepted MIME types — split into text-based and image-based buckets
        # so we can route to the right validation path.
        _TEXT_MIME_TYPES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            # Some browsers send .doc files with this MIME type
            "application/msword",
        }
        _IMAGE_MIME_TYPES = {
            "image/jpeg",
            "image/jpg",
            "image/png",
            "image/webp",
        }
        _ALL_ALLOWED = _TEXT_MIME_TYPES | _IMAGE_MIME_TYPES

        if resume.content_type not in _ALL_ALLOWED:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Unsupported file format: {resume.content_type}. "
                    "Accepted formats: PDF, DOCX, JPEG, PNG, WEBP."
                ),
            )

        file_bytes = await resume.read()

        # ── File size gate ────────────────────────────────────────────────
        # 10 MB hard limit. We read first, then check — UploadFile doesn't
        # expose a Content-Length header reliably across all clients.
        _MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB
        if len(file_bytes) > _MAX_FILE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File too large: {size_mb:.1f} MB. "
                    "Maximum allowed size is 10 MB."
                ),
            )

        file_ext   = resume.filename.rsplit(".", 1)[-1].lower() if resume.filename else ""

        # ── IMAGE PATH ────────────────────────────────────────────────────
        # For images the validator calls the Groq vision model which does
        # OCR + document classification in a SINGLE API call.
        # We reuse the extracted_text it returns instead of calling the
        # vision API a second time for parsing.
        if resume.content_type in _IMAGE_MIME_TYPES:
            validation = await document_validator.validate_image(
                file_bytes, resume.content_type
            )
            if not validation.is_valid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=validation.rejection_reason
                    or "The uploaded image is not a valid hiring document.",
                )
            # validation.extracted_text is the OCR output from llama-4-scout
            if validation.extracted_text:
                parse_result = resume_parser.parse_image(
                    extracted_text=validation.extracted_text,
                    filename=resume.filename or "",
                )
                if parse_result.parse_success:
                    resume_text   = parse_result.raw_text
                    parsed_github = parse_result.github_url
                    parsed_skills = parse_result.skills
                    logger.info(
                        f"Image resume processed | {full_name} | "
                        f"Doc type: {validation.document_type} | "
                        f"Skills found: {len(parsed_skills)}"
                    )

        # ── TEXT PATH (PDF / DOCX) ────────────────────────────────────────
        # Parse first (fast, local — no API call).
        # Then validate the extracted text (single LLM call, ~80ms).
        # Validation runs on the text we already have — no extra cost.
        else:
            parse_result = resume_parser.parse(
                file_bytes, file_type=file_ext, filename=resume.filename or ""
            )
            if parse_result.parse_success and parse_result.raw_text:
                validation = await document_validator.validate_text(
                    parse_result.raw_text
                )
                if not validation.is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=validation.rejection_reason
                        or "The uploaded file is not a valid hiring document.",
                    )
                resume_text   = parse_result.raw_text
                parsed_github = parse_result.github_url
                parsed_skills = parse_result.skills
                logger.info(
                    f"Resume parsed | {full_name} | "
                    f"Doc type: {validation.document_type} | "
                    f"Skills found: {len(parsed_skills)}"
                )

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
    _email_index[applicant.email] = applicant.id   # keep O(1) duplicate index in sync

    # Persist to Supabase so this application survives server restarts.
    # Fire-and-forget: a Supabase failure doesn't block the HTTP response —
    # the applicant is still in the in-memory store for this session.
    try:
        await asyncio.to_thread(supabase_store.save_applicant, applicant)
        logger.info(f"Application saved to Supabase | ID: {applicant.id}")
    except Exception as exc:
        logger.warning(f"Supabase save failed for {applicant.id} (in-memory only): {exc}")

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

    # ── Check remaining capacity before storing ───────────────────────
    # Reject the entire bulk if the store is already full.
    # If there is partial room, import what fits and report how many were capped.
    remaining_capacity = _PORTAL_CAP - len(_applicant_store)
    if remaining_capacity <= 0:
        logger.error(
            f"PORTAL | BULK CAP | Store full ({_PORTAL_CAP}). "
            f"Rejecting entire bulk upload of {result.success_count} applicants."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"The portal has reached its capacity limit ({_PORTAL_CAP} applicants). "
                f"No new applicants can be stored. Raise MAX_APPLICANTS to continue."
            ),
        )

    capped_count = 0
    if result.success_count > remaining_capacity:
        logger.warning(
            f"PORTAL | BULK PARTIAL CAP | Only {remaining_capacity} of "
            f"{result.success_count} applicants will be imported "
            f"(store limit: {_PORTAL_CAP})."
        )
        capped_count = result.success_count - remaining_capacity
        result.applicants = result.applicants[:remaining_capacity]

    # Store all successfully parsed applicants.
    # Use _email_index for O(1) duplicate checks — never rebuild the set per iteration.
    for applicant in result.applicants:
        if applicant.email not in _email_index:
            _applicant_store[applicant.id] = applicant
            _email_index[applicant.email] = applicant.id

    logger.info(f"Bulk upload stored | {result.summary()}")

    return {
        "success":       True,
        "summary":       result.summary(),
        "total_rows":    result.total_rows,
        "imported":      result.success_count,
        "errors":        result.error_count,
        "skipped":       result.skipped,
        "capped":        capped_count,
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


# ─────────────────────────────────────────────────────
#  Interview routes
# ─────────────────────────────────────────────────────

@app.post(
    "/interview/{applicant_id}/start",
    status_code=status.HTTP_201_CREATED,
    tags=["Interviews"],
    summary="Start an interview session for a shortlisted applicant",
)
async def start_interview(
    applicant_id: str,
    config_id: Optional[str] = None,   # query param: ?config_id=<uuid>
):
    """
    Begin a 3-round autonomous interview session.

    The applicant must already exist in the portal (submitted via /apply
    or /apply/bulk). Returns the session ID and the first interview question.

    Optional query param `config_id`: if a RecruiterInterviewConfig with this
    ID exists, the interviewer agent will ask the recruiter's custom questions
    (extracted from uploaded files + manually entered) verbatim before falling
    back to Groq-generated questions.

    The caller should present the question to the applicant and then post
    their answer to POST /interview/{session_id}/respond.
    """
    applicant = _applicant_store.get(applicant_id)
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Applicant not found: {applicant_id}",
        )

    # ── Resolve recruiter config (optional) ──────────────────────────
    custom_questions: list[str] = []
    config_name = None
    if config_id:
        cfg = _config_by_id.get(config_id)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Interview config not found: {config_id}",
            )
        config_name = cfg.name
        # Merge: extracted questions from file uploads come first,
        # then any manually entered custom questions per round
        # (behavioral, hr, managerial, technical), deduped.
        seen: set[str] = set()
        for q in cfg.extracted_questions:
            if q not in seen:
                custom_questions.append(q)
                seen.add(q)
        for round_cfg in [cfg.behavioral, cfg.hr, cfg.managerial, cfg.technical]:
            if round_cfg.enabled:
                for q in round_cfg.custom_questions:
                    if q not in seen:
                        custom_questions.append(q)
                        seen.add(q)

    logger.info(
        f"PORTAL | /interview/{applicant_id}/start | "
        f"{applicant.full_name} | Role: {applicant.role_applied.value} | "
        f"config={config_name or 'none'} | custom_questions={len(custom_questions)}"
    )

    try:
        pipeline = _get_pipeline()
        session_id, first_question = await pipeline.start_interview(
            applicant,
            custom_questions=custom_questions or None,
        )
        _session_store[session_id] = applicant_id

        logger.info(f"PORTAL | Session created | {session_id} → {applicant_id}")

        return {
            "session_id":       session_id,
            "applicant_id":     applicant_id,
            "applicant_name":   applicant.full_name,
            "first_question":   first_question,
            "round":            1,
            "round_type":       "screening",
            "total_rounds":     3,
            "config_id":        config_id,
            "config_name":      config_name,
            "custom_questions": len(custom_questions),
            "instructions": (
                "Post your response to "
                f"POST /interview/{session_id}/respond "
                "with field response_text."
            ),
        }

    except Exception as e:
        logger.error(
            f"PORTAL | /interview/{applicant_id}/start failed: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start interview session: {e}",
        )


@app.post(
    "/interview/{session_id}/respond",
    tags=["Interviews"],
    summary="Submit one applicant response and receive the next question",
)
async def respond_to_interview(
    session_id: str,
    response_text: str = Form(
        ...,
        min_length=1,
        description="The applicant's answer to the current interview question",
    ),
):
    """
    Process one applicant response turn.

    Runs AI detection on the response immediately, then asks the next question.
    When all rounds are complete, returns `is_complete: true` with the final
    hiring verdict from the Orchestrator Agent.

    Response fields:
    - `is_complete`  — True when the interview has finished
    - `next_question` — the next question to present (null when complete)
    - `ai_flagged`   — True if this response was flagged by the Detector Agent
    - `verdict`      — "accept" / "reject" / "hold"  (set when is_complete)
    - `confidence`   — orchestrator confidence 0.0–1.0 (set when is_complete)
    - `next_action`  — "send_offer" / "send_rejection" / etc. (set when is_complete)
    """
    applicant_id = _session_store.get(session_id)
    if not applicant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or expired: {session_id}",
        )

    applicant = _applicant_store.get(applicant_id)
    if not applicant:
        # Applicant was deleted after the session started — clean up
        _session_store.pop(session_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Applicant record missing for session: {session_id}",
        )

    logger.info(
        f"PORTAL | /interview/{session_id}/respond | "
        f"Applicant: {applicant_id} | "
        f"Response length: {len(response_text)} chars"
    )

    try:
        pipeline = _get_pipeline()
        result = await pipeline.process_interview_response(
            session_id=session_id,
            response_text=response_text,
            applicant=applicant,
            score=None,                               # scored separately via /run-ingest
            experience_years=applicant.total_experience_years(),
        )

    except Exception as e:
        logger.error(f"PORTAL | /interview/{session_id}/respond failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process response: {e}",
        )

    is_complete = result.get("is_complete", False)

    if is_complete:
        _session_store.pop(session_id, None)
        decision = result.get("decision")
        logger.info(
            f"PORTAL | Session {session_id} complete | "
            f"Verdict: {decision.verdict if decision else 'none'}"
        )
        return {
            "is_complete":   True,
            "next_question": None,
            "ai_flagged":    result.get("ai_flagged", False),
            "verdict":       decision.verdict      if decision else None,
            "confidence":    decision.confidence   if decision else None,
            "reason":        decision.reason       if decision else None,
            "next_action":   decision.next_action  if decision else None,
        }

    return {
        "is_complete":   False,
        "next_question": result.get("next_question"),
        "ai_flagged":    result.get("ai_flagged", False),
        "verdict":       None,
        "confidence":    None,
        "reason":        None,
        "next_action":   None,
    }


@app.get(
    "/interview/{session_id}/status",
    tags=["Interviews"],
    summary="Check the current state of an active interview session",
)
async def get_interview_status(session_id: str):
    """
    Poll the current state of an interview session.

    Useful for the frontend to show progress indicators:
    current round, questions asked, AI flags so far, etc.

    Returns 404 if the session has expired or never existed.
    """
    applicant_id = _session_store.get(session_id)
    if not applicant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found or expired: {session_id}",
        )

    pipeline = _get_pipeline()
    session = pipeline.session_store.get_session(session_id)
    if not session:
        # Session TTL expired inside the pipeline's store
        _session_store.pop(session_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session expired: {session_id}",
        )

    return {
        "session_id":       session_id,
        "applicant_id":     applicant_id,
        "applicant_name":   session.applicant_name,
        "role_applied":     session.role_applied,
        "status":           session.status.value,
        "current_round":    session.current_round,
        "total_rounds":     session.total_rounds,
        "interview_type":   session.interview_type.value,
        "questions_asked":  len(session.questions),
        "responses_given":  len(session.responses),
        "ai_flags":         session.total_ai_flags,
        "final_score":      session.final_score,
        "started_at":       session.started_at.isoformat() if session.started_at else None,
    }


# ─────────────────────────────────────────────────────
#  Chatbot routes
# ─────────────────────────────────────────────────────

@app.post(
    "/chat/stream",
    tags=["Chatbot"],
    summary="Send a message to the HireIQ assistant and stream the response",
)
async def chat_stream(
    session_id: str = Form(..., description="Client-generated UUID for the conversation session"),
    message:    str = Form(..., min_length=1, description="The user's message"),
):
    """
    Stream a chatbot response as Server-Sent Events (SSE).

    The client reads the response incrementally using fetch() + ReadableStream.
    Each event is: data: {"chunk": "..."}\n\n
    The stream ends with: data: [DONE]\n\n

    Session history is maintained server-side by session_id.
    The same session_id across multiple calls = continuous conversation.
    A new session_id = a fresh conversation with no memory of prior turns.
    """
    logger.info(f"PORTAL | /chat/stream | Session: {session_id[:8]} | Msg: {message[:60]}")
    return StreamingResponse(
        chat_agent.stream(message, session_id),
        media_type="text/event-stream",
        headers={
            # Prevent proxies and browsers from buffering the stream
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/chat",
    tags=["Chatbot"],
    summary="Send a message to the HireIQ assistant (non-streaming)",
)
async def chat(
    session_id: str = Form(...),
    message:    str = Form(..., min_length=1),
):
    """
    Non-streaming fallback. Returns the complete response in one JSON object.
    Use /chat/stream for the live-typing experience.
    """
    logger.info(f"PORTAL | /chat | Session: {session_id[:8]} | Msg: {message[:60]}")
    reply = await chat_agent.chat(message, session_id)
    return {"reply": reply, "session_id": session_id}


# ─────────────────────────────────────────────────────
#  Pipeline Settings routes
# ─────────────────────────────────────────────────────

# In-memory pipeline config — initialised from env, mutated by PATCH endpoint.
# A server restart resets to env defaults (acceptable for an MVP).
_pipeline_config: dict = {
    "shortlist_threshold":    float(os.getenv("SHORTLIST_THRESHOLD", "30")),
    "auto_reject_threshold":  float(os.getenv("AUTO_REJECT_THRESHOLD", "20")),
    "interview_rounds":       int(os.getenv("INTERVIEW_ROUNDS", "3")),
    "ai_detection_threshold": float(os.getenv("AI_DETECTION_THRESHOLD", "0.75")),
    "max_applicants":         int(os.getenv("MAX_APPLICANTS", "1000")),
}


@app.get(
    "/settings/pipeline",
    tags=["Settings"],
    summary="Get current pipeline configuration",
)
async def get_pipeline_settings():
    """Return the active pipeline configuration values."""
    return _pipeline_config


@app.patch(
    "/settings/pipeline",
    tags=["Settings"],
    summary="Update pipeline configuration",
)
async def update_pipeline_settings(
    shortlist_threshold:    Optional[float] = Form(default=None, ge=0, le=100),
    auto_reject_threshold:  Optional[float] = Form(default=None, ge=0, le=100),
    interview_rounds:       Optional[int]   = Form(default=None, ge=1, le=5),
    ai_detection_threshold: Optional[float] = Form(default=None, ge=0.0, le=1.0),
    max_applicants:         Optional[int]   = Form(default=None, ge=1, le=10000),
):
    """
    Partial update of pipeline configuration.
    Only supplied fields are changed; omitted fields keep their current value.
    """
    if shortlist_threshold    is not None: _pipeline_config["shortlist_threshold"]    = shortlist_threshold
    if auto_reject_threshold  is not None: _pipeline_config["auto_reject_threshold"]  = auto_reject_threshold
    if interview_rounds       is not None: _pipeline_config["interview_rounds"]        = interview_rounds
    if ai_detection_threshold is not None: _pipeline_config["ai_detection_threshold"] = ai_detection_threshold
    if max_applicants         is not None: _pipeline_config["max_applicants"]          = max_applicants

    logger.info(f"PORTAL | /settings/pipeline | Updated: {_pipeline_config}")
    return {"success": True, "config": _pipeline_config}


# ═══════════════════════════════════════════════════════
#  DSA PLATFORM — Feature Gate + Code Execution Routes
# ═══════════════════════════════════════════════════════

# Lazy singletons for DSA subsystem
_dsa_pipeline   = None
_feature_gate   = None
_dsa_sessions:  dict[str, DSASession] = {}      # session_id → DSASession (in-memory)
_dsa_problems:  dict[str, DSAProblem] = {}      # problem_id → DSAProblem (in-memory seed)
_proctor_ws_connections: dict[str, WebSocket] = {}  # session_id → live WebSocket


def _get_feature_gate():
    global _feature_gate
    if _feature_gate is None:
        from connectors.feature_gate import FeatureGate
        _feature_gate = FeatureGate()
    return _feature_gate


def _get_dsa_pipeline():
    global _dsa_pipeline
    if _dsa_pipeline is None:
        from pipelines.dsa_interview_flow import DSAInterviewPipeline
        _dsa_pipeline = DSAInterviewPipeline(feature_gate=_get_feature_gate())
    return _dsa_pipeline


def _seed_demo_problems():
    """Populate a small in-memory problem bank for demo / dev use."""
    if _dsa_problems:
        return
    _dsa_problems["demo_two_sum"] = DSAProblem(
        id="demo_two_sum",
        title="Two Sum",
        slug="two-sum",
        difficulty=ProblemDifficulty.EASY,
        problem_type=ProblemType.DSA,
        description=(
            "Given an array of integers `nums` and an integer `target`, return **indices** "
            "of the two numbers such that they add up to `target`.\n\n"
            "You may assume exactly one solution exists."
        ),
        constraints="2 ≤ nums.length ≤ 10⁴\n-10⁹ ≤ nums[i] ≤ 10⁹",
        examples=[
            TestCase(
                input="[2,7,11,15]\n9",
                expected_output="0 1",
                is_sample=True,
                explanation="nums[0] + nums[1] = 2 + 7 = 9",
            ),
        ],
        hidden_tests=[
            TestCase(input="[3,2,4]\n6",     expected_output="1 2"),
            TestCase(input="[3,3]\n6",        expected_output="0 1"),
        ],
        tags=["Array", "Hash Table"],
        time_limit_ms=5000,
        memory_limit_mb=256,
    )
    _dsa_problems["demo_select_dept"] = DSAProblem(
        id="demo_select_dept",
        title="Employees by Department",
        slug="employees-by-department",
        difficulty=ProblemDifficulty.EASY,
        problem_type=ProblemType.SQL,
        description=(
            "Write a SQL query to return all employees in the **Engineering** department, "
            "ordered by `name` ascending."
        ),
        schema_sql=(
            "CREATE TABLE employees (id INTEGER, name TEXT, department TEXT, salary INTEGER);\n"
            "INSERT INTO employees VALUES (1,'Alice','Engineering',120000);\n"
            "INSERT INTO employees VALUES (2,'Bob','Marketing',90000);\n"
            "INSERT INTO employees VALUES (3,'Carol','Engineering',115000);\n"
        ),
        examples=[
            TestCase(
                input="SELECT query on employees",
                expected_output="1|Alice|Engineering|120000\n3|Carol|Engineering|115000",
                is_sample=True,
            ),
        ],
        hidden_tests=[
            TestCase(
                input="",
                expected_output="1|Alice|Engineering|120000\n3|Carol|Engineering|115000",
            ),
        ],
        tags=["SQL", "SELECT", "ORDER BY"],
    )


# ── GET /dsa/problems ─────────────────────────────────

@app.get("/dsa/problems", tags=["DSA Platform"], summary="List available DSA/SQL problems")
async def list_dsa_problems():
    """Return all problems in the bank (id, title, difficulty, type, tags)."""
    _seed_demo_problems()
    problems = [
        {
            "id":           p.id,
            "title":        p.title,
            "slug":         p.slug,
            "difficulty":   p.difficulty.value,
            "problem_type": p.problem_type.value,
            "tags":         p.tags,
        }
        for p in _dsa_problems.values()
    ]
    return {"success": True, "data": problems}


# ── GET /dsa/problems/{problem_id} ───────────────────

@app.get("/dsa/problems/{problem_id}", tags=["DSA Platform"], summary="Get a DSA/SQL problem")
async def get_dsa_problem(problem_id: str):
    """Return full problem details (description, examples, starter code)."""
    _seed_demo_problems()
    prob = _dsa_problems.get(problem_id)
    if not prob:
        raise HTTPException(status_code=404, detail=f"Problem '{problem_id}' not found")
    # Return only sample tests (not hidden)
    result = prob.dict()
    result["hidden_tests"] = []   # never expose to candidate
    return {"success": True, "data": result}


# ── POST /dsa/sessions ────────────────────────────────

@app.post("/dsa/sessions", tags=["DSA Platform"], summary="Start a DSA interview session")
async def start_dsa_session(
    recruiter_id: str  = Form(...),
    applicant_id: str  = Form(...),
    problem_id:   str  = Form(...),
    language:     str  = Form(default="python3"),
    duration_min: int  = Form(default=90, ge=15, le=240),
):
    """
    Gate-check subscription tier, then create a DSA session.
    Returns session_id and problem details.
    """
    _seed_demo_problems()
    prob = _dsa_problems.get(problem_id)
    if not prob:
        raise HTTPException(status_code=404, detail=f"Problem '{problem_id}' not found")

    try:
        lang = ProgrammingLanguage(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown language: {language}")

    session, gate = await _get_dsa_pipeline().start(
        recruiter_id=recruiter_id,
        applicant_id=applicant_id,
        problem=prob,
        duration_min=duration_min,
    )

    if not gate.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code":    "DSA_GATE_001",
                "message": gate.reason,
                "tier":    gate.tier.value,
            },
        )

    session.language = lang
    _dsa_sessions[session.id] = session

    # Register with silent proctoring pipeline
    get_proctoring_pipeline().start_session(
        session_id=session.id,
        applicant_id=applicant_id,
        recruiter_id=recruiter_id,
        problem_id=prob.id,
        problem_title=prob.title,
    )

    return {
        "success":    True,
        "data": {
            "session_id":  session.id,
            "problem_id":  prob.id,
            "problem_title": prob.title,
            "language":    lang.value,
            "duration_min": duration_min,
            "platform_url": f"/dsa/platform?session={session.id}&applicant={applicant_id}&recruiter={recruiter_id}&problem={problem_id}",
            "tier":        gate.tier.value,
            "remaining":   gate.remaining,
        },
    }


# ── POST /dsa/run ─────────────────────────────────────

@app.post("/dsa/run", tags=["DSA Platform"], summary="Run code against sample test cases only")
async def run_code(
    session_id:  str  = Form(...),
    problem_id:  str  = Form(...),
    language:    str  = Form(...),
    source_code: str  = Form(...),
    sample_only: bool = Form(default=True),
):
    """
    Execute code/SQL against sample test cases only (no hidden tests revealed).
    Used by the ▶ Run button in the platform UI.
    """
    _seed_demo_problems()
    prob = _dsa_problems.get(problem_id)
    if not prob:
        raise HTTPException(status_code=404, detail="Problem not found")

    session = _dsa_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        lang = ProgrammingLanguage(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown language: {language}")

    session.language = lang

    # Build a temporary DSASession-like object for the pipeline call
    from models.dsa_problem import CodeSubmission as _CS, DSASession as _DS
    tmp_session = _DS(
        id=session_id,
        applicant_id=session.applicant_id,
        recruiter_id=session.recruiter_id,
        problem_id=problem_id,
        language=lang,
    )

    # Only run sample (visible) tests for the ▶ Run action
    import copy
    run_prob = copy.copy(prob)
    run_prob.hidden_tests = []

    sub = await _get_dsa_pipeline().submit_code(tmp_session, run_prob, source_code)

    return {
        "success": True,
        "data": {
            "status":       sub.status.value,
            "passed_count": sub.passed_count,
            "total_count":  sub.total_count,
            "score_pct":    sub.score_pct,
            "runtime_ms":   sub.runtime_ms,
            "test_results": [r.dict() for r in sub.test_results],
        },
    }


# ── POST /dsa/sessions/{id}/submit ───────────────────

@app.post(
    "/dsa/sessions/{session_id}/submit",
    tags=["DSA Platform"],
    summary="Submit code — run all hidden tests",
)
async def submit_code(
    session_id:  str,
    problem_id:  str  = Form(...),
    language:    str  = Form(...),
    source_code: str  = Form(...),
):
    """
    Submit code/SQL against ALL test cases (including hidden ones).
    Scores the submission and records it in the session.
    """
    _seed_demo_problems()
    session = _dsa_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prob = _dsa_problems.get(problem_id or session.problem_id)
    if not prob:
        raise HTTPException(status_code=404, detail="Problem not found")

    try:
        lang = ProgrammingLanguage(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown language: {language}")

    session.language = lang
    sub = await _get_dsa_pipeline().submit_code(session, prob, source_code)
    session.submissions.append(sub.id)
    if sub.score_pct > session.best_score_pct:
        session.best_score_pct = sub.score_pct

    # Notify silent proctoring pipeline of this submission
    get_proctoring_pipeline().record_submission(
        session_id=session_id,
        score_pct=sub.score_pct,
    )

    return {
        "success": True,
        "data": {
            "submission_id": sub.id,
            "status":        sub.status.value,
            "passed_count":  sub.passed_count,
            "total_count":   sub.total_count,
            "score_pct":     sub.score_pct,
            "runtime_ms":    sub.runtime_ms,
            "test_results":  [
                {
                    "test_index":      r.test_index,
                    "passed":          r.passed,
                    "runtime_ms":      r.runtime_ms,
                    "memory_kb":       r.memory_kb,
                    # Never reveal expected output for hidden tests
                    "actual_output":   r.actual_output if r.passed else "(hidden)",
                    "expected_output": r.expected_output if r.passed else "(hidden)",
                    "error":           r.error,
                }
                for r in sub.test_results
            ],
        },
    }


# ── POST /dsa/sessions/{id}/cheat-event ──────────────

@app.post(
    "/dsa/sessions/{session_id}/cheat-event",
    tags=["DSA Platform"],
    summary="Report a proctoring event (tab switch, paste, etc.)",
)
async def report_cheat_event(
    session_id: str,
    event_type: str = Form(...),
    detail:     str = Form(default=""),
):
    """
    Frontend reports suspicious activity; proctor agent applies strike system.
    Returns warning text (for TTS) and kicked flag.
    """
    session = _dsa_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        evt = CheatEventType(event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {event_type}")

    prob = _dsa_problems.get(session.problem_id, None)
    prob_title = prob.title if prob else ""

    state, warning_text, kicked = await _get_dsa_pipeline().handle_cheat_event(
        session=session,
        event_type=evt,
        detail=detail,
        problem_title=prob_title,
    )

    if kicked:
        session.status = __import__('models.dsa_problem', fromlist=['DSASessionStatus']).DSASessionStatus.KICKED

    # Forward event to silent proctoring pipeline
    get_proctoring_pipeline().record_events(
        session_id=session_id,
        raw_events=[{
            "event_type": event_type,
            "timestamp":  datetime.utcnow().isoformat(),
            "detail":     detail,
        }],
    )

    # Push warning over WebSocket if candidate is connected
    ws = _proctor_ws_connections.get(session_id)
    if ws and warning_text:
        try:
            await ws.send_json({"type": "warning", "text": warning_text, "strike": state.strike_count})
        except Exception:
            pass

    logger.info(
        f"PORTAL | /dsa/sessions/{session_id}/cheat-event | "
        f"{event_type} | strike={state.strike_count} | kicked={kicked}"
    )

    return {
        "success": True,
        "data": {
            "strike":       state.strike_count,
            "strike_level": state.strike_level.value,
            "warning_text": warning_text,
            "kicked":       kicked,
        },
    }


# ── GET /dsa/sessions/{id} ────────────────────────────

@app.get(
    "/dsa/sessions/{session_id}",
    tags=["DSA Platform"],
    summary="Get DSA session status",
)
async def get_dsa_session(session_id: str):
    session = _dsa_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "success": True,
        "data": {
            "session_id":    session.id,
            "status":        session.status.value,
            "strike_count":  session.strike_count,
            "strike_level":  session.strike_level.value,
            "best_score_pct": session.best_score_pct,
            "language":      session.language.value,
            "submissions":   session.submissions,
            "started_at":    session.started_at.isoformat(),
            "ended_at":      session.ended_at.isoformat() if session.ended_at else None,
        },
    }


# ── DELETE /dsa/sessions/{id} (end session) ───────────

@app.delete(
    "/dsa/sessions/{session_id}",
    tags=["DSA Platform"],
    summary="End a DSA session",
)
async def end_dsa_session(session_id: str):
    session = _dsa_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await _get_dsa_pipeline().end(session, [])

    # Generate proctoring report in a thread (Groq call is sync/blocking)
    pp = get_proctoring_pipeline()
    await asyncio.to_thread(pp.generate_report, session_id)

    return {
        "success": True,
        "data": {
            "session_id":    session.id,
            "status":        session.status.value,
            "best_score_pct": session.best_score_pct,
        },
    }


# ── WS /dsa/proctor-ws/{session_id} ──────────────────

@app.websocket("/dsa/proctor-ws/{session_id}")
async def proctor_ws(websocket: WebSocket, session_id: str):
    """
    Persistent WebSocket between the DSA platform and the proctoring backend.
    - Server → Client: warning, kicked, avatar_speech messages
    - Client → Server: cheat_event messages (mirrors the HTTP fallback)
    """
    session = _dsa_sessions.get(session_id)
    if not session:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    _proctor_ws_connections[session_id] = websocket
    logger.info(f"PORTAL | proctor-ws connected | {session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "cheat_event":
                evt_str = data.get("event_type", "")
                detail  = data.get("detail", "")
                try:
                    evt = CheatEventType(evt_str)
                except ValueError:
                    continue

                prob       = _dsa_problems.get(session.problem_id)
                prob_title = prob.title if prob else ""

                _, warning_text, kicked = await _get_dsa_pipeline().handle_cheat_event(
                    session=session,
                    event_type=evt,
                    detail=detail,
                    problem_title=prob_title,
                )

                get_proctoring_pipeline().record_events(
                    session_id=session_id,
                    raw_events=[{
                        "event_type": evt_str,
                        "timestamp":  datetime.utcnow().isoformat(),
                        "detail":     detail,
                    }],
                )

                if kicked:
                    await websocket.send_json({"type": "kicked", "text": warning_text or "Session ended."})
                    break
                elif warning_text:
                    await websocket.send_json({"type": "warning", "text": warning_text})

    except WebSocketDisconnect:
        pass
    finally:
        _proctor_ws_connections.pop(session_id, None)
        logger.info(f"PORTAL | proctor-ws disconnected | {session_id}")


# ── GET /proctor/dashboard/{recruiter_id}/data ────────

@app.get(
    "/proctor/dashboard/{recruiter_id}/data",
    tags=["Proctoring"],
    summary="Aggregated proctoring data for recruiter dashboard",
)
async def get_proctor_dashboard_data(recruiter_id: str):
    """
    Returns ranked candidate list + per-session risk summaries for the
    recruiter's proctor dashboard.
    """
    summary = get_proctoring_pipeline().get_recruiter_summary(recruiter_id)
    return {"success": True, "data": summary}


# ── GET /subscription/{recruiter_id} ─────────────────

@app.get(
    "/subscription/{recruiter_id}",
    tags=["Subscription"],
    summary="Get subscription status and feature limits",
)
async def get_subscription(recruiter_id: str):
    """
    Returns current tier, enabled features, daily limits,
    today's usage, and per-recruiter feature toggles.
    """
    status_obj = await _get_feature_gate().get_status(recruiter_id)
    return {"success": True, "data": status_obj.dict()}


# ── GET /pricing ──────────────────────────────────────

@app.get("/pricing", tags=["Subscription"], summary="Return all subscription tiers and pricing")
async def get_pricing():
    """Returns tier display info for the pricing page."""
    tiers = []
    for tier, cfg in TIER_CONFIGS.items():
        tiers.append({
            "tier":          cfg.tier.value,
            "display_name":  cfg.display_name,
            "price_monthly": cfg.price_monthly,
            "description":   cfg.description,
            "features": {
                feat: getattr(cfg.features, feat, False)
                for feat in vars(cfg.features)
                if not feat.startswith("_")
            },
            "limits": {
                feat: getattr(cfg.limits, feat, 0)
                for feat in vars(cfg.limits)
                if not feat.startswith("_") and feat != "get"
            },
            "contact":  "aakarshkumar241@gmail.com" if tier == TierType.ENTERPRISE else None,
        })
    return {"success": True, "data": tiers}


# ── GET/PATCH /settings/features ─────────────────────

@app.get(
    "/settings/features/{recruiter_id}",
    tags=["Settings"],
    summary="Get per-recruiter feature toggles (MAX/ENTERPRISE only)",
)
async def get_feature_toggles(recruiter_id: str):
    status_obj = await _get_feature_gate().get_status(recruiter_id)
    return {"success": True, "data": {"toggles": status_obj.toggles, "tier": status_obj.tier.value}}


@app.patch(
    "/settings/features/{recruiter_id}",
    tags=["Settings"],
    summary="Toggle a feature on/off (MAX/ENTERPRISE only)",
)
async def set_feature_toggle(
    recruiter_id: str,
    feature:      str  = Form(...),
    enabled:      bool = Form(...),
    note:         str  = Form(default=""),
):
    """
    Enable or disable a feature for this recruiter account.
    Only works on MAX or ENTERPRISE tier — ignored on FREE/PRO.
    """
    try:
        feat = Feature(feature)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    ok = await _get_feature_gate().set_toggle(recruiter_id, feat, enabled, note)
    if not ok:
        raise HTTPException(
            status_code=403,
            detail="Feature toggles require MAX or ENTERPRISE plan.",
        )
    return {"success": True, "data": {"feature": feature, "enabled": enabled}}


# ─────────────────────────────────────────────────────
#  Recruiter Interview Configuration
# ─────────────────────────────────────────────────────
#
#  In-memory store: { recruiter_id: { config_id: RecruiterInterviewConfig } }
#  Persisted to Supabase in a future migration; fast dict for now.
#
_interview_configs: dict[str, dict[str, RecruiterInterviewConfig]] = {}
# Flat index — lets interview endpoints look up a config by ID alone
_config_by_id: dict[str, RecruiterInterviewConfig] = {}

_MAX_FILE_BYTES = 5 * 1024 * 1024   # 5 MB hard limit


def _configs_for(recruiter_id: str) -> dict[str, RecruiterInterviewConfig]:
    if recruiter_id not in _interview_configs:
        _interview_configs[recruiter_id] = {}
    return _interview_configs[recruiter_id]


# ── POST /recruiter/{id}/interview-config ─────────────

@app.post(
    "/recruiter/{recruiter_id}/interview-config",
    tags=["Recruiter Config"],
    summary="Create or update an interview configuration",
)
async def create_interview_config(
    recruiter_id: str,
    body: CreateInterviewConfigRequest,
):
    """
    Create a named interview configuration for this recruiter.
    Specify DSA difficulty breakdown, SQL count, and round settings.
    Each call with the same name overwrites the existing config for that name.
    """
    configs = _configs_for(recruiter_id)

    # Check for existing config with same name (upsert semantics)
    existing = next(
        (c for c in configs.values() if c.name == body.name), None
    )
    if existing:
        config_id = existing.config_id
    else:
        config_id = str(uuid.uuid4())

    now = datetime.utcnow()
    config = RecruiterInterviewConfig(
        config_id=config_id,
        recruiter_id=recruiter_id,
        name=body.name,
        dsa=body.dsa or DSAQuestionConfig(),
        sql=body.sql or SQLQuestionConfig(),
        behavioral=body.behavioral or RoundConfig(),
        hr=body.hr or RoundConfig(),
        managerial=body.managerial or RoundConfig(),
        technical=body.technical or RoundConfig(),
        extracted_questions=existing.extracted_questions if existing else [],
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    configs[config_id] = config
    _config_by_id[config_id] = config   # keep flat index in sync

    logger.info(
        f"RECRUITER-CONFIG | {recruiter_id} | "
        f"{'updated' if existing else 'created'} | config_id={config_id} | name={body.name}"
    )
    return {"success": True, "data": _serialize_config(config)}


# ── GET /recruiter/{id}/interview-configs ─────────────

@app.get(
    "/recruiter/{recruiter_id}/interview-configs",
    tags=["Recruiter Config"],
    summary="List all interview configurations for a recruiter",
)
async def list_interview_configs(recruiter_id: str):
    configs = _configs_for(recruiter_id)
    return {
        "success": True,
        "data": [_serialize_config(c) for c in configs.values()],
    }


# ── GET /recruiter/{id}/interview-config/{config_id} ──

@app.get(
    "/recruiter/{recruiter_id}/interview-config/{config_id}",
    tags=["Recruiter Config"],
    summary="Get a single interview configuration",
)
async def get_interview_config(recruiter_id: str, config_id: str):
    configs = _configs_for(recruiter_id)
    if config_id not in configs:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"success": True, "data": _serialize_config(configs[config_id])}


# ── DELETE /recruiter/{id}/interview-config/{config_id}

@app.delete(
    "/recruiter/{recruiter_id}/interview-config/{config_id}",
    tags=["Recruiter Config"],
    summary="Delete an interview configuration",
)
async def delete_interview_config(recruiter_id: str, config_id: str):
    configs = _configs_for(recruiter_id)
    if config_id not in configs:
        raise HTTPException(status_code=404, detail="Config not found")
    del configs[config_id]
    _config_by_id.pop(config_id, None)   # keep flat index in sync
    logger.info(f"RECRUITER-CONFIG | {recruiter_id} | deleted | config_id={config_id}")
    return {"success": True, "data": {"deleted": config_id}}


# ── POST /recruiter/{id}/interview-config/{config_id}/upload-questions

@app.post(
    "/recruiter/{recruiter_id}/interview-config/{config_id}/upload-questions",
    tags=["Recruiter Config"],
    summary="Upload a file to extract interview questions (PDF/DOCX/image/TXT, max 5 MB)",
)
async def upload_interview_questions(
    recruiter_id: str,
    config_id:    str,
    file:         UploadFile = File(...),
):
    """
    Accepts: PDF, DOCX, plain-text, or image (JPEG/PNG/WEBP/GIF).
    Parses the file, sends text to Groq, extracts a list of interview
    questions, and appends them to the config's extracted_questions.

    The interviewer agent will read these questions during the session.
    """
    configs = _configs_for(recruiter_id)
    if config_id not in configs:
        raise HTTPException(status_code=404, detail="Config not found")

    config = configs[config_id]

    # ── 1. Size guard ──────────────────────────────────
    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large — maximum size is 5 MB (got {len(content) / 1024 / 1024:.1f} MB)",
        )

    filename  = file.filename or "upload"
    mime_type = file.content_type or ""

    # ── 2. Detect file type and extract raw text ───────
    try:
        raw_text, file_type = await asyncio.to_thread(
            _extract_text_from_file, content, filename, mime_type
        )
    except Exception as exc:
        logger.warning(f"RECRUITER-CONFIG | file extraction failed: {exc}")
        raise HTTPException(status_code=422, detail=f"Could not read file: {exc}")

    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="File appears to be empty or unreadable")

    # ── 3. Extract questions via Groq ──────────────────
    try:
        questions = await _extract_questions_with_groq(raw_text)
    except Exception as exc:
        logger.warning(f"RECRUITER-CONFIG | Groq question extraction failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Question extraction failed: {exc}")

    # ── 4. Append to config ────────────────────────────
    config.extracted_questions.extend(questions)
    config.updated_at = datetime.utcnow()

    logger.info(
        f"RECRUITER-CONFIG | {recruiter_id} | upload | config_id={config_id} | "
        f"file={filename} | type={file_type} | extracted={len(questions)}"
    )

    return {
        "success": True,
        "data": UploadQuestionsResponse(
            config_id=config_id,
            filename=filename,
            file_type=file_type,
            extracted_count=len(questions),
            total_questions=len(config.extracted_questions),
            extracted_questions=questions,
        ).model_dump(),
    }


# ─────────────────────────────────────────────────────
#  File parsing helpers (run in thread via asyncio.to_thread)
# ─────────────────────────────────────────────────────

def _extract_text_from_file(
    content: bytes, filename: str, mime_type: str
) -> tuple[str, str]:
    """
    Parse file bytes → (raw_text, file_type_label).
    Runs synchronously — call via asyncio.to_thread.
    """
    lower = filename.lower()

    # PDF
    if mime_type == "application/pdf" or lower.endswith(".pdf"):
        return _parse_pdf(content), "pdf"

    # DOCX
    if (
        mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or lower.endswith(".docx")
    ):
        return _parse_docx(content), "docx"

    # Plain text
    if mime_type.startswith("text/") or lower.endswith(".txt") or lower.endswith(".md"):
        return content.decode("utf-8", errors="replace"), "txt"

    # Image — return sentinel so async caller uses Groq vision
    if mime_type.startswith("image/") or any(
        lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ):
        # Return raw bytes encoded as base64 with a sentinel prefix
        import base64
        b64 = base64.b64encode(content).decode()
        return f"__IMAGE_B64__{mime_type}|{b64}", "image"

    # Fallback: try UTF-8 decode
    try:
        return content.decode("utf-8", errors="replace"), "txt"
    except Exception:
        raise ValueError(f"Unsupported file type: {mime_type or lower}")


def _parse_pdf(content: bytes) -> str:
    """Extract text from PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
        import io
        doc = fitz.open(stream=io.BytesIO(content), filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        raise RuntimeError("PyMuPDF not installed — run: pip install pymupdf")


def _parse_docx(content: bytes) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        raise RuntimeError("python-docx not installed — run: pip install python-docx")


async def _extract_questions_with_groq(raw_text: str) -> list[str]:
    """
    Send extracted text (or base64 image) to Groq, get back a list
    of interview questions. Returns a de-duplicated list of strings.
    """
    from groq import AsyncGroq

    client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
    model  = os.getenv("GROQ_SCORER", "llama-3.3-70b-versatile")

    # Image path — use vision model
    if raw_text.startswith("__IMAGE_B64__"):
        _, rest       = raw_text.split("__IMAGE_B64__", 1)
        mime, b64_data = rest.split("|", 1)
        vision_model  = os.getenv("GROQ_VISION", "meta-llama/llama-4-scout-17b-16e-instruct")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "This image contains interview questions. "
                            "Extract every question you see, exactly as written. "
                            "Return ONLY a JSON array of strings — no explanation, "
                            "no numbering, no markdown fences.\n"
                            'Example: ["What is a binary tree?", "Explain ACID."]'
                        ),
                    },
                ],
            }
        ]
        resp = await asyncio.wait_for(
            client.chat.completions.create(model=vision_model, messages=messages, max_tokens=2048),
            timeout=20.0,
        )
    else:
        # Text path — truncate to 6000 chars to stay within context
        truncated = raw_text[:6000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a question extractor. Given text from a document, "
                    "identify every interview question present. "
                    "Return ONLY a JSON array of question strings — no explanation, "
                    "no numbering, no markdown.\n"
                    'Example: ["Tell me about yourself.", "What is O(n log n)?"]'
                ),
            },
            {"role": "user", "content": truncated},
        ]
        resp = await asyncio.wait_for(
            client.chat.completions.create(model=model, messages=messages, max_tokens=2048),
            timeout=15.0,
        )

    # Parse JSON array from response
    import re as _re
    answer = resp.choices[0].message.content.strip()
    # Strip markdown fences if present
    answer = _re.sub(r"```(?:json)?\s*|\s*```", "", answer).strip()

    try:
        import ast as _ast
        questions = _ast.literal_eval(answer) if answer.startswith("[") else []
    except Exception:
        # Fallback: split by newlines and filter non-empty
        questions = [line.strip().lstrip("0123456789.-) ") for line in answer.splitlines() if line.strip()]

    # De-duplicate while preserving order
    seen: set[str] = set()
    unique = []
    for q in questions:
        if isinstance(q, str) and q.strip() and q not in seen:
            seen.add(q)
            unique.append(q.strip())

    return unique


# ─────────────────────────────────────────────────────
#  Serialisation helper
# ─────────────────────────────────────────────────────

def _serialize_config(c: RecruiterInterviewConfig) -> dict:
    return {
        "config_id":   c.config_id,
        "recruiter_id": c.recruiter_id,
        "name":        c.name,
        "dsa": {
            "total_count": c.dsa.total_count,
            "difficulties": {
                "easy":   c.dsa.difficulties.easy,
                "medium": c.dsa.difficulties.medium,
                "hard":   c.dsa.difficulties.hard,
            },
            "pinned_problem_ids": c.dsa.pinned_problem_ids,
        },
        "sql": {
            "count":      c.sql.count,
            "difficulty": c.sql.difficulty,
            "pinned_problem_ids": c.sql.pinned_problem_ids,
        },
        "behavioral": {
            "enabled":         c.behavioral.enabled,
            "question_count":  c.behavioral.question_count,
            "custom_questions": c.behavioral.custom_questions,
        },
        "hr": {
            "enabled":         c.hr.enabled,
            "question_count":  c.hr.question_count,
            "custom_questions": c.hr.custom_questions,
        },
        "managerial": {
            "enabled":         c.managerial.enabled,
            "question_count":  c.managerial.question_count,
            "custom_questions": c.managerial.custom_questions,
        },
        "technical": {
            "enabled":         c.technical.enabled,
            "question_count":  c.technical.question_count,
            "custom_questions": c.technical.custom_questions,
        },
        "extracted_questions": c.extracted_questions,
        "total_extracted":     len(c.extracted_questions),
        "created_at":          c.created_at.isoformat(),
        "updated_at":          c.updated_at.isoformat(),
    }