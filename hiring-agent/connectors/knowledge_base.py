"""
connectors/knowledge_base.py
═══════════════════════════════════════════════════════
Static knowledge base for the HireIQ platform chatbot.

WHY THIS EXISTS
───────────────
The chatbot's job is to answer questions about HireIQ — how to use it,
what each feature does, and how to fix problems. This knowledge never
changes during a session, so it lives here as structured Python data,
not in a database.

HOW RETRIEVAL WORKS (Keyword-Filtered In-Context RAG)
──────────────────────────────────────────────────────
1. User sends a message: "how do I upload my resume?"
2. retrieve() lowercases the query and counts how many of each entry's
   tags appear in it. "upload" matches the upload entry's tags.
3. Top 4 matching entries are formatted as context and injected into
   the LLM prompt alongside the conversation history.
4. If NO tags match at all (totally off-topic query), the top 3
   "overview" entries are returned so the bot can still respond.

WHY NOT EMBEDDINGS?
───────────────────
Embeddings require either a local model (adds 300 MB) or an external
API (adds latency + cost). For a ~20-entry knowledge base about a
single platform, keyword matching is faster, cheaper, and just as
accurate. The LLM does the semantic reasoning — retrieval just narrows
the context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KBEntry:
    """A single knowledge base article."""
    id:       str
    title:    str
    content:  str
    tags:     list[str]   # lowercase keywords used for retrieval scoring
    category: str         # "overview" | "how_to" | "feature" | "troubleshoot" | "concept"


# ─── Knowledge Base ───────────────────────────────────────────────────────────
# Each entry is self-contained — the LLM should be able to answer a question
# using ONLY the content of the retrieved entries + conversation history.

KNOWLEDGE_BASE: list[KBEntry] = [

    KBEntry(
        id="hireiq_overview",
        title="What is HireIQ?",
        category="overview",
        tags=["hireiq", "what", "about", "overview", "platform", "project", "autonomous", "hiring", "agent", "ai"],
        content="""
HireIQ is an Autonomous AI Hiring Agent — a platform that handles the entire hiring process end-to-end using artificial intelligence.

What it does:
- Accepts job applications (resumes, cover letters, certificates) from candidates
- Automatically scores and ranks every applicant using 5 key dimensions
- Conducts live AI-powered interviews (3 rounds: Screening, Technical, Cultural)
- Detects AI-generated or plagiarised interview responses
- Verifies candidate profiles against public sources (GitHub, portfolio)
- Makes final hiring decisions (Accept / Reject / On Hold) autonomously
- Learns from outcomes to improve over time

Who uses it: HR managers, recruiters, and hiring teams who want to screen large numbers of applicants quickly and fairly without spending hours on manual review.

The platform is powered entirely by Groq's LLM API. Different AI models are assigned to different tasks — a fast model for detection, a powerful model for scoring and decisions.
        """.strip(),
    ),

    KBEntry(
        id="submit_application",
        title="How to Submit a Job Application (Upload Resume)",
        category="how_to",
        tags=["submit", "apply", "application", "upload", "resume", "form", "candidate", "how", "start", "fill", "enter"],
        content="""
To submit a job application on HireIQ:

Step 1 — Go to the Upload Resume page
  Click "Upload Resume" in the left sidebar.

Step 2 — Upload your document (optional but recommended)
  Click the big upload area or drag and drop your file.
  Accepted formats: PDF, DOCX, JPEG, PNG, WEBP
  Maximum file size: 10 MB

Step 3 — Fill in the candidate information form (right side):
  • Full Name* — the applicant's full name
  • Email Address* — must be a valid email, must be unique (no duplicates)
  • Phone Number — optional
  • Target Role* — pick from the dropdown (e.g. Senior Software Engineer, ML Engineer)
  • GitHub URL — optional but helps with profile verification
  • LinkedIn URL — optional
  • Experience Level — drag the slider (0–20 years)
  • Core Skills — type a skill and press Enter to add it. Or click the suggested chips below.

Step 4 — Click "Analyze Resume"
  The AI will process the application and show a success banner with your Application ID (e.g. APP-A1B2C3D4).
  Save this ID — you'll need it to start an interview later.

