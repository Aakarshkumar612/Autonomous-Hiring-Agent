# PROJECT STATUS REPORT
**Autonomous Hiring Agent (HireIQ)**
Generated: 2026-04-09

---

## 1. COMPLETE FILE INVENTORY

| # | File Path | Lines | Description | Status |
|---|-----------|-------|-------------|--------|
| 1 | `agents/__init__.py` | 0 | Package marker | empty |
| 2 | `agents/detector.py` | 242 | AI/plagiarism detection agent using `llama-3.1-8b-instant` | **complete** |
| 3 | `agents/interviewer.py` | 493 | 3-round autonomous interview agent using `llama-4-maverick` | **complete** |
| 4 | `agents/learner.py` | 233 | Hiring outcome analysis agent using `deepseek-r1-distill-qwen-32b` | **complete** |
| 5 | `agents/orchestrator.py` | 232 | Final hire/reject/hold decision agent using `llama-3.3-70b-versatile` | **complete** |
| 6 | `agents/scorer.py` | 245 | Applicant scoring agent (5 dimensions, batched) using `llama-3.3-70b-versatile` | **complete** |
| 7 | `connectors/__init__.py` | 0 | Package marker | empty |
| 8 | `connectors/csv_ingestor.py` | 335 | Bulk CSV/Excel applicant ingestion with column normalisation | **complete** |
| 9 | `connectors/portal_api.py` | 382 | FastAPI portal: apply, bulk upload, list, status-patch endpoints | **partial** |
| 10 | `connectors/resume_parser.py` | 401 | PDF/DOCX/TXT resume parser with regex field extraction | **complete** |
| 11 | `connectors/supabase_mcp.py` | 469 | Supabase CRUD for applicants, scores, sessions, agent memory | **complete** |
| 12 | `memory/__init__.py` | 0 | Package marker | empty |
| 13 | `memory/pageindex_store.py` | 286 | In-memory reasoning-based applicant profile index (PageIndex) | **complete** |
| 14 | `memory/session_store.py` | 269 | In-memory active interview session store with TTL expiry | **complete** |
| 15 | `models/__init__.py` | 0 | Package marker | empty |
| 16 | `models/applicant.py` | 266 | Pydantic v2 Applicant, WorkExperience, Skill, DetailedStatus models | **complete** |
| 17 | `models/interview.py` | 302 | Pydantic v2 InterviewSession, Question, Response, RoundSummary models | **complete** |
| 18 | `models/score.py` | 268 | Pydantic v2 ApplicantScore, DimensionScore, BatchScoringResult models | **complete** |
| 19 | `pipelines/__init__.py` | 0 | Package marker | empty |
| 20 | `pipelines/ingest.py` | 303 | End-to-end CSV → score → PageIndex pipeline | **complete** |
| 21 | `pipelines/interview_flow.py` | 405 | Full 3-round interview orchestration pipeline (turn-based + automated) | **complete** |
| 22 | `pipelines/rank.py` | 229 | Score ranking pipeline: percentile assignment + band bucketing | **complete** |
| 23 | `utils/__init__.py` | 0 | Package marker | empty |
| 24 | `utils/logger.py` | 171 | Loguru + Rich multi-sink logging with structured helpers | **complete** |
| 25 | `utils/prompt_templates.py` | 538 | All Groq LLM prompts (orchestrator, scorer, interviewer, detector, learner, researcher) | **complete** |
| 26 | `utils/rate_limiter.py` | 316 | Per-model RPM/RPD token-bucket limiter + async retry with backoff | **complete** |
| 27 | `tests/__init__.py` | 0 | Package marker | empty |
| 28 | `tests/test_detector.py` | 0 | Detector agent tests | **empty** |
| 29 | `tests/test_interview.py` | 0 | Interview pipeline tests | **empty** |
| 30 | `tests/test_scorer.py` | 0 | Scorer agent tests | **empty** |
| 31 | `main.py` | 351 | FastAPI app entry point: /health, /run-ingest, /run-rank, /run-interviews | **complete** |
| 32 | `pyproject.toml` | 72 | uv/hatch project config + all dependencies | **complete** |
| 33 | `.env.example` | 31 | Environment variable template | **complete** |
| 34 | `requirements.txt` | 78 | pip-compatible dependency list | **complete** |

