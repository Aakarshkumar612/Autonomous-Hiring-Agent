# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Autonomous AI Hiring Agent — processes applicants end-to-end: resume parsing → scoring → AI/plagiarism detection → interviews → decisions. All LLM calls go through **Groq only** (no OpenAI, no Anthropic API).

## Development Setup

All work is done inside the `hiring-agent/` subdirectory. Python 3.12 is required.

```bash
cd hiring-agent

# Install dependencies (preferred)
uv sync

# Or with pip
pip install -r requirements.txt

# Run the app
uv run python main.py

# Start FastAPI server
uv run uvicorn main:app --reload
```

## Commands

```bash
# Format
uv run black .
uv run ruff check .
uv run ruff check --fix .

# Tests
uv run pytest
uv run pytest tests/path/to/test_file.py::test_name   # single test
uv run pytest -x                                       # stop on first failure
uv run pytest -k "keyword"                             # filter by name
```

## Architecture

The planned package structure (defined in `pyproject.toml`):

- **`agents/`** — LangGraph agent definitions. Each agent role maps to a specific Groq model (see `.env`): orchestrator, scorer, interviewer, detector, learner, researcher.
- **`connectors/`** — External service integrations: Groq API client, Supabase client, PageIndex RAG.
- **`models/`** — Pydantic data models for applicants, job descriptions, scores, interview transcripts.
- **`pipelines/`** — End-to-end LangGraph pipelines combining agents into hiring workflows.
- **`memory/`** — Supabase-backed memory layer ("Open Brain") for persistent agent state across sessions.
- **`utils/`** — Resume parsing (PyMuPDF for PDF, python-docx for DOCX), CSV/Excel ingestion, rate limiting, token counting.

## Key Technical Decisions

- **Groq-only LLM stack**: Different models are assigned to different roles via env vars (`GROQ_ORCHESTRATOR`, `GROQ_SCORER`, etc.). Never substitute another provider.
- **PageIndex RAG**: Vectorless, reasoning-based retrieval — not embedding-based. Don't replace with vector DB approaches.
- **LangGraph for orchestration**: Agent workflows are stateful graphs, not simple chains.
- **FastAPI portal**: Applicant intake (resume upload, form submission) is a separate HTTP service, not CLI-only.
- **AI/plagiarism detection**: Uses local `transformers`/`torch` models, not external APIs.

## Environment Variables

Copy `.env` and populate — required keys: `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`. See `.env` for all model assignments and config values (`MAX_APPLICANTS`, `INTERVIEW_ROUNDS`, `AI_DETECTION_THRESHOLD`, `SCORING_BATCH_SIZE`).

**Note**: `.env` is not in `.gitignore` — add it before committing.