* = Required field
        """.strip(),
    ),

    KBEntry(
        id="accepted_formats",
        title="Accepted File Formats and Size Limits",
        category="how_to",
        tags=["format", "file", "pdf", "docx", "jpeg", "jpg", "png", "webp", "size", "limit", "mb", "upload", "accept", "type", "extension"],
        content="""
HireIQ accepts the following document formats for resume/document uploads:

Text-based formats:
  • PDF (.pdf) — Most common. Best quality for text extraction.
  • DOCX (.docx) — Microsoft Word format. Also well supported.

Image-based formats (scanned documents):
  • JPEG / JPG (.jpg, .jpeg) — Scanned resumes, photos of certificates.
  • PNG (.png) — High quality scans.
  • WEBP (.webp) — Modern web image format.

File size limit: Maximum 10 MB per upload.

Why the limit? 10 MB is more than enough for any resume or certificate. Larger files slow down the AI processing and waste storage space. A typical 3-page PDF resume is around 200 KB–2 MB.

What happens if you upload an image?
  HireIQ uses a Vision AI model (llama-4-scout) to read (OCR) the text from your image AND classify the document type — all in one step. So scanned documents work just as well as digital PDFs.

What formats are NOT accepted?
  ZIP files, EXE files, spreadsheets (XLSX), PowerPoints, or any random non-document file. The system will reject them immediately with an error message.
        """.strip(),
    ),

    KBEntry(
        id="document_validation",
        title="Document Validation — Why Was My File Rejected?",
        category="troubleshoot",
        tags=["rejected", "invalid", "document", "validation", "error", "not accepted", "wrong", "selfie", "photo", "meme", "joke", "reject"],
        content="""
HireIQ validates every uploaded document before accepting it. There are two checks:

Check 1 — Format Gate (instant):
  Verifies the file type is one of: PDF, DOCX, JPEG, PNG, WEBP.
  Rejects: ZIP, EXE, Excel, PowerPoint, random files.

Check 2 — Content Gate (AI-powered, ~100ms):
  An AI model reads your document and checks: "Is this a real hiring document?"
  Only these types are accepted:
    • Resume / CV
    • Cover Letter
    • Offer Letter
    • Internship Certificate
    • Experience Letter

Common rejection reasons and fixes:
  ❌ "File too large" → Your file exceeds 10 MB. Compress it using a free PDF compressor online.
  ❌ "Not a valid hiring document" → You uploaded something that isn't a resume or letter. Use the correct document.
  ❌ "Image does not contain readable text" → Your photo is blurry or has no document text. Take a clearer scan.
  ❌ "Unsupported file format" → Wrong file type. Convert to PDF or JPEG first.

Why so strict? To prevent garbage data from entering the system. Random files would produce nonsense AI scores and waste processing time.
        """.strip(),
    ),

    KBEntry(
        id="application_id",
        title="What is an Application ID and Where to Find It?",
        category="how_to",
        tags=["application id", "app id", "id", "find", "where", "applicant id", "APP-"],
        content="""
Every applicant in HireIQ gets a unique Application ID in the format: APP-XXXXXXXX
Example: APP-A1B2C3D4

Where to find it:
  1. After submitting an application — the green success banner shows the ID.
  2. On the Applications page — every row shows the applicant's ID.
  3. In the URL bar when viewing an individual applicant.

What you need it for:
  • To start a live interview session — you paste the ID into the "Start Interview" page.
  • To look up a specific applicant via the API.
  • To track the application through the pipeline.

What if you lose the ID?
  Go to the Applications page (/dashboard/applications). Find the applicant by name or email. Their ID is shown in the table.
        """.strip(),
    ),

    KBEntry(
        id="start_interview",
        title="How to Start a Live Interview",
        category="how_to",
        tags=["interview", "start", "begin", "live", "session", "applicant id", "how", "conduct"],
        content="""
To start a live interview session:

Step 1 — Go to Live Interview
  Click "Live Interview" in the sidebar (it has a LIVE badge).

Step 2 — Enter the Applicant ID
  Type the applicant's ID (e.g. APP-A1B2C3D4) in the input box.
  You can press Enter or click "Start Interview".