**Missing (not yet created):**
- `agents/researcher.py` — Researcher agent (`compound-beta`) — prompt exists but file is absent

---

## 2. COMPLETED FILES — DETAIL

### `agents/detector.py` (242 lines)
**Key classes/functions:**
- `DetectionResult` — dataclass: `question_id`, `verdict`, `confidence`, `signals`, `reasoning`, `flagged`
- `DetectorAgent` — async agent
  - `_call_groq(prompt)` — single-shot classification
  - `_parse_response(raw, question_id)` → `DetectionResult`
  - `detect(question, response, applicant_name, role, experience_years, question_id)` → `DetectionResult`
  - `scan_session(session, experience_years)` → `list[DetectionResult]`

**External imports:** `groq.AsyncGroq`

**Issues/TODOs:** None found.

---

### `agents/interviewer.py` (493 lines)
**Key classes/functions:**
- `InterviewerAgent` — full stateful interview conductor
  - `start_session(applicant)` → `(InterviewSession, first_question_text)`
  - `process_response(session, response_text)` → `(next_question | None, is_complete)`
  - `_open_round(session)`, `_finish_round(session)`, `_complete_round(session)`
  - `_ask_next_question(session, last_response)`
  - `_call_groq(session, prompt)`, `_call_groq_summary(prompt)`

**External imports:** `groq.AsyncGroq`, `connectors.supabase_mcp.supabase_store`

**Issues/TODOs:** None found.

---

### `agents/learner.py` (233 lines)
**Key classes/functions:**
- `LearnerInsight` — dataclass: `insights`, `weight_adjustments`, `new_red_flags`, `interview_improvements`, `threshold_recommendations`, `summary`, `raw_response`, `error`
- `LearnerAgent` — offline reasoning agent
  - `_call_groq(prompt)`, `_parse_response(raw)` → `LearnerInsight`
  - `analyse(total_hired, total_rejected, avg_score_hired, ...)` → `LearnerInsight`

**External imports:** `groq.AsyncGroq`

**Issues/TODOs:** No trigger mechanism wired up — `LearnerAgent.analyse()` must be called manually. No scheduled/periodic invocation exists yet.

---

### `agents/orchestrator.py` (232 lines)
**Key classes/functions:**
- `OrchestratorDecision` — dataclass: `applicant_id`, `verdict`, `confidence`, `reason`, `next_action`, `ai_flags`, `error`
- `OrchestratorAgent`
  - `_call_groq(prompt)`, `_parse_response(raw, applicant_id, ai_flags)`
  - `decide(applicant, score, detection_results, round_scores)` → `OrchestratorDecision`

**External imports:** `groq.AsyncGroq`, `agents.detector.DetectionResult`

**Issues/TODOs:** None found.

---

### `agents/scorer.py` (245 lines)
**Key classes/functions:**
- `ScorerAgent`
  - `_call_groq(prompt)`, `_parse_response(raw, score)`
  - `score_applicant(applicant)` → `ApplicantScore`
  - `score_batch(applicants, batch_id)` → `BatchScoringResult`
  - `score_all(applicants)` → `list[BatchScoringResult]`

**External imports:** `groq.AsyncGroq`

**Issues/TODOs:** None found.

---

### `connectors/csv_ingestor.py` (335 lines)
**Key classes/functions:**
- `IngestResult` — dataclass with `total_rows`, `applicants`, `errors`, `skipped`, `success_count`, `error_count`, `summary()`
- `CSVIngestor`
  - `ingest(file_bytes, file_type, source_label)` → `IngestResult`
  - `ingest_from_path(file_path, source_label)` → `IngestResult`
