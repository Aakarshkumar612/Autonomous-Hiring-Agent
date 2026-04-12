# 🤖 HireIQ — Autonomous AI Hiring Agent

> End-to-end AI-powered hiring platform that autonomously scores resumes, conducts 3-round interviews, detects AI-generated responses, and makes data-driven hiring decisions.

---

## 🏗️ Architecture

```
Resume Upload → AI Scoring → Ranking → Autonomous Interview → AI Detection → Final Decision
```

All LLM calls are routed through **Groq** for maximum speed.

| Agent | Model | Role |
|---|---|---|
| Scorer | llama-3.3-70b-versatile | Evaluates resume on 5 dimensions |
| Interviewer | llama-4-maverick | Conducts 3-round interviews |
| Detector | llama-3.1-8b-instant | Detects AI-generated answers |
| Orchestrator | llama-3.3-70b-versatile | Makes final hire/reject/hold decision |
| Learner | deepseek-r1-distill-qwen-32b | Improves system from historical data |

---

## 🚀 Tech Stack

- **Backend:** FastAPI + Python 3.12 + uv
- **LLMs:** Groq (llama-3.3-70b, llama-4-maverick, deepseek-r1)
- **Database:** Supabase (PostgreSQL)
- **Frontend:** Next.js 14 + Shadcn/ui + Clerk Auth *(coming soon)*
- **Multi-agent:** CrewAI + AutoGen *(planned)*
- **Storage:** AWS S3 *(planned)*
- **Deployment:** AWS EC2 + Docker *(planned)*

---

## ⚡ Quick Start

### 1. Clone and install
```bash
git clone https://github.com/Aakarshkumar612/Autonomous-Hiring-Agent.git
cd Autonomous-Hiring-Agent/hiring-agent
```

### 2. Set up environment
```bash
cp .env.example .env
# Fill in your API keys in .env
```

### 3. Install dependencies
```bash
# Install uv first: https://docs.astral.sh/uv/
uv sync
```

### 4. Run the server
```bash
uv run uvicorn main:app --reload
```

### 5. Open API docs
```
http://localhost:8000/docs
```

---

## 📋 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check + system stats |
| POST | `/run-ingest` | Upload CSV and score all applicants |
| POST | `/run-rank` | Rank all scored applicants |
| POST | `/run-interviews` | Start interview sessions for shortlisted |
| POST | `/portal/apply` | Submit single application with resume |
| POST | `/portal/apply/bulk` | Bulk upload CSV/Excel |
| GET | `/portal/applicants` | List all applicants |

---

## 📁 Project Structure

```
hiring-agent/
├── agents/          # AI agents (scorer, interviewer, detector, orchestrator, learner)
├── connectors/      # Supabase, CSV ingestor, portal API, resume parser
├── models/          # Pydantic models (applicant, score, interview)
├── memory/          # PageIndex store, session store
├── pipelines/       # Ingest, rank, interview flow pipelines
├── utils/           # Prompt templates, rate limiter, logger
└── main.py          # FastAPI entry point
```

---

## 🔧 Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
GROQ_API_KEY=your_groq_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_service_role_key
```

---

## 📊 Current Status

- ✅ Backend fully built and tested
- ✅ All agents working (Groq API)
- ✅ Supabase connected
- ✅ CSV ingest pipeline working
- ✅ Frontend (Next.js) — in progress
- ✅ RAG feedback agent — planned
- 🔄 AWS S3 + EC2 deployment — planned

---

## 👨‍💻 Author

**Aakarsh Kumar** — [@Aakarshkumar612](https://github.com/Aakarshkumar612)