Step 3 — The interview begins
  The AI Interviewer asks the first question.
  The left panel shows your progress through the 3 rounds:
    • Round 1: Screening (general background, motivation)
    • Round 2: Technical (role-specific skills, problem-solving)
    • Round 3: Cultural (team fit, values, communication style)

Step 4 — Answer questions
  Type the applicant's answer in the text box.
  Press Enter to send (or Shift+Enter for a new line).
  The AI asks follow-up questions or moves to the next one.

Step 5 — Interview completes
  After all 3 rounds (typically 15 questions total, 5 per round), the AI shows:
    • ACCEPTED / REJECTED / ON HOLD verdict
    • Confidence percentage
    • Reasoning summary
    • Next action recommendation

Note: The applicant must already be in the system (submitted via Upload Resume or CSV) before you can interview them.
        """.strip(),
    ),

    KBEntry(
        id="interview_rounds",
        title="The 3 Interview Rounds Explained",
        category="feature",
        tags=["round", "screening", "technical", "cultural", "interview", "questions", "three", "rounds", "what"],
        content="""
HireIQ conducts interviews in 3 rounds, each with a different focus:

Round 1 — Screening (5 questions)
  Focus: Is this person who they claim to be? Are they genuinely interested?
  Topics: Background, career history, motivation for the role, self-assessment.
  Example question: "Walk me through your professional journey and what brings you to this role."

Round 2 — Technical (5 questions)
  Focus: Can they actually do the job?
  Topics: Role-specific skills, problem-solving, technical knowledge, past projects.
  Example question: "Describe a time you had to optimize a database query under heavy load. What was your approach?"

Round 3 — Cultural (5 questions)
  Focus: Will they fit well with the team?
  Topics: Teamwork, communication style, handling conflict, values alignment.
  Example question: "Tell me about a time you disagreed with a team decision. How did you handle it?"

Each round is evaluated separately. The Orchestrator Agent then combines all 3 round summaries with the original resume score to make the final verdict.

Total questions: ~15 (can vary slightly with follow-up questions for short answers).
        """.strip(),
    ),

    KBEntry(
        id="interview_verdict",
        title="How to Read Interview Results (Accept/Reject/Hold)",
        category="how_to",
        tags=["verdict", "result", "accept", "reject", "hold", "decision", "outcome", "confidence", "complete", "interview result"],
        content="""
When an interview completes, you see a verdict card with three possible outcomes:

✅ ACCEPTED (green)
  The candidate performed well across all 3 rounds and the AI recommends hiring them.
  Confidence: How sure the AI is (e.g. 87% means fairly confident).
  Next action: Usually "send_offer" — proceed with an offer letter.

❌ REJECTED (red)
  The candidate did not meet the bar. Significant gaps in technical skills, experience, or cultural fit.
  Next action: Usually "send_rejection" — notify the candidate politely.

⏸ ON HOLD (yellow/amber)
  The candidate showed mixed signals — good in some areas, weak in others.
  Next action: Usually "schedule_human_review" — have a human interviewer look at the transcript.

What does Confidence mean?
  It's the AI's certainty from 0–100%. A 95% REJECTED is very clear. A 51% ON HOLD means the AI was nearly split — definitely worth human review.

Where to see past interview transcripts?
  At the bottom of the verdict screen, a full transcript of all messages is shown.
  You can also check the Applications page for the updated status.
        """.strip(),
    ),

    KBEntry(
        id="scoring_system",
        title="How the AI Scoring System Works",
        category="feature",
        tags=["score", "scoring", "dimension", "rank", "points", "grade", "evaluation", "criteria", "how scored", "assessment"],
        content="""
Every applicant is scored across 5 dimensions before they can be interviewed:

1. Technical Skills (0–100)
   Does the applicant have the specific tech skills required for the role?
   Example: A backend engineer role checks for Python, databases, API design.

2. Experience (0–100)
   Is the applicant's experience level appropriate? Do their past roles match?

3. Problem Solving (0–100)
   Based on resume projects and descriptions — can they solve complex problems?

4. Communication (0–100)
   Clarity of writing in the resume and cover letter.

5. Cultural Fit (0–100)
   Values alignment, team player signals, and leadership indicators.

Final score = weighted average of all 5 dimensions.