- `COLUMN_MAP`, `ROLE_MAP` — flexible column name normalisation
- `_row_to_applicant(row, index, source_label)` → `Applicant`

**External imports:** `pandas`

**Issues/TODOs:** `_safe_str` has a minor logic flaw: it checks `isinstance(val, float)` before `math.isnan()` but still calls `isnan` when the first check is false — safe but slightly redundant.

---

### `connectors/portal_api.py` (382 lines) — PARTIAL
**Key endpoints:**
- `POST /apply` — single application with resume upload
- `POST /apply/bulk` — CSV/Excel bulk upload
- `GET /applicants` — list with status/role filters + pagination
- `GET /applicants/{id}` — single applicant fetch
- `PATCH /applicants/{id}/status` — status update
- `GET /stats` — counts by status and role
- `GET /health` — health check

**External imports:** `fastapi`, `connectors.csv_ingestor`, `connectors.resume_parser`

**Issues/TODOs:**
- **Missing interview routing endpoints.** `main.py:338` references `GET /portal/interview/{applicant_id}/start` and `POST /portal/interview/{session_id}/respond`, but neither endpoint exists in `portal_api.py`. The `InterviewPipeline.process_interview_response()` is fully implemented in `pipelines/interview_flow.py` but is never wired to an HTTP route.
- `_applicant_store` is in-memory only — not backed by Supabase (noted as TODO comment).

---

### `connectors/resume_parser.py` (401 lines)
**Key classes/functions:**
- `ResumeParseResult` — dataclass with all extracted fields
- `ResumeParser`
  - `parse(file_bytes, file_type, filename)` → `ResumeParseResult`
  - `parse_from_path(file_path)` → `ResumeParseResult`
- Standalone extractors: `extract_email`, `extract_phone`, `extract_github_url`, `extract_linkedin_url`, `extract_portfolio_url`, `extract_skills`, `extract_education`, `extract_name_from_top`
- `clean_text(text)` — normalises raw extracted text

**External imports:** `fitz` (pymupdf), `docx` (python-docx)

**Issues/TODOs:** `extract_skills` uses a static curated list — won't catch niche/emerging skills. No LLM-based enrichment yet.

---

### `connectors/supabase_mcp.py` (469 lines)
**Key classes/functions:**
- `SupabaseStore`
  - `save_applicant`, `get_applicant`, `get_all_applicants`, `update_applicant_status`, `count_applicants`
  - `save_score`, `get_score`, `get_top_scored`
  - `save_session`, `get_session`, `get_sessions_for_applicant`
  - `memory_set`, `memory_get`, `memory_delete`
  - `print_schema()` — prints SQL DDL for Supabase setup
- `SCHEMA_SQL` — full SQL DDL for all 4 tables
- Global instance: `supabase_store`

**External imports:** `supabase.Client`, `supabase.create_client`

**Issues/TODOs:** All Supabase calls are synchronous (blocking). `agents/interviewer.py` wraps them in `asyncio.to_thread()` but other callers don't — potential event-loop blocking in high-concurrency use.

---

### `memory/pageindex_store.py` (286 lines)
**Key classes/functions:**
- `ApplicantProfile` — dataclass: all flattened fields + `searchable_text()`, `to_dict()`
- `PageIndexStore`
  - `add_applicant(applicant, score, session)` → `ApplicantProfile`
  - `update_status`, `remove`
  - `get_applicant`, `get_all`, `count`
  - `search_similar_profiles(query, top_k, role_filter, min_score)` — keyword-overlap retrieval
  - `get_top_scored(limit, role_filter)`, `get_by_status(status)`, `stats()`

**External imports:** None (stdlib only)

**Issues/TODOs:** In-memory only — does not persist to Supabase. Process restart loses all data unless re-ingested.

---

