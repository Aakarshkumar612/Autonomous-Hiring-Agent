# 🤖 Autonomous Hiring Agent — Full Project Context
> Paste this entire document into any Claude session to continue where we left off.

---

## 📌 Project Overview

**Project Name:** Autonomous Hiring Agent / HireIQ  
**Type:** AI-powered SaaS hiring platform (production-grade)  
**Status:** Backend 100% complete ✅ | Frontend NOT STARTED 🔄  
**Goal:** End-to-end autonomous hiring system — resume upload → AI scoring → interview → AI detection → hire/reject/hold decision + personalized rejection feedback  
**Location:** `C:\Users\Lenovo\OneDrive\Desktop\Autonomous Hiring Agent\`

---

## 🏗️ Architecture

```
Candidate uploads resume (PDF/DOC/image)
         ↓
IngestPipeline → CSV/portal intake → Applicant model
         ↓
ScorerAgent (Groq llama-3.3-70b) → scores on 5 dimensions (0-100)
         ↓
RankPipeline → shortlisted (≥30) / on-hold / rejected (<20)
         ↓
InterviewPipeline (shortlisted only)
  ├── InterviewerAgent (Groq llama-4-maverick) → 3 rounds
  ├── DetectorAgent (Groq llama-3.1-8b-instant) → AI detection
  └── OrchestratorAgent (Groq llama-3.3-70b) → final verdict
         ↓
FeedbackAgent (RAG/ChromaDB) → explains skill gaps to rejected candidates [NOT BUILT YET]
         ↓
LearnerAgent (deepseek-r1-distill-qwen-32b) → improves system over time
         ↓
Supabase (PostgreSQL) → persists everything
```

---

## ✅ What's Already Built (Backend — 100% Complete)

### Agents (`hiring-agent/agents/`)
| File | Model | Purpose | Status |
|---|---|---|---|
| `scorer.py` | llama-3.3-70b-versatile | Scores resume on 5 dimensions | ✅ Done |
| `interviewer.py` | meta-llama/llama-4-maverick-17b | 3-round autonomous interview | ✅ Done |
| `detector.py` | llama-3.1-8b-instant | Detects AI-generated interview responses | ✅ Done |
| `orchestrator.py` | llama-3.3-70b-versatile | Final hire/reject/hold decision | ✅ Done |
| `learner.py` | deepseek-r1-distill-qwen-32b | Analyses outcomes, improves weights | ✅ Done |

### Models, Connectors, Memory, Pipelines, Utils, main.py
All complete. Import test passed: `All imports OK`

---

## 🧪 Verified Working

1. ✅ All imports pass
2. ✅ Supabase connected: `Connected: True`
3. ✅ Server: `uv run uvicorn main:app --reload` → `http://localhost:8000`
4. ✅ `/health` → 200 OK (groq_key_set: true, supabase_set: true)
5. ✅ `/run-ingest` → scored 3 applicants in 5.84s
6. ✅ `/run-rank` → ranked all 3, percentiles assigned
7. ✅ Swagger UI: `http://localhost:8000/docs`

---

## 🔧 `.env` Config (in `hiring-agent/.env`)

```env
GROQ_API_KEY="gsk_YOUR_GROQ_API_KEY_HERE"
GROQ_ORCHESTRATOR=llama-3.3-70b-versatile
GROQ_SCORER=llama-3.3-70b-versatile
GROQ_INTERVIEWER=meta-llama/llama-4-maverick-17b-128e-instruct
GROQ_DETECTOR=llama-3.1-8b-instant
GROQ_LEARNER=deepseek-r1-distill-qwen-32b
GROQ_RESEARCHER=compound-beta
SUPABASE_URL="https://rvjxehxbplsqutaabjpb.supabase.co"
SUPABASE_KEY="sb_publishable_ZyuUO_4p-fSoryYBi-XMkQ_olENSfs7"   <-- NEEDS service_role key
MAX_APPLICANTS=1000
INTERVIEW_ROUNDS=3
AI_DETECTION_THRESHOLD=0.75
SCORING_BATCH_SIZE=50
SHORTLIST_THRESHOLD=30
AUTO_REJECT_THRESHOLD=20
```

> ⚠️ Get service_role key: Supabase Dashboard → Settings → API → service_role (starts with eyJ...)

---

## 🗂️ Project Structure

```
Autonomous Hiring Agent/
├── hiring-agent/              ← Python FastAPI backend (COMPLETE)
│   ├── agents/                ← scorer, interviewer, detector, orchestrator, learner
│   ├── connectors/            ← supabase_mcp, csv_ingestor, portal_api, resume_parser
│   ├── models/                ← applicant, score, interview
│   ├── memory/                ← pageindex_store, session_store
│   ├── pipelines/             ← ingest, rank, interview_flow
│   ├── utils/                 ← prompt_templates, rate_limiter, logger
│   ├── main.py
│   └── .env
│
└── frontend/                  ← NOT YET BUILT (Next.js + Clerk + Stitch design)
```