Grades:
  A (85–100) — Excellent
  B (70–84)  — Good
  C (55–69)  — Average
  D (40–54)  — Below average
  F (0–39)   — Does not meet requirements

After scoring, applicants are ranked and split into:
  • Shortlisted — score above the shortlist threshold (default: 30th percentile and above)
  • On Hold    — borderline scores
  • Rejected   — below the auto-reject threshold (default: 20th percentile)

The thresholds are configurable in the .env file (SHORTLIST_THRESHOLD, AUTO_REJECT_THRESHOLD).
        """.strip(),
    ),

    KBEntry(
        id="application_status",
        title="What Do the Application Statuses Mean?",
        category="concept",
        tags=["status", "pending", "shortlisted", "accepted", "rejected", "on hold", "meaning", "what does"],
        content="""
Every applicant has a status that shows where they are in the hiring pipeline:

⏳ Pending
  Just submitted. Waiting to be scored. No AI analysis has run yet.

⭐ Shortlisted
  Scored and ranked. This applicant scored high enough to proceed to interviews.
  They haven't been interviewed yet.

✅ Accepted
  Interview complete. The AI (Orchestrator Agent) decided to hire this person.
  Recommended action: send an offer letter.

❌ Rejected
  Either scored too low to be shortlisted, OR completed the interview and was not selected.
  Recommended action: send a polite rejection email.

⏸ On Hold
  The AI was uncertain. Needs human review before a final decision.
  Check the interview transcript and score breakdown for context.

How does an applicant move through statuses?
  1. Submit application → Pending
  2. Run /run-ingest (scoring) → Shortlisted, On Hold, or Rejected (by score)
  3. Run interview → Accepted, Rejected, or On Hold (by interview performance)

You can also manually update a status from the Applications page.
        """.strip(),
    ),

    KBEntry(
        id="ai_detection",
        title="What is AI Detection and Why It Matters",
        category="concept",
        tags=["ai detection", "ai generated", "plagiarism", "detector", "flagged", "ai flag", "cheat", "cheating", "fake", "detection"],
        content="""
HireIQ has a built-in AI Detection system that runs on every interview response.

What it detects:
  • AI-generated text (ChatGPT, Claude, Gemini-style responses)
  • Plagiarised answers copied from the internet
  • Unnaturally perfect, generic responses with no personal experience

How it works:
  After the applicant submits each interview answer, the Detector Agent analyses it.
  It looks for patterns like: overly structured bullet points, no specific details, corporate-speak, lack of personal storytelling.
  It returns: verdict (ai_generated / human / uncertain) + confidence score.

What you see in the interview UI:
  If an answer is flagged: a red warning banner appears in the chat:
  "⚠️ AI-generated content detected in this response."

Does it auto-reject flagged candidates?
  No — it's a signal, not an automatic disqualifier. The Orchestrator Agent considers AI flags as part of its final decision alongside scores and interview quality.
  High confidence AI flags do lower the final verdict confidence significantly.

Why this matters:
  It ensures you're evaluating the real candidate, not their AI tool. Hiring someone who can't actually do the work they claim is costly.
        """.strip(),
    ),

    KBEntry(
        id="bulk_upload",
        title="How to Bulk Upload Multiple Applicants via CSV",
        category="how_to",
        tags=["bulk", "csv", "excel", "multiple", "batch", "import", "upload many", "spreadsheet", "mass"],
        content="""
You can import multiple applicants at once by uploading a CSV or Excel file.

Where to access it:
  The bulk upload is available via the API at POST /portal/apply/bulk.
  Or use the main /run-ingest endpoint which accepts a CSV file directly.

Required columns in your CSV:
  • name — full name of the applicant
  • email — email address (must be unique)
  • role — role code (sde, backend, frontend, ml_engineer, data_engineer, devops, fullstack, ai_researcher)
  • experience — number of years (e.g. 5)

Optional columns:
  • phone — phone number
  • skills — pipe-separated skills: Python|FastAPI|Docker
  • github — GitHub profile URL
  • portfolio — portfolio website URL
  • linkedin — LinkedIn profile URL
  • cover_letter — text of cover letter
  • education — education details
  • location — city/country

File formats: .csv or .xlsx (Excel)