### `memory/session_store.py` (269 lines)
**Key classes/functions:**
- `_SessionEntry` — internal TTL wrapper around `InterviewSession`
- `SessionStore`
  - `create_session`, `get_session`, `update_session`, `end_session`, `abandon_session`
  - `purge_expired()` — call periodically to free memory
  - `active_count`, `get_all_active`, `stats()`

**External imports:** None (stdlib only)

**Issues/TODOs:** No background purge task wired up — `purge_expired()` must be called manually. No FastAPI background task or lifespan hook calls it.

---

### `models/applicant.py` (266 lines)
**Key classes:**
- Enums: `TechRole`, `ExperienceLevel`, `ApplicationStatus`, `InterviewRound`, `AIDetectionVerdict`
- `WorkExperience`, `Skill`, `RoundScore`, `DetailedStatus`
- `Applicant` — core model with validators + helpers: `total_experience_years()`, `skill_names()`, `summary()`

**External imports:** `pydantic`

**Issues/TODOs:** None found.

---

### `models/interview.py` (302 lines)
**Key classes:**
- Enums: `InterviewType`, `MessageRole`, `QuestionCategory`, `ResponseQuality`, `SessionStatus`
- `InterviewMessage`, `InterviewQuestion`, `InterviewResponse`, `RoundSummary`
- `InterviewSession` — full session with `add_message()`, `add_response()`, `get_conversation_history()`, `advance_round()`, `compute_final_score()`, `summary()`

**External imports:** `pydantic`

**Issues/TODOs:** None found.

---

### `models/score.py` (268 lines)
**Key classes:**
- Enums: `ScoreGrade`, `ScoringDimension`, `ScoringStatus`
- `DimensionScore`, `ScoringCriteria`, `ApplicantScore`, `BatchScoringResult`
- `ApplicantScore` methods: `compute_final_score()`, `_assign_grade()`, `is_shortlistable()`, `should_auto_reject()`, `get_red_flags()`, `summary_line()`

**External imports:** `pydantic`

**Issues/TODOs:** `ScoringCriteria` is defined but never used at runtime — `scorer_prompt()` hardcodes weights in the prompt text. The two could drift out of sync.

---

### `pipelines/ingest.py` (303 lines)
**Key classes/functions:**
- `IngestPipelineResult` — dataclass with `total_applicants`, `scores`, `shortlisted`, `rejected`, `on_hold`, `failed`, `skipped`, `duration_seconds`, `summary()`
- `IngestPipeline`
  - `run_from_applicants(applicants)` → `IngestPipelineResult`
  - `run_from_csv(file_bytes, file_type, source_label)` → `IngestPipelineResult`

**External imports:** `agents.scorer.ScorerAgent`, `connectors.csv_ingestor`, `memory.pageindex_store`

**Issues/TODOs:** Does not call `supabase_store.save_applicant()` or `save_score()` — all data stays in PageIndex (in-memory). Supabase persistence must be added.

---

### `pipelines/interview_flow.py` (405 lines)
**Key classes/functions:**
- `InterviewPipelineResult` — dataclass with session, detections, decision, round_scores, summary
- `_ResponseProvider` — abstract interface for applicant answer source
- `InterviewPipeline`
  - `run_interview(applicant, score, response_provider, experience_years)` → full automated run
  - `start_interview(applicant)` → `(session_id, first_question)` — live portal entry point
  - `process_interview_response(session_id, response_text, applicant, score, experience_years)` → dict

**External imports:** `agents.detector`, `agents.interviewer`, `agents.orchestrator`, `memory.session_store`

**Issues/TODOs:**
- `start_interview()` / `process_interview_response()` are fully implemented but **not wired to any HTTP route** in `portal_api.py`.
- No Supabase save of final `OrchestratorDecision` — only the session is saved by `InterviewerAgent`.

---

