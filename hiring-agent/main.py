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

import asyncio
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

from agents.learner import LearnerAgent
from connectors.portal_api import app as portal_app
from connectors.supabase_mcp import supabase_store
from memory.pageindex_store import ApplicantProfile, PageIndexStore
from memory.session_store import SessionStore
from models.applicant import Applicant, ApplicationStatus, ExperienceLevel, Skill, TechRole
from pipelines.ingest import IngestPipeline
from pipelines.interview_flow import InterviewPipeline
from pipelines.rank import RankPipeline
from utils.logger import logger

# ─────────────────────────────────────────────────────
#  Shared state (process-lifetime singletons)
# ─────────────────────────────────────────────────────

_page_index          = PageIndexStore()
_session_store       = SessionStore()
_ingest_pipeline     = IngestPipeline(page_index=_page_index)
_rank_pipeline       = RankPipeline()
_interview_pipeline  = InterviewPipeline(session_store=_session_store)
_learner_agent       = LearnerAgent()

# Max simultaneous interview sessions started by /run-interviews
MAX_CONCURRENT_INTERVIEWS = 5

# How often to purge expired sessions (seconds).
# Sessions older than their TTL are removed from memory.
SESSION_PURGE_INTERVAL = 300   # 5 minutes

# Last run results (in-memory cache — cleared on restart)
_last_ingest_result  = None
_last_rank_result    = None


# ─────────────────────────────────────────────────────
#  Lifespan (startup / shutdown)
# ─────────────────────────────────────────────────────