After uploading:
  The system tells you: total rows processed, successfully imported, errors (with details), and duplicates skipped.
  All imported applicants start with Pending status. Run /run-ingest to score them all.
        """.strip(),
    ),

    KBEntry(
        id="pipeline_flow",
        title="The Full Hiring Pipeline — Step by Step",
        category="overview",
        tags=["pipeline", "flow", "process", "step", "ingest", "rank", "interview", "learn", "how it works", "end to end"],
        content="""
The HireIQ pipeline has 4 main stages you run in order:

Stage 1: Ingest (POST /run-ingest)
  Upload a CSV file of applicants. The system:
  • Parses every applicant
  • Scores each one across 5 dimensions (Scorer Agent)
  • Verifies profiles for top candidates (Researcher Agent — checks GitHub etc.)
  • Stores everything in the database
  Output: shortlisted / on_hold / rejected applicants

Stage 2: Rank (POST /run-rank)
  Re-ranks all scored applicants using percentile thresholds.
  You can set custom thresholds for shortlisting.
  Output: ordered shortlist ready for interviews

Stage 3: Interviews (POST /run-interviews)
  Starts automated interview sessions for shortlisted applicants.
  Runs up to 5 concurrent sessions.
  You can also run manual interviews via the Live Interview page.
  Output: accepted / rejected / on_hold with full transcripts

Stage 4: Learn (POST /run-learn)
  The Learner Agent analyses all hiring outcomes.
  It recommends: adjust scoring weights, new red flags to watch for, interview question improvements.
  Output: actionable recommendations for improving the pipeline

You don't have to run all 4 stages — you can use just the manual interview flow if you prefer.
        """.strip(),
    ),

    KBEntry(
        id="researcher_agent",
        title="What Does the Researcher Agent Do?",
        category="feature",
        tags=["researcher", "research", "github", "verify", "verification", "credibility", "profile", "online", "web"],
        content="""
The Researcher Agent is an optional enrichment step that runs on shortlisted applicants.

What it does:
  • Checks the applicant's GitHub profile (if provided): looks at repo count, recent activity, project quality, contribution consistency
  • Checks their portfolio or personal website for legitimacy
  • Cross-references claimed skills against what's visible publicly
  • Looks for any red flags (gaps, inconsistencies, exaggerated claims)

How it works technically:
  It uses Groq's compound-beta model which has built-in web search capability. It can actually browse URLs and search the internet during analysis — no scraping code needed.

Output:
  • credibility_score (0–10): How credible the applicant's claims appear to be
  • skill_match_score (0–1): Whether their public work matches claimed skills
  • red_flags: List of concerns found (e.g. "GitHub last active 3 years ago despite claiming active open source work")

How it affects the process:
  Red flags from research are appended to the applicant's profile weaknesses. The Orchestrator considers them in the final interview verdict. A credibility score below 3/10 is a strong negative signal.
        """.strip(),
    ),

    KBEntry(
        id="learner_agent",
        title="What is the Learner Agent?",
        category="feature",
        tags=["learner", "learn", "improve", "recommendations", "analysis", "insights", "feedback", "adapt"],
        content="""
The Learner Agent analyses historical hiring outcomes and recommends improvements to the system.

When to use it:
  After you've processed at least 20–30 applicants through the full pipeline. The more data, the better its recommendations.

How to trigger it:
  POST /run-learn (via the API)

What it analyses:
  • How many applicants were accepted vs rejected vs on hold
  • Average scores of accepted vs rejected candidates
  • Common red flags that appeared in rejected candidates
  • Interview patterns in accepted vs rejected transcripts

What it recommends:
  • Scoring weight adjustments: "Technical Skills is under-weighted for ML Engineer roles — increase from 20% to 30%"
  • New red flags to flag: "Candidates with fewer than 2 active GitHub repos in the last year have a 80% rejection rate"
  • Interview improvements: "Round 2 Technical questions are too easy — accepted and rejected candidates score similarly"
  • Threshold adjustments: "Current shortlist threshold too low — many shortlisted candidates fail interviews"

The recommendations are informational. You apply them by adjusting your .env config or prompt templates.
        """.strip(),
    ),

    KBEntry(
        id="dashboard_navigation",
        title="How to Navigate the Dashboard",
        category="how_to",
        tags=["dashboard", "navigate", "sidebar", "menu", "page", "where", "find", "go to"],
        content="""