### `pipelines/rank.py` (229 lines)
**Key classes/functions:**
- `RankResult` — dataclass with all bands, stats, thresholds, `summary()`, `top_n(n)`
- `RankPipeline`
  - `run(scores, shortlist_threshold, auto_reject_threshold)` → `RankResult`
  - `_compute_stats(completed, result, ...)` → stats dict
- `_median(values)` — utility

**External imports:** `utils.logger.log_shortlist`, `log_rejected`

**Issues/TODOs:** None found.

---

### `utils/logger.py` (171 lines)
**Key exports:**
- `logger` — loguru logger (console + main log + error log + scoring log + interview log)
- `console` — Rich Console with custom theme
- Helpers: `log_score`, `log_interview_event`, `log_ai_flag`, `log_batch_start`, `log_batch_complete`, `log_api_error`, `log_shortlist`, `log_rejected`

**External imports:** `loguru`, `rich`

**Issues/TODOs:** None found.

---

### `utils/prompt_templates.py` (538 lines)
**Key exports:**
- System prompts: `ORCHESTRATOR_SYSTEM`, `SCORER_SYSTEM`, `INTERVIEWER_SYSTEMS` (dict), `DETECTOR_SYSTEM`, `LEARNER_SYSTEM`, `RESEARCHER_SYSTEM`
- Prompt builders: `orchestrator_decision_prompt`, `scorer_prompt`, `interviewer_opening_prompt`, `interviewer_followup_prompt`, `interviewer_round_summary_prompt`, `detector_prompt`, `learner_analysis_prompt`, `researcher_prompt`

**External imports:** None

**Issues/TODOs:**
- `RESEARCHER_SYSTEM` and `researcher_prompt()` exist here but `agents/researcher.py` does not exist.

---

### `utils/rate_limiter.py` (316 lines)
**Key classes/functions:**
- `ModelLimits`, `ModelUsage`, `GROQ_MODEL_LIMITS`
- `GroqRateLimiter`
  - `acquire(model)` — async wait with RPM+RPD enforcement
  - `get_usage_stats(model)`, `print_all_stats()`
- `with_retry(func, *args, max_retries, base_delay, model)` — async exponential backoff
- `sync_retry(func, ...)` — sync version
- `batch_delay(batch_index, delay_between_batches)` — inter-batch spacing
- `DailyLimitExceededError`, `RateLimitError`
- Global instance: `rate_limiter`

**External imports:** None (stdlib only)

**Issues/TODOs:** Lock creation in `_get_lock()` is not protected — two concurrent coroutines could create duplicate locks on the first call for a new model. Low risk in practice.

---

### `main.py` (351 lines)
**Key endpoints:**
- `GET /health` — env check + PageIndex stats
- `POST /run-ingest` — CSV upload → `IngestPipeline.run_from_csv()`
- `POST /run-rank` — re-rank PageIndex contents via `RankPipeline.run()`
- `POST /run-interviews` — returns session start URLs for shortlisted applicants (does NOT call `InterviewPipeline.start_interview()`)
- Mounts `portal_app` at `/portal`

**External imports:** `fastapi`, `dotenv`, `connectors.portal_api`, `memory.pageindex_store`, `pipelines.ingest`, `pipelines.rank`

**Issues/TODOs:**
- `/run-interviews` references `GET /portal/interview/{applicant_id}/start` but this route does not exist in `portal_api.py`.
- `InterviewPipeline` is imported inside the function body but never actually called — sessions are **not started**, only URL strings are returned.

---

## 3. `pyproject.toml` DEPENDENCIES

