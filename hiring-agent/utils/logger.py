"""
utils/logger.py
═══════════════════════════════════════════════════════
Centralized logging for the Autonomous Hiring Agent.
Uses loguru for file logging + rich for beautiful
console output.

Usage:
    from utils.logger import logger, console

    logger.info("Scoring applicant INT-001")
    logger.success("Shortlisted: Aakarsh Kumar | Score: 85.5")
    logger.warning("AI flag detected in response")
    logger.error("Groq API call failed")
    console.print("[bold green]Batch complete![/bold green]")
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.theme import Theme


# ─────────────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────────────

LOG_DIR  = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE         = LOG_DIR / "hiring_agent.log"
ERROR_LOG_FILE   = LOG_DIR / "errors.log"
SCORING_LOG_FILE = LOG_DIR / "scoring.log"
INTERVIEW_LOG_FILE = LOG_DIR / "interviews.log"


# ─────────────────────────────────────────────────────
#  Rich Console (colored terminal output)
# ─────────────────────────────────────────────────────

custom_theme = Theme({
    "info":      "cyan",
    "success":   "bold green",
    "warning":   "bold yellow",
    "error":     "bold red",
    "agent":     "bold magenta",
    "score":     "bold blue",
    "highlight": "bold white",
})

console = Console(theme=custom_theme)


# ─────────────────────────────────────────────────────
#  Loguru Setup
# ─────────────────────────────────────────────────────

# Remove default loguru handler
logger.remove()

# ── Console handler (colored, human-readable) ────────
logger.add(
    sys.stdout,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "{message}"
    ),
    level="DEBUG",
    colorize=True,
)

# ── Main log file (all levels, rotates daily) ────────
logger.add(
    LOG_FILE,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
    level="DEBUG",
    rotation="1 day",
    retention="7 days",
    compression="zip",
    encoding="utf-8",
)

# ── Error-only log file ───────────────────────────────
logger.add(
    ERROR_LOG_FILE,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
    level="ERROR",
    rotation="1 week",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
)

# ── Scoring-specific log ──────────────────────────────
logger.add(
    SCORING_LOG_FILE,
    format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    level="DEBUG",
    filter=lambda record: "SCORE" in record["message"],
    rotation="1 week",
    retention="14 days",
    encoding="utf-8",
)

# ── Interview-specific log ────────────────────────────
logger.add(
    INTERVIEW_LOG_FILE,
    format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    level="DEBUG",
    filter=lambda record: "INTERVIEW" in record["message"],
    rotation="1 week",
    retention="14 days",
    encoding="utf-8",
)


# ─────────────────────────────────────────────────────
#  Convenience helpers
# ─────────────────────────────────────────────────────

def log_score(applicant_id: str, name: str, score: float, grade: str) -> None:
    """Log a scoring result — goes to both main log and scoring.log."""
    logger.info(f"SCORE | [{applicant_id}] {name} | {score} | Grade: {grade}")


def log_interview_event(session_id: str, event: str, detail: str = "") -> None:
    """Log an interview event — goes to both main log and interviews.log."""
    logger.info(f"INTERVIEW | [{session_id}] {event} | {detail}")


def log_ai_flag(applicant_id: str, session_id: str, confidence: float) -> None:
    """Log an AI detection flag."""
    logger.warning(
        f"AI FLAG | Applicant: {applicant_id} | "
        f"Session: {session_id} | Confidence: {confidence:.2%}"
    )


def log_batch_start(batch_id: str, size: int) -> None:
    logger.info(f"SCORE | Batch {batch_id} started | {size} applicants")
    console.print(f"[score]⚡ Batch {batch_id} | Scoring {size} applicants...[/score]")


def log_batch_complete(batch_id: str, scored: int, failed: int, avg: float) -> None:
    logger.info(
        f"SCORE | Batch {batch_id} complete | "
        f"Scored: {scored} | Failed: {failed} | Avg: {avg}"
    )
    console.print(
        f"[success]✓ Batch {batch_id} done | "
        f"Scored: {scored} | Failed: {failed} | Avg Score: {avg}[/success]"
    )


def log_api_error(agent: str, error: str, retry: int = 0) -> None:
    """Log a Groq API error with retry info."""
    logger.error(f"API ERROR | Agent: {agent} | Retry: {retry} | {error}")


def log_shortlist(applicant_id: str, name: str, score: float) -> None:
    logger.success(f"SHORTLISTED | [{applicant_id}] {name} | Score: {score}")
    console.print(f"[success]✓ Shortlisted: {name} | Score: {score}[/success]")


def log_rejected(applicant_id: str, name: str, score: float) -> None:
    logger.info(f"REJECTED | [{applicant_id}] {name} | Score: {score}")