The dashboard has the following pages accessible from the left sidebar:

📊 Dashboard (/dashboard)
  Main overview with KPI cards, pipeline progress, and top candidates.

📤 Upload Resume (/dashboard/upload)
  Submit individual applications with a form and file upload.

📋 Applications (/dashboard/applications)
  Table view of all applicants. Filter by status and role. View individual profiles.

📈 Results (/dashboard/results)
  Hiring decision analysis. Score breakdowns by dimension.

🎙 Live Interview (/dashboard/interview)
  Start and conduct AI-powered interviews. Shows the LIVE badge.

🤖 AI Chatbot (/dashboard/chatbot)
  That's here — you're talking to it right now!

📜 History (/dashboard/history)
  Timeline of all hiring events (batches scored, interviews completed, etc.)

⚙️ Settings (/dashboard/settings)
  Configure pipeline thresholds, notification preferences, API keys.

❓ Help (/dashboard/help)
  FAQ section with common questions.

At the bottom of the sidebar:
  🔔 Notifications — alerts for completed jobs and important events
  👤 Profile — your HR manager profile

Top right of every page:
  Search bar, notification bell, user menu (sign out, settings).
        """.strip(),
    ),

    KBEntry(
        id="troubleshoot_common",
        title="Common Problems and How to Fix Them",
        category="troubleshoot",
        tags=["error", "problem", "fix", "issue", "not working", "fail", "broken", "trouble", "crash", "help", "wrong"],
        content="""
Common problems and their fixes:

❌ "Application already exists for email"
  → Each email can only be used once. If re-testing, use a different email address.

❌ "Applicant not found" when starting interview
  → The Application ID is wrong. Go to Applications page, find the applicant, copy their correct ID.

❌ "Session not found or expired" during interview
  → Interview sessions expire after 24 hours of inactivity. Start a new interview session.

❌ File upload shows "File too large"
  → Your file exceeds 10 MB. Compress it: for PDFs use ilovepdf.com, for images use squoosh.app.

❌ File upload shows "Not a valid hiring document"
  → You uploaded something that isn't a resume or hiring document. The AI checked the content and rejected it. Upload a real resume/CV/cover letter.

❌ Interview won't start — "Failed to start interview session"
  → The backend AI (Groq) may be temporarily unavailable. Wait 30 seconds and try again.

❌ Scores seem wrong / too low
  → The AI scores based on the resume text it extracted. If the resume text was extracted poorly (e.g. from a very formatted PDF), the score may be lower. Try uploading a simpler PDF or add skills manually in the form.

❌ Dashboard shows no applicants
  → You may be on a fresh server. Applicants are loaded from Supabase on startup. If Supabase isn't configured, only in-session data is visible.
        """.strip(),
    ),

    KBEntry(
        id="groq_models",
        title="Which AI Models Power HireIQ?",
        category="concept",
        tags=["model", "groq", "llm", "ai model", "llama", "deepseek", "which model", "powered by"],
        content="""
HireIQ uses different Groq LLM models for different tasks, each chosen for the right balance of speed and intelligence:

🧮 Scorer (llama-3.3-70b-versatile)
  Most capable Groq model. Used for complex evaluation of 5 scoring dimensions.

🎙 Interviewer (llama-4-maverick-17b-128e-instruct)
  Fast and conversational. Llama 4 generation model. Generates natural interview questions.

🔍 Detector (llama-3.1-8b-instant)
  Fastest, cheapest model. Used for the quick AI detection check after each response.

🌐 Researcher (compound-beta)
  Special model with built-in web search. Can actually browse the internet to verify profiles.

🧠 Learner (deepseek-r1-distill-qwen-32b)
  Deep reasoning model. Used for complex outcome analysis and recommendations.

🎯 Orchestrator (llama-3.3-70b-versatile)
  Same powerful model as scorer. Makes the final hire/reject/hold decision.

💬 Chatbot (llama-3.3-70b-versatile)
  The model you're talking to right now. Best for clear, helpful explanations.