---

## 🚀 Full Phase Roadmap

### Phase 1 — Frontend (CURRENT PHASE) 🔄
**Tech:** Next.js 14, Shadcn/ui, Clerk auth, TailwindCSS  
**3-Page Structure (like claude.ai):**
- Page 1 `/` → Landing: project info, architecture, features, CTA
- Page 2 `/sign-in` `/sign-up` → Clerk auth pages
- Page 3 `/dashboard` → The app: resume upload, pipeline status, results

**STEP 1: Google Stitch** → go to https://stitch.withgoogle.com and paste the prompt below  
**STEP 2: Claude Code Prompt 1** → create Next.js app  
**STEP 3: Claude Code Prompt 2** → add Clerk auth  
**STEP 4: Claude Code Prompt 3** → wire API calls to FastAPI

### Phase 2 — RAG Feedback Agent 🔄 NOT STARTED
- `memory/rag_store.py` (ChromaDB)
- `agents/feedback_agent.py` (skills gap analysis)
- `GET /feedback/{applicant_id}` endpoint

### Phase 3 — Image OCR for Resumes 🔄 NOT STARTED
- Groq Vision in `resume_parser.py` for .jpg/.png/.webp

### Phase 4 — CrewAI + AutoGen 🔄 NOT STARTED
- CrewAI: wraps Scorer→Interviewer→Detector→Orchestrator
- AutoGen: 3-agent feedback debate (SkillsAnalyst, CareerCoach, IndustryExpert)

### Phase 5 — Real MCP 🔄 NOT STARTED
- `npx @supabase/mcp-server-supabase`
- Lets Claude directly query Supabase as a tool

### Phase 6 — AWS S3 🔄 NOT STARTED
- `connectors/s3_storage.py` with boto3
- Store resumes in S3, URL in Supabase

### Phase 7 — AWS EC2 Deployment 🔄 NOT STARTED
- Dockerfile + docker-compose + Nginx + CI/CD

---

## 🎨 Google Stitch Prompt

Go to: https://stitch.withgoogle.com — paste this:

```
Design a professional SaaS hiring platform called "HireIQ" — an AI-powered autonomous hiring agent.

DESIGN STYLE: Dark theme like claude.ai or linear.app. Deep navy backgrounds (#0a0f1e, #0f172a), electric blue (#3b82f6) and emerald green (#10b981) accents. Clean, minimal, premium. Inter or Geist font. Glassmorphism cards, subtle gradient glows.

CREATE 3 PAGES:

PAGE 1 — LANDING (/)
Hero:
- Headline: "Hire Smarter, Faster, and Fairer with AI"
- Subtext: "HireIQ autonomously scores resumes, conducts interviews, detects AI-generated responses, and makes data-driven hiring decisions — in minutes, not weeks."
- CTA buttons: "Get Started Free" (blue, primary) | "View Demo" (outlined)
- Animated AI pipeline flow graphic

Features (4 glassmorphism cards):
1. "AI Resume Scoring" — Evaluates technical skills across 5 dimensions
2. "Autonomous Interviews" — 3-round AI interviews (Screening → Technical → Cultural)
3. "AI Detection" — Flags AI-generated responses with confidence scores
4. "Instant Decisions" — Hire, reject, or hold in seconds with reasoning

How It Works (3 steps with arrow connectors):
Step 1: Upload Resume → Step 2: AI Evaluates → Step 3: Get Decision

Architecture diagram (dark card):
Resume Upload → Groq AI Scoring → Interview Agent → AI Detection → Orchestrator → Final Verdict

Stats bar: "1000+ Resumes Processed | 95% Accuracy | 10x Faster | 100% Bias-Free"

Footer

PAGE 2 — AUTH (/sign-in and /sign-up)
- Dark centered card
- "Welcome back to HireIQ" heading
- Email + Password inputs
- "Continue with Google" button
- Toggle between sign-in and sign-up
- HireIQ logo top-left

PAGE 3 — DASHBOARD (/dashboard)
Left sidebar:
- HireIQ logo
- Nav: Dashboard, Upload Resume, Applicants, Results, Settings
- User avatar at bottom

Main content area — 3 views:

VIEW A: Upload Resume
- Drag-drop zone: "Drop resume here (PDF, DOCX, or image)"
- Fields: Full Name, Email, Role (dropdown: SDE/Backend/Frontend/ML Engineer/Data Engineer/DevOps), Experience years (slider 0-15), Skills (tag input), GitHub URL, LinkedIn URL
- "Analyze Resume" button (emerald green, large)

VIEW B: Pipeline Status
- Horizontal timeline: Ingested → Scoring → Ranked → Interviewing → Decision
- Status dots: pending (grey) / active (blue pulsing) / complete (green checkmark)

VIEW C: Results
- Large verdict card: HIRED (green glow) | REJECTED (red glow) | ON HOLD (yellow glow)
- Circular score: 78/100
- Grade badge: A/B/C/D/F
- Percentile: "Top 22% of applicants"
- Strengths list (green checkmarks)
- Weaknesses (red x marks)
- Skill Gap Analysis card (for rejected only):
  - Missing skills as red badges
  - Learning roadmap timeline
  - "Estimated 3 months to qualify"
```