```toml
[project]
name = "hiring-agent"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

dependencies = [
    # LLM
    "groq>=1.1.2",
    # Agent Frameworks
    "langchain>=0.2.0",
    "langgraph>=0.1.0",
    # FastAPI
    "fastapi>=0.111.0",
    "uvicorn>=0.30.0",
    "python-multipart>=0.0.9",
    # Resume Parsing
    "pymupdf>=1.24.0",
    "python-docx>=1.1.0",
    # CSV Ingestion
    "pandas>=2.2.0",
    "openpyxl>=3.1.0",
    # Supabase
    "supabase>=2.4.0",
    # PageIndex RAG
    "pageindex>=0.2.6",
    # AI/Plagiarism Detection
    "transformers>=4.41.0",
    "torch>=2.4.0",
    "accelerate>=0.30.0",
    # Data Validation
    "pydantic>=2.7.0",
    "pydantic-settings>=2.2.0",
    "numpy>=1.26.0",
    # HTTP & Async
    "httpx>=0.27.0",
    "aiohttp>=3.9.0",
    "tenacity>=8.3.0",
    # Utilities
    "ratelimit>=2.2.1",
    "tiktoken>=0.7.0",
    "python-dotenv>=1.0.0",
    "python-dateutil>=2.9.0",
    "loguru>=0.7.0",
    "rich>=13.7.0",
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "black>=24.4.0",
    "ruff>=0.4.0",
]
```

**Note:** `langchain`, `langgraph`, `transformers`, `torch`, `accelerate`, `pageindex`, `tenacity`, `ratelimit`, `tiktoken`, `aiohttp`, `httpx` are declared but **not actively imported** in any current source file. They appear reserved for planned features.

---

## 4. `.env.example` CONTENTS

```env
# Groq API
GROQ_API_KEY=your_groq_api_key_here

# Model Assignments
GROQ_ORCHESTRATOR=llama-3.3-70b-versatile
GROQ_SCORER=llama-3.3-70b-versatile
GROQ_INTERVIEWER=meta-llama/llama-4-maverick-17b-128e-instruct
GROQ_DETECTOR=llama-3.1-8b-instant
GROQ_LEARNER=deepseek-r1-distill-qwen-32b
GROQ_RESEARCHER=compound-beta

# Supabase (Memory)
SUPABASE_URL=your_supabase_project_url_here
SUPABASE_KEY=your_supabase_publishable_key_here

# App Config
MAX_APPLICANTS=1000
INTERVIEW_ROUNDS=3
AI_DETECTION_THRESHOLD=0.75
SCORING_BATCH_SIZE=50
```

**Note:** Agents currently read model names hardcoded (e.g. `DETECTOR_MODEL = "llama-3.1-8b-instant"`) rather than reading `GROQ_DETECTOR` from env. The `.env.example` model vars are unused at runtime.

---

## 5. WHAT STILL NEEDS TO BE BUILT

### agents/ — 5 of 6 done

| Agent | Status | Notes |
|-------|--------|-------|
| `detector.py` | ✅ complete | |
| `interviewer.py` | ✅ complete | |
| `learner.py` | ✅ complete | No trigger mechanism wired |
| `orchestrator.py` | ✅ complete | |
| `scorer.py` | ✅ complete | |
| `researcher.py` | ❌ **missing** | Prompt template exists, file does not |

### memory/ — 2 of 2 done

| File | Status | Notes |
|------|--------|-------|
| `pageindex_store.py` | ✅ complete | In-memory only |
| `session_store.py` | ✅ complete | No background purge task |

### pipelines/ — 3 of 3 done

| File | Status | Notes |
|------|--------|-------|
| `ingest.py` | ✅ complete | No Supabase save |
| `interview_flow.py` | ✅ complete | Not wired to HTTP routes |
| `rank.py` | ✅ complete | |

### main.py — partial

- `/run-ingest` — ✅ works end-to-end
- `/run-rank` — ✅ works end-to-end
- `/run-interviews` — ❌ returns URLs only, does not start sessions

### Tests — 0 of 3 written

| File | Status |
|------|--------|
| `tests/test_detector.py` | ❌ empty |
| `tests/test_interview.py` | ❌ empty |
| `tests/test_scorer.py` | ❌ empty |

---

## 6. IMPORT INCONSISTENCIES