All models run on Groq's infrastructure — designed for ultra-low latency (typically under 1 second per response).
        """.strip(),
    ),

    KBEntry(
        id="data_privacy",
        title="Data Privacy and Security",
        category="concept",
        tags=["privacy", "data", "security", "safe", "store", "supabase", "credentials", "personal", "gdpr"],
        content="""
How HireIQ handles data:

Where data is stored:
  • Supabase (PostgreSQL) — applicant profiles, scores, interview transcripts, session data
  • In-memory cache — fast lookup during the server's active session
  • Groq API — resume text and interview responses are sent to Groq for AI processing

What is sent to Groq:
  • Resume text (first 500 characters for scoring, full text for research)
  • Interview questions and responses (for evaluation)
  • Document images (for OCR validation)
  Groq processes this data according to their privacy policy. No data is stored permanently on Groq's servers.

API keys:
  • GROQ_API_KEY and SUPABASE_KEY are stored in .env files
  • These should NEVER be committed to version control
  • Add .env to your .gitignore

Resume file storage:
  Only the extracted text from resumes is stored — not the original file. The raw bytes are processed and discarded.

Recommendations:
  • Use environment variables for all credentials
  • Enable Supabase Row Level Security (RLS) in production
  • Rotate API keys periodically
        """.strip(),
    ),

    KBEntry(
        id="skills_input",
        title="How to Add Skills to an Application",
        category="how_to",
        tags=["skills", "add skill", "tag", "remove skill", "skill input", "enter", "suggested"],
        content="""
Adding skills to an application on the Upload Resume page:

Method 1 — Type and press Enter:
  Click the skills input box at the bottom of the form.
  Type a skill name (e.g. "TensorFlow") and press Enter or comma.
  The skill appears as a blue tag above the input.

Method 2 — Click suggested chips:
  Below the skills box are pre-suggested skills (Python, React, FastAPI, etc.)
  Click any chip to instantly add it.

Removing a skill:
  Click the × button on any skill tag to remove it.

Skills from your resume:
  If you upload a resume, the AI automatically extracts tech skills it finds in the document. These are merged with the skills you enter manually. Duplicates are removed.

How many skills to add?
  There's no hard limit. Add all relevant skills. The Scorer Agent looks for specific skills based on the target role — missing key skills for a role will lower the Technical Skills dimension score.

Tips:
  • Be specific: "PostgreSQL" is better than "databases"
  • Include both languages AND frameworks: Python AND Django/FastAPI
  • Don't add soft skills here — they come out in the interview, not the score
        """.strip(),
    ),

]


# ─── Retrieval Function ───────────────────────────────────────────────────────

def retrieve(query: str, k: int = 4) -> list[KBEntry]:
    """
    Return the top-k most relevant KB entries for a user query.

    Algorithm:
      1. For each entry, count how many of its tags appear in the query string.
      2. Also add 2 points for each word of the query that appears in the title.
      3. Sort by score descending.
      4. If no entry scores above 0, fall back to all "overview" category entries.

    Why this works:
      The LLM doing the final answer is smart enough to use context it's
      given. Our job is just to narrow the ~20 entries down to the 4 most
      relevant. Keyword overlap is sufficient for this bounded domain.

    Args:
        query: The user's message.
        k:     Maximum number of entries to return (default 4).

    Returns:
        List of KBEntry objects, most relevant first.
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored: list[tuple[int, KBEntry]] = []
    for entry in KNOWLEDGE_BASE:
        score = 0
        # Tag match: each tag that appears anywhere in the query
        for tag in entry.tags:
            if tag in query_lower:
                score += 1
        # Title match: each query word that appears in the title
        title_lower = entry.title.lower()
        for word in query_words:
            if len(word) > 2 and word in title_lower:
                score += 2
        if score > 0:
            scored.append((score, entry))

    if scored:
        scored.sort(key=lambda x: -x[0])
        return [entry for _, entry in scored[:k]]

    # Fallback: return overview entries so the bot can still respond
    return [e for e in KNOWLEDGE_BASE if e.category == "overview"][:3]


def format_context(entries: list[KBEntry]) -> str:
    """Format retrieved entries into a context block for the LLM prompt."""
    if not entries:
        return "No specific knowledge base entries retrieved."
    sections = []
    for entry in entries:
        sections.append(f"### {entry.title}\n{entry.content}")
    return "\n\n".join(sections)