---

## 🤖 Claude Code Prompts Queue

Paste these ONE AT A TIME into Claude Code after Stitch design is done:

### Prompt 1 — Next.js Setup
```
Create a Next.js 14 app with TypeScript in folder "frontend" at:
C:\Users\Lenovo\OneDrive\Desktop\Autonomous Hiring Agent\frontend

Run: npx create-next-app@latest frontend --typescript --tailwind --app --no-src-dir
Then: cd frontend && npx shadcn@latest init
Then: npm install @clerk/nextjs axios

Create these files:
- app/page.tsx (landing page)
- app/(auth)/sign-in/[[...sign-in]]/page.tsx
- app/(auth)/sign-up/[[...sign-up]]/page.tsx
- app/dashboard/page.tsx (protected main app)
- app/dashboard/upload/page.tsx
- app/dashboard/results/[applicant_id]/page.tsx
- middleware.ts (Clerk protection for /dashboard)
- lib/api.ts (axios base URL = http://localhost:8000)
- components/Navbar.tsx
- components/Sidebar.tsx
```

### Prompt 2 — Landing Page (paste Stitch-generated code + this)
```
Build the landing page at app/page.tsx for HireIQ using the design from Google Stitch.
It should include:
- Navbar with logo, nav links (Features, How it works, Pricing), Sign In button
- Hero section with headline, subtext, two CTA buttons
- Features section (4 cards)
- How it works (3 steps)
- Architecture diagram as a styled div
- Stats bar
- Footer
Use Shadcn/ui components. Dark theme with blue/green accents. Fully responsive.
```

### Prompt 3 — RAG Feedback Backend
```
Add ChromaDB RAG feedback system to hiring-agent backend:

1. pip install chromadb (add to pyproject.toml)

2. Create hiring-agent/memory/rag_store.py:
   - ChromaDB persistent store at ./chroma_data/
   - Pre-populate with 60 role requirement documents
   - Roles: SDE, Backend, Frontend, ML Engineer, Data Engineer, DevOps
   - search(role, query) method returning top_k docs

3. Create hiring-agent/agents/feedback_agent.py:
   - AsyncGroq llama-3.3-70b
   - Input: applicant_skills, target_role, score, rejection_reason
   - Query RAG, generate FeedbackReport with:
     missing_skills, recommended_courses, learning_roadmap (month-by-month), 
     estimated_gap_months, personalized_message, target_companies
   - Warm, encouraging tone in the message

4. Add to main.py:
   GET /feedback/{applicant_id}
```

### Prompt 4 — CrewAI Integration
```
Wrap the existing hiring pipeline with CrewAI.
Keep all agent files unchanged — only wrap them.

Install: uv add crewai

Create hiring-agent/crew/hiring_crew.py:
- 4 CrewAI Agents: ScoringAgent, InterviewAgent, DetectionAgent, DecisionAgent
- Each wraps the corresponding existing agent class
- 4 sequential Tasks
- HiringCrew class with async run(applicant) method
- Process.sequential

Create hiring-agent/crew/feedback_crew.py:
- 3 AutoGen AssistantAgents: SkillsAnalyst, CareerCoach, IndustryExpert
- GroupChat with 3 rounds of debate about candidate gaps
- Returns merged feedback report
```

---

## 🛠️ Run Commands

```powershell
# Backend
cd "C:\Users\Lenovo\OneDrive\Desktop\Autonomous Hiring Agent\hiring-agent"
uv run uvicorn main:app --reload
# → http://localhost:8000/docs

# Frontend (once built)
cd "C:\Users\Lenovo\OneDrive\Desktop\Autonomous Hiring Agent\frontend"
npm run dev
# → http://localhost:3000
```

---

## 💡 How to Continue in a New Claude Session

1. Paste this entire file at the start of any Claude conversation
2. Say: "I'm continuing the Autonomous Hiring Agent / HireIQ project. Backend is 100% complete and tested. I need to continue Phase 1 — building the Next.js frontend. I've used Google Stitch to get the design. Help me continue."
3. Claude will have all context needed to continue immediately