| Location | Import / Reference | Issue |
|----------|-------------------|-------|
| `utils/prompt_templates.py:493` | `researcher_prompt()`, `RESEARCHER_SYSTEM` defined | `agents/researcher.py` does not exist — cannot import |
| `.env.example:22` | `GROQ_RESEARCHER=compound-beta` | Referenced model but no agent to use it |
| `main.py:338` | `f"/portal/interview/{profile.applicant_id}/start"` | Route does not exist in `portal_api.py` |
| `main.py:298` | `POST /portal/interview/{session_id}/respond` (docstring) | Route does not exist in `portal_api.py` |
| `main.py:310-311` | `from pipelines.interview_flow import InterviewPipeline` / `from memory.session_store import SessionStore` | Imported but **not called** — `InterviewPipeline` is never instantiated in the endpoint |
| `pyproject.toml` | `langchain`, `langgraph`, `transformers`, `torch`, `accelerate`, `pageindex`, `tenacity`, `ratelimit`, `tiktoken` | Declared as dependencies but no source file imports them |
| `models/score.py:69` | `ScoringCriteria` class | Fully defined but never used — scorer weights are hardcoded in `utils/prompt_templates.py` |

---

## 7. OVERALL COMPLETION ESTIMATE

```
Core Source Files (excluding __init__.py and config):

  agents/          5 / 6    (83%)  — researcher.py missing
  connectors/      4 / 4   (100%)  — portal_api.py partial (no interview routes)
  memory/          2 / 2   (100%)  — no Supabase write-through in ingest pipeline
  models/          3 / 3   (100%)
  pipelines/       3 / 3   (100%)  — interview_flow not wired to HTTP
  utils/           3 / 3   (100%)
  main.py          1 / 1    (80%)  — /run-interviews incomplete
  tests/           0 / 3     (0%)  — all empty

  Total source:   21 / 23   (91%)  — by file count

Feature Completeness:

  [✅] Resume ingestion (CSV/portal)        100%
  [✅] Resume parsing (PDF/DOCX)            100%
  [✅] Applicant scoring (batch)            100%
  [✅] Score ranking & bucketing            100%
  [✅] AI/plagiarism detection              100%
  [✅] 3-round interview engine             100%
  [✅] Orchestrator final decision          100%
  [✅] Supabase persistence layer           100%
  [✅] In-memory PageIndex store            100%
  [✅] Rate limiting & retry logic          100%
  [✅] Prompt templates (all 6 agents)      100%
  [⚠️] Interview HTTP routing              50%  — pipeline exists, routes missing
  [⚠️] Supabase write-through in ingest    30%  — Supabase connector exists, not called
  [❌] Researcher agent                      0%  — file missing
  [❌] LearnerAgent trigger / scheduling     0%  — agent exists, not called anywhere
  [❌] Test suite                            0%  — all test files empty
  [❌] Model env var wiring                  0%  — agents ignore GROQ_* env vars

OVERALL COMPLETION:  ~72%
```

---

## PRIORITY FIXES (in order)

1. **Add interview HTTP routes** to `portal_api.py`:
   - `POST /interview/{applicant_id}/start` → calls `InterviewPipeline.start_interview()`
   - `POST /interview/{session_id}/respond` → calls `InterviewPipeline.process_interview_response()`

2. **Create `agents/researcher.py`** using `compound-beta` + `researcher_prompt()` from prompt_templates.

3. **Wire Supabase saves** in `pipelines/ingest.py` after scoring: call `supabase_store.save_applicant()` and `supabase_store.save_score()`.

4. **Write tests** — `test_scorer.py`, `test_detector.py`, `test_interview.py`.

5. **Wire GROQ_* env vars** — agents should read their model from `.env` instead of hardcoding strings.

6. **Add background purge** for `SessionStore.purge_expired()` via FastAPI lifespan background task.

7. **Fix `/run-interviews`** in `main.py` to actually call `InterviewPipeline.start_interview()` per shortlisted applicant.