async def _session_purge_loop() -> None:
    """
    Background task: purge expired interview sessions every SESSION_PURGE_INTERVAL seconds.

    Why: SessionStore is in-memory. Expired sessions accumulate forever if
    purge_expired() is never called. This task runs as long as the server is up
    and prevents unbounded memory growth in long-running deployments.
    """
    while True:
        await asyncio.sleep(SESSION_PURGE_INTERVAL)
        try:
            purged = _session_store.purge_expired()
            if purged:
                logger.info(f"SESSION_PURGE | Removed {purged} expired session(s)")
        except Exception as exc:
            logger.warning(f"SESSION_PURGE | Error during purge: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═══ Autonomous Hiring Agent starting ═══")
    logger.info(f"  GROQ_API_KEY  : {'set' if os.getenv('GROQ_API_KEY') else 'MISSING ⚠'}")
    logger.info(f"  SUPABASE_URL  : {'set' if os.getenv('SUPABASE_URL') else 'not set'}")
    logger.info(f"  MAX_APPLICANTS: {os.getenv('MAX_APPLICANTS', '1000 (default)')}")
    logger.info(f"  GROQ_SCORER   : {os.getenv('GROQ_SCORER', 'llama-3.3-70b-versatile (default)')}")
    logger.info("═══════════════════════════════════════")

    # Start the background session-purge task.
    # asyncio.create_task schedules it on the running event loop.
    purge_task = asyncio.create_task(_session_purge_loop())
    logger.info(f"SESSION_PURGE | Background purge started (interval: {SESSION_PURGE_INTERVAL}s)")

    yield

    # Cancel the purge task cleanly on shutdown
    purge_task.cancel()
    try:
        await purge_task
    except asyncio.CancelledError:
        pass
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
    """Check if the hiring agent API is running and report PageIndex capacity."""
    pi_stats = _page_index.stats()
    return {
        "status":           "ok",
        "version":          "1.0.0",
        "timestamp":        datetime.utcnow().isoformat(),
        "groq_key_set":     bool(os.getenv("GROQ_API_KEY")),
        "supabase_set":     bool(os.getenv("SUPABASE_URL")),
        "page_index_size":  _page_index.count(),
        "page_index_cap":   _page_index.cap,
        "cap_usage_pct":    pi_stats["cap_usage_pct"],
        "is_near_cap":      pi_stats["is_near_cap"],
        "is_full":          pi_stats["is_full"],
        "page_index_stats": pi_stats,
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
#  Learner Endpoint
# ─────────────────────────────────────────────────────

@app.post(
    "/run-learn",
    tags=["Pipelines"],
    summary="Analyse hiring outcomes and generate scoring improvement recommendations",
)
async def run_learn():
    """
    Run the LearnerAgent on historical hiring data from Supabase.

    The LearnerAgent (deepseek-r1-distill-qwen-32b) uses chain-of-thought
    reasoning to identify which scoring signals were accurate predictors,
    recommend new scoring weights, flag new red flags, and suggest
    updated shortlist/reject thresholds.

    Call this after you have processed at least 20–30 applicants through the
    full pipeline (ingest → rank → interview → decision) to get meaningful
    recommendations.

    Why this matters: Without this feedback loop, your scoring model never
    improves. This is what separates a one-shot tool from a self-improving
    hiring system.
    """
    # ── 1. Pull hiring outcome stats from Supabase ────────────────
    try:
        total_accepted = await asyncio.to_thread(
            supabase_store.count_applicants, "accepted"
        )
        total_rejected = await asyncio.to_thread(
            supabase_store.count_applicants, "rejected"
        )
        total_on_hold  = await asyncio.to_thread(
            supabase_store.count_applicants, "on_hold"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Supabase unavailable — cannot load hiring stats: {exc}",
        )

    total_decisions = total_accepted + total_rejected
    if total_decisions < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Not enough hiring decisions to analyse ({total_decisions} found). "
                "Run /run-ingest → /run-rank → /run-interviews first and process "
                "at least 5 applicants through to a final verdict."
            ),
        )

    # ── 2. Pull top scored applicants for avg score computation ──
    try:
        top_rows = await asyncio.to_thread(
            supabase_store.get_top_scored, 200
        )
    except Exception:
        top_rows = []

    # Compute average scores by final status
    accepted_scores = [
        float(r.get("final_score", 0))
        for r in top_rows
        if r.get("status") == "accepted" and r.get("final_score") is not None
    ]
    rejected_scores = [
        float(r.get("final_score", 0))
        for r in top_rows
        if r.get("status") == "rejected" and r.get("final_score") is not None
    ]

    avg_score_hired    = sum(accepted_scores) / len(accepted_scores) if accepted_scores else 70.0
    avg_score_rejected = sum(rejected_scores) / len(rejected_scores) if rejected_scores else 40.0

    # Collect red flags from PageIndex (in-memory) for the current run
    all_profiles = _page_index.get_all()
    red_flag_counts: dict[str, int] = {}
    for profile in all_profiles:
        for flag in (profile.weaknesses or []):
            red_flag_counts[flag] = red_flag_counts.get(flag, 0) + 1
    top_red_flags = sorted(red_flag_counts, key=red_flag_counts.get, reverse=True)[:10]

    logger.info(
        f"LEARN | Accepted: {total_accepted} | Rejected: {total_rejected} | "
        f"On hold: {total_on_hold} | "
        f"Avg score hired: {avg_score_hired:.1f} | Avg score rejected: {avg_score_rejected:.1f}"
    )

    # ── 3. Run LearnerAgent ───────────────────────────────────────
    try:
        insight = await _learner_agent.analyse(
            total_hired=total_accepted,
            total_rejected=total_rejected,
            avg_score_hired=avg_score_hired,
            avg_score_rejected=avg_score_rejected,
            false_positive_rate=0.0,    # TODO: wire when you collect post-hire feedback
            false_negative_rate=0.0,
            top_red_flags=top_red_flags,
            scoring_dimension_accuracy={},  # TODO: wire when dimension tracking is added
        )
    except Exception as exc:
        logger.error(f"LEARN | LearnerAgent failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LearnerAgent failed: {exc}",
        )

    return {
        "success":      not bool(insight.error),
        "error":        insight.error,
        "summary":      insight.summary,
        "data_used": {
            "total_accepted":     total_accepted,
            "total_rejected":     total_rejected,
            "total_on_hold":      total_on_hold,
            "avg_score_hired":    round(avg_score_hired, 1),
            "avg_score_rejected": round(avg_score_rejected, 1),
            "top_red_flags":      top_red_flags,
        },
        "recommendations": {
            "weight_adjustments":        insight.weight_adjustments,
            "new_red_flags":             insight.new_red_flags,
            "interview_improvements":    insight.interview_improvements,
            "threshold_recommendations": insight.threshold_recommendations,
            "insights":                  insight.insights,
        },
    }


