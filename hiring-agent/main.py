"""
main.py
═══════════════════════════════════════════════════════
Autonomous Hiring Agent — FastAPI Application Entry Point.

Mounts:
  /portal    → applicant intake (connectors/portal_api.py)

Top-level endpoints:
  GET  /health           → health check + pipeline stats
  POST /run-ingest       → trigger IngestPipeline from CSV upload
  POST /run-rank         → rank all scored applicants
  POST /run-interviews   → run interview pipeline for shortlisted applicants

Run locally:
  uv run uvicorn main:app --reload

API docs:
  http://localhost:8000/docs
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env before anything else so all agents see the env vars
load_dotenv()

from connectors.portal_api import app as portal_app
from memory.pageindex_store import PageIndexStore
from pipelines.ingest import IngestPipeline
from pipelines.rank import RankPipeline
from utils.logger import logger

# ─────────────────────────────────────────────────────
#  Shared state (process-lifetime singletons)
# ─────────────────────────────────────────────────────

_page_index    = PageIndexStore()
_ingest_pipeline  = IngestPipeline(page_index=_page_index)
_rank_pipeline    = RankPipeline()

# Last run results (in-memory cache — cleared on restart)
_last_ingest_result  = None
_last_rank_result    = None


# ─────────────────────────────────────────────────────
#  Lifespan (startup / shutdown)
# ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═══ Autonomous Hiring Agent starting ═══")
    logger.info(f"  GROQ_API_KEY  : {'set' if os.getenv('GROQ_API_KEY') else 'MISSING ⚠'}")
    logger.info(f"  SUPABASE_URL  : {'set' if os.getenv('SUPABASE_URL') else 'not set'}")
    logger.info(f"  MAX_APPLICANTS: {os.getenv('MAX_APPLICANTS', '1000 (default)')}")
    logger.info("═══════════════════════════════════════")
    yield
    logger.info("Autonomous Hiring Agent shutting down.")


# ─────────────────────────────────────────────────────
#  Main App
# ─────────────────────────────────────────────────────

app = FastAPI(
    title="Autonomous Hiring Agent",
    description=(
        "End-to-end AI hiring system. Processes applicants through "
        "resume scoring → interview → AI detection → final decision. "
        "All LLM calls go through Groq."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the portal sub-application
app.mount("/portal", portal_app)


# ─────────────────────────────────────────────────────
#  Health Check
# ─────────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
)
async def health():
    """Check if the hiring agent API is running."""
    return {
        "status":          "ok",
        "version":         "1.0.0",
        "timestamp":       datetime.utcnow().isoformat(),
        "page_index_size": _page_index.count(),
        "groq_key_set":    bool(os.getenv("GROQ_API_KEY")),
        "supabase_set":    bool(os.getenv("SUPABASE_URL")),
        "page_index_stats": _page_index.stats(),
    }


# ─────────────────────────────────────────────────────
#  Ingest Endpoint
# ─────────────────────────────────────────────────────

@app.post(
    "/run-ingest",
    tags=["Pipelines"],
    summary="Ingest applicants from CSV/Excel and score them",
)
async def run_ingest(
    file: UploadFile = File(
        ...,
        description="CSV or Excel file containing applicant data",
    ),
):
    """
    Upload a CSV or Excel file of applicants.

    Steps performed:
    1. Parse all rows into Applicant models
    2. Score each applicant via Groq llama-3.3-70b-versatile
    3. Store in PageIndexStore
    4. Return shortlist/reject/hold breakdown

    Required CSV columns: name, email, role, experience
    Optional: phone, skills, github, portfolio, linkedin, cover_letter, education
    """
    global _last_ingest_result

    allowed_types = {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File must be CSV or Excel (.csv / .xlsx / .xls). Got: {file.content_type}",
        )

    file_bytes = await file.read()
    file_ext   = file.filename.split(".")[-1] if file.filename else "csv"

    logger.info(f"MAIN | /run-ingest | {file.filename} | {len(file_bytes)} bytes")

    try:
        result = await _ingest_pipeline.run_from_csv(
            file_bytes=file_bytes,
            file_type=file_ext,
            source_label=file.filename or "uploaded_file",
        )
        _last_ingest_result = result

        return {
            "success":          True,
            "summary":          result.summary(),
            "total_applicants": result.total_applicants,
            "shortlisted":      len(result.shortlisted),
            "on_hold":          len(result.on_hold),
            "rejected":         len(result.rejected),
            "failed":           len(result.failed),
            "skipped":          len(result.skipped),
            "duration_seconds": result.duration_seconds,
            "top_shortlisted":  [
                {
                    "applicant_id": s.applicant_id,
                    "name":         s.applicant_name,
                    "score":        s.final_score,
                    "grade":        s.grade.value if s.grade else None,
                }
                for s in result.shortlisted[:10]
            ],
        }

    except Exception as e:
        logger.error(f"MAIN | /run-ingest failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingest pipeline failed: {e}",
        )


# ─────────────────────────────────────────────────────
#  Rank Endpoint
# ─────────────────────────────────────────────────────

@app.post(
    "/run-rank",
    tags=["Pipelines"],
    summary="Rank all scored applicants in the PageIndex",
)
async def run_rank(
    shortlist_threshold:    Optional[float] = None,
    auto_reject_threshold:  Optional[float] = None,
):
    """
    Re-rank all currently scored applicants using configurable thresholds.

    Uses scores already in the PageIndexStore from a previous /run-ingest call.
    Pass optional threshold overrides to adjust the shortlist / reject bands.
    """
    global _last_rank_result

    profiles = _page_index.get_all()
    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No applicants in PageIndex. Run /run-ingest first.",
        )

    from models.score import ApplicantScore, ScoringStatus

    # Reconstruct minimal ApplicantScore list from PageIndex profiles
    scores = []
    for p in profiles:
        if p.score is not None:
            from models.score import ScoreGrade
            score = ApplicantScore(
                applicant_id=p.applicant_id,
                applicant_name=p.full_name,
                status=ScoringStatus.COMPLETED,
                final_score=p.score,
                grade=ScoreGrade(p.grade) if p.grade else None,
                strengths=p.strengths,
                weaknesses=p.weaknesses,
            )
            scores.append(score)

    if not scores:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No scored applicants found. Run /run-ingest first.",
        )

    result = _rank_pipeline.run(
        scores,
        shortlist_threshold=shortlist_threshold,
        auto_reject_threshold=auto_reject_threshold,
    )
    _last_rank_result = result

    return {
        "success":          True,
        "summary":          result.summary(),
        "stats":            result.stats,
        "shortlisted":      len(result.shortlisted),
        "on_hold":          len(result.on_hold),
        "rejected":         len(result.rejected),
        "thresholds": {
            "shortlist":    result.shortlist_threshold,
            "auto_reject":  result.auto_reject_threshold,
        },
        "top_10": [
            {
                "rank":         s.rank,
                "applicant_id": s.applicant_id,
                "name":         s.applicant_name,
                "score":        s.final_score,
                "grade":        s.grade.value if s.grade else None,
                "percentile":   s.percentile,
            }
            for s in result.top_n(10)
        ],
    }


# ─────────────────────────────────────────────────────
#  Interview Pipeline Endpoint
# ─────────────────────────────────────────────────────

@app.post(
    "/run-interviews",
    tags=["Pipelines"],
    summary="Start interview sessions for all shortlisted applicants",
)
async def run_interviews():
    """
    Kick off interview sessions for all shortlisted applicants
    in the PageIndex.

    In live deployments, each interview is turn-based via the portal
    chat UI. This endpoint **starts** sessions and returns session IDs
    so the frontend can route applicants into their respective sessions.

    The applicant then interacts via:
      POST /portal/interview/{session_id}/respond
    """
    from pipelines.interview_flow import InterviewPipeline
    from memory.session_store import SessionStore

    shortlisted_profiles = _page_index.get_by_status("shortlisted")

    if not shortlisted_profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No shortlisted applicants found. Run /run-ingest and /run-rank first.",
        )

    logger.info(
        f"MAIN | /run-interviews | "
        f"Starting sessions for {len(shortlisted_profiles)} shortlisted applicants"
    )

    # We can only start sessions here — actual interviews are turn-based
    # and happen asynchronously via the portal chat interface.
    # Return session metadata for the frontend to route applicants.
    sessions_started = []
    for profile in shortlisted_profiles:
        sessions_started.append({
            "applicant_id":   profile.applicant_id,
            "name":           profile.full_name,
            "role":           profile.role,
            "score":          profile.score,
            "grade":          profile.grade,
            "interview_url":  f"/portal/interview/{profile.applicant_id}/start",
        })

    logger.info(f"MAIN | {len(sessions_started)} interview session slots prepared")

    return {
        "success":          True,
        "sessions_prepared": len(sessions_started),
        "sessions":         sessions_started,
        "note": (
            "Interview sessions are turn-based. Each applicant starts their "
            "interview at their interview_url. Responses are received via "
            "POST /portal/interview/{session_id}/respond"
        ),
    }