# ─────────────────────────────────────────────────────
#  Interview helpers
# ─────────────────────────────────────────────────────

def _exp_level(years: float) -> ExperienceLevel:
    if years == 0:
        return ExperienceLevel.FRESHER
    elif years <= 2:
        return ExperienceLevel.JUNIOR
    elif years <= 5:
        return ExperienceLevel.MID
    elif years <= 8:
        return ExperienceLevel.SENIOR
    return ExperienceLevel.LEAD


def _applicant_from_supabase_row(row: dict) -> Applicant:
    """
    Reconstruct a minimal Applicant from a raw Supabase row dict.

    Supabase returns JSONB columns (skills) already deserialised as
    Python lists. String-encoded JSON is handled as a fallback.
    Fields not persisted (work_experience, detailed_status) default.
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
        role_applied=TechRole(row["role_applied"]),
        experience_level=ExperienceLevel(row.get("experience_level", "fresher")),
        total_experience_months=row.get("total_experience_months", 0),
        resume_url=row.get("resume_url"),
        resume_text=row.get("resume_text"),
        github_url=row.get("github_url"),
        portfolio_url=row.get("portfolio_url"),
        linkedin_url=row.get("linkedin_url"),
        cover_letter=row.get("cover_letter"),
        education=row.get("education"),
        skills=skills,
        status=ApplicationStatus(row.get("status", "shortlisted")),
        source=row.get("source", "supabase"),
    )


def _applicant_from_profile(profile: ApplicantProfile) -> Applicant:
    """
    Build a minimal Applicant from a PageIndex ApplicantProfile.

    Used as a fallback when Supabase returns no shortlisted rows
    (e.g. the ingest pipeline hasn't saved to Supabase yet).
    """
    return Applicant(
        id=profile.applicant_id,
        full_name=profile.full_name,
        email=profile.email,
        role_applied=TechRole(profile.role),
        experience_level=_exp_level(profile.experience_years),
        total_experience_months=int(profile.experience_years * 12),
        skills=[Skill(name=s) for s in profile.skills],
        github_url=profile.github_url,
        portfolio_url=profile.portfolio_url,
        education=profile.education,
        status=ApplicationStatus(profile.status),
        source="pageindex",
    )


async def _start_one_interview(
    pipeline: InterviewPipeline,
    applicant: Applicant,
    sem: asyncio.Semaphore,
) -> dict:
    """
    Start one interview session under the concurrency semaphore.

    Never raises — failures are captured and returned as a dict with
    status "failed" so asyncio.gather() always produces a complete list.
    """
    async with sem:
        try:
            session_id, first_question = await pipeline.start_interview(applicant)
            logger.info(
                f"MAIN | Session started | {session_id} | "
                f"[{applicant.id}] {applicant.full_name}"
            )
            return {
                "applicant_id":   applicant.id,
                "name":           applicant.full_name,
                "role":           applicant.role_applied.value,
                "session_id":     session_id,
                "first_question": first_question,
                "respond_url":    f"/portal/interview/{session_id}/respond",
                "status_url":     f"/portal/interview/{session_id}/status",
                "status":         "started",
                "error":          None,
            }
        except Exception as exc:
            logger.error(
                f"MAIN | Failed to start interview for "
                f"[{applicant.id}] {applicant.full_name}: {exc}"
            )
            return {
                "applicant_id":   applicant.id,
                "name":           applicant.full_name,
                "role":           applicant.role_applied.value,
                "session_id":     None,
                "first_question": None,
                "respond_url":    None,
                "status_url":     None,
                "status":         "failed",
                "error":          str(exc),
            }


# ─────────────────────────────────────────────────────
#  Interview Pipeline Endpoint
# ─────────────────────────────────────────────────────

@app.post(
    "/run-interviews",
    tags=["Pipelines"],
    summary="Start interview sessions for all shortlisted applicants (concurrent)",
)
async def run_interviews():
    """
    Start autonomous 3-round interview sessions for every shortlisted applicant.

    Source priority:
      1. Supabase `applicants` table filtered by status = shortlisted
      2. In-memory PageIndex (fallback when Supabase is empty or unavailable)

    Sessions are started concurrently — up to MAX_CONCURRENT_INTERVIEWS at once
    (default 5) to respect Groq rate limits. Each started session returns:
      - `session_id`     → unique session token
      - `first_question` → Round 1 opening question to present to the applicant
      - `respond_url`    → POST here with field `response_text` to continue
      - `status_url`     → GET here to poll current round / AI flags / score

    Failed sessions are included in the response with `status: "failed"` so
    the caller can retry individual applicants without re-running the whole batch.
    """
    # ── 1. Fetch shortlisted applicants ──────────────────────────────
    applicants: list[Applicant] = []

    try:
        rows = await asyncio.to_thread(
            supabase_store.get_all_applicants, "shortlisted"
        )
        if rows:
            for row in rows:
                try:
                    applicants.append(_applicant_from_supabase_row(row))
                except Exception as exc:
                    logger.warning(
                        f"MAIN | Skipping malformed Supabase row "
                        f"[{row.get('id', '?')}]: {exc}"
                    )
            logger.info(
                f"MAIN | /run-interviews | "
                f"Loaded {len(applicants)} shortlisted applicants from Supabase"
            )
    except Exception as exc:
        logger.warning(f"MAIN | Supabase fetch failed ({exc}) — falling back to PageIndex")

    # Fallback: PageIndex (populated by /run-ingest when Supabase is not in use)
    if not applicants:
        profiles = _page_index.get_by_status("shortlisted")
        for profile in profiles:
            try:
                applicants.append(_applicant_from_profile(profile))
            except Exception as exc:
                logger.warning(
                    f"MAIN | Skipping PageIndex profile "
                    f"[{profile.applicant_id}]: {exc}"
                )
        if applicants:
            logger.info(
                f"MAIN | /run-interviews | "
                f"Loaded {len(applicants)} shortlisted applicants from PageIndex"
            )

    if not applicants:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No shortlisted applicants found in Supabase or PageIndex. "
                "Run /run-ingest then /run-rank first."
            ),
        )

    logger.info(
        f"MAIN | /run-interviews | "
        f"Starting {len(applicants)} interview sessions "
        f"(max {MAX_CONCURRENT_INTERVIEWS} concurrent)"
    )

    # ── 2. Start all sessions concurrently under semaphore ────────────
    sem     = asyncio.Semaphore(MAX_CONCURRENT_INTERVIEWS)
    tasks   = [
        _start_one_interview(_interview_pipeline, applicant, sem)
        for applicant in applicants
    ]
    results: list[dict] = await asyncio.gather(*tasks)

    # ── 3. Summarise ──────────────────────────────────────────────────
    started = [r for r in results if r["status"] == "started"]
    failed  = [r for r in results if r["status"] == "failed"]

    logger.info(
        f"MAIN | /run-interviews complete | "
        f"Started: {len(started)} | Failed: {len(failed)}"
    )

    return {
        "success":        len(started) > 0,
        "total":          len(results),
        "started":        len(started),
        "failed":         len(failed),
        "max_concurrent": MAX_CONCURRENT_INTERVIEWS,
        "sessions":       results,
        "note": (
            "Each applicant's first question is in `first_question`. "
            "Submit answers via the `respond_url`. "
            "Poll progress via the `status_url`."
        ),
    }
