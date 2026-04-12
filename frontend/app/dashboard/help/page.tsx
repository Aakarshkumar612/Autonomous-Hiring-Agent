'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'

// ─── Data ──────────────────────────────────────────────────────────────────

const FAQS = [
  // Upload & Resume
  {
    category: 'Upload & Resume',
    q: 'What file formats does HireIQ accept?',
    a: 'HireIQ accepts PDF, DOCX, JPEG, PNG, and WEBP files up to 10 MB. PDF and DOCX files are parsed directly. Image files (JPEG, PNG, WEBP) are processed through Vision OCR which extracts all text from the document before analysis.',
  },
  {
    category: 'Upload & Resume',
    q: 'Why was my file rejected as "not a hiring document"?',
    a: 'HireIQ runs a two-gate validation on every upload. First it checks the file type. Then the AI reads the content and verifies it is actually a resume or CV — not an invoice, article, or random document. If your legitimate resume was rejected, try re-uploading as a PDF (most reliable format) or fill in the candidate details manually in the form instead.',
  },
  {
    category: 'Upload & Resume',
    q: 'Is the resume required, or can I submit without one?',
    a: 'The resume file is optional. You can submit a candidate with just the form fields: Full Name, Email, Role, Experience, and Skills. The AI will score based on the structured data you provide. Attaching a resume gives the AI richer context and usually produces a more accurate score.',
  },
  {
    category: 'Upload & Resume',
    q: 'How long does processing take after I submit?',
    a: 'Resume analysis and scoring typically completes in 10–30 seconds depending on document length. During peak load it may take up to 60 seconds. You will see the applicant appear on the Applications page with a "Pending" status while the AI pipeline is running.',
  },

  // Scoring & Grading
  {
    category: 'Scoring & Grading',
    q: 'How does the AI calculate a candidate\'s score?',
    a: 'HireIQ scores candidates across five weighted dimensions: Technical Skills (30%), Relevant Experience (25%), Problem Solving (20%), Communication Quality (15%), and Cultural Fit (10%). Each dimension is scored 0–100 by the AI, then combined into a final weighted total. The final score drives automatic shortlisting and rejection decisions.',
  },
  {
    category: 'Scoring & Grading',
    q: 'What do the letter grades mean?',
    a: 'Grades are derived from the final score: A+ (95–100) — exceptional, fast-track to interview; A (85–94) — strong candidate, recommend interview; B (70–84) — good candidate, consider for next round; C (60–69) — borderline, review manually; D (50–59) — below expectations; F (below 50) — does not meet minimum requirements.',
  },
  {
    category: 'Scoring & Grading',
    q: 'What does "Shortlisted" vs "Pending" vs "On Hold" mean?',
    a: '"Pending" means the AI pipeline is still processing the application. "Shortlisted" means the candidate scored above your Shortlist Threshold (default: 30) and is ready for interview. "On Hold" means the score is between the rejection and shortlist thresholds — requires manual review. "Rejected" means the score fell below the Auto-reject Threshold (default: 20). "Hired" is set after a successful interview verdict.',
  },
  {
    category: 'Scoring & Grading',
    q: 'Can I change the shortlist and rejection thresholds?',
    a: 'Yes. Go to Settings → Pipeline Config. You can adjust the Shortlist Threshold (minimum score to be shortlisted), Auto-reject Threshold (scores below this are automatically rejected), Interview Rounds (1–5), and AI Detection Sensitivity. Changes take effect on all future submissions — existing scores are not recalculated.',
  },

  // Interview
  {
    category: 'Interview',
    q: 'How does the AI interview work?',
    a: 'The interview is a turn-based conversation conducted entirely by AI. It runs across 3 rounds (configurable): Round 1 — Screening (background, motivations), Round 2 — Technical (role-specific questions), Round 3 — Cultural (values, teamwork, situational). Each round has 5 questions. After the final answer, the AI produces a verdict: Accept, Reject, or Hold, along with a confidence score and reasoning.',
  },
  {
    category: 'Interview',
    q: 'Where do I get an Applicant ID to start an interview?',
    a: 'Go to the Applications page, find the candidate in the table, and copy their Applicant ID from the details. It starts with "APP-" followed by 8 characters (e.g. APP-A1B2C3D4). You can also find it in the Results page for any candidate.',
  },
  {
    category: 'Interview',
    q: 'What happens if I close the interview tab mid-session?',
    a: 'Interview sessions are stored server-side with a timeout. If you return to the Interview page, you will need to start a new session with the same Applicant ID — the previous session will expire. For best results, complete an interview in a single sitting.',
  },
  {
    category: 'Interview',
    q: 'What does the "AI content detected" warning mean during an interview?',
    a: 'HireIQ analyses each interview response in real time for signs of AI-generated text (e.g. the candidate is using ChatGPT to answer). When the AI detection confidence exceeds your sensitivity threshold, a yellow warning banner appears in the chat. This is recorded in the final verdict and may reduce the confidence score.',
  },

  // AI Detection
  {
    category: 'AI Detection',
    q: 'How accurate is the AI detection feature?',
    a: 'The detection engine analyses linguistic patterns, sentence structure variance, vocabulary distribution, and semantic consistency. In internal testing it achieves over 90% accuracy on clearly AI-generated text. Edge cases — like a candidate who writes in a formal or structured style naturally — may occasionally trigger a false positive. Always treat flagged responses as a signal to probe further, not as a definitive verdict.',
  },
  {
    category: 'AI Detection',
    q: 'Can I adjust how sensitive the AI detection is?',
    a: 'Yes. Go to Settings → Pipeline Config → AI Detection Sensitivity. Options are Low (0.50), Medium (0.65), High (0.75 — default), and Very High (0.90). A lower threshold flags more responses (more false positives). A higher threshold only flags strongly AI-generated text (fewer false positives, but may miss subtle AI use).',
  },

  // Data & Security
  {
    category: 'Data & Security',
    q: 'Is candidate data stored securely?',
    a: 'All candidate data is stored in Supabase with row-level security (RLS) enabled. Data is encrypted at rest and in transit (TLS 1.3). HireIQ does not share applicant data with third parties. Groq processes text transiently for scoring and interview generation — no training data is retained.',
  },
  {
    category: 'Data & Security',
    q: 'Can I delete a candidate\'s data?',
    a: 'Yes. From the Applications page, open the candidate\'s results and use the delete option. This permanently removes the applicant record, all scores, and the interview transcript from the database.',
  },

  // Chatbot
  {
    category: 'Chatbot',
    q: 'What can the AI Chatbot help me with?',
    a: 'The HireIQ Chatbot has full access to your applicant database. You can ask it things like: "Who are the top 5 candidates for the backend role?", "Summarise why APP-XXXX was rejected", "Which applicants have more than 5 years of Python experience?", or "Compare the scores of these two candidates". It uses natural language — no need for exact IDs or filters.',
  },
]

const WORKFLOW_STEPS = [
  {
    num: '01',
    icon: 'upload_file',
    title: 'Upload Resume',
    color: 'text-primary',
    ring: 'border-primary/30',
    bg: 'bg-primary/10',
    desc: 'Go to the Upload page. Drag-and-drop a PDF or DOCX, or fill in the candidate form. The AI validates the document, extracts skills, and queues the candidate for scoring.',
    link: '/dashboard/upload',
    linkLabel: 'Go to Upload',
  },
  {
    num: '02',
    icon: 'analytics',
    title: 'AI Scores the Resume',
    color: 'text-secondary',
    ring: 'border-secondary/30',
    bg: 'bg-secondary/10',
    desc: 'Within 10–30 seconds the AI pipeline scores the candidate across 5 dimensions. The status changes from Pending → Shortlisted, On Hold, or Rejected automatically based on your thresholds.',
    link: '/dashboard/results',
    linkLabel: 'View Results',
  },
  {
    num: '03',
    icon: 'list_alt',
    title: 'Review Applications',
    color: 'text-tertiary',
    ring: 'border-tertiary/30',
    bg: 'bg-tertiary/10',
    desc: 'Open the Applications page to see all candidates ranked by score. Filter by status (Shortlisted, On Hold, Rejected), search by name or role, and click any row to view the full score breakdown.',
    link: '/dashboard/applications',
    linkLabel: 'Go to Applications',
  },
  {
    num: '04',
    icon: 'record_voice_over',
    title: 'Conduct AI Interview',
    color: 'text-primary',
    ring: 'border-primary/30',
    bg: 'bg-primary/10',
    desc: 'For shortlisted candidates, copy their Applicant ID and start a live interview session. The AI conducts 3 rounds of questions (Screening → Technical → Cultural). Responses are analysed for AI-generated content in real time.',
    link: '/dashboard/interview',
    linkLabel: 'Go to Interview',
  },
  {
    num: '05',
    icon: 'verified',
    title: 'Get Final Verdict',
    color: 'text-secondary',
    ring: 'border-secondary/30',
    bg: 'bg-secondary/10',
    desc: 'After the final interview round the AI delivers a verdict: Accept, Reject, or Hold — with a confidence percentage and written reasoning. The candidate status is updated automatically. Ask the Chatbot for deeper analysis anytime.',
    link: '/dashboard/chatbot',
    linkLabel: 'Open Chatbot',
  },
]

const SHORTCUTS = [
  { keys: ['Enter'],            action: 'Submit form / Send interview message' },
  { keys: ['Shift', 'Enter'],  action: 'New line in interview text box' },
  { keys: ['Esc'],             action: 'Close modal / Clear search' },
  { keys: ['Ctrl', 'K'],       action: 'Focus search bar (Applications page)' },
]

const SCORE_GRADES = [
  { range: '95 – 100', grade: 'A+', label: 'Exceptional',   color: 'text-secondary', bg: 'bg-secondary/10',  action: 'Fast-track to interview immediately' },
  { range: '85 – 94',  grade: 'A',  label: 'Strong',        color: 'text-secondary', bg: 'bg-secondary/10',  action: 'Recommend for interview' },
  { range: '70 – 84',  grade: 'B',  label: 'Good',          color: 'text-primary',   bg: 'bg-primary/10',    action: 'Consider for next round' },
  { range: '60 – 69',  grade: 'C',  label: 'Borderline',    color: 'text-tertiary',  bg: 'bg-tertiary/10',   action: 'Manual review recommended' },
  { range: '50 – 59',  grade: 'D',  label: 'Below Average', color: 'text-error',     bg: 'bg-error/10',      action: 'Likely not a fit' },
  { range: '0 – 49',   grade: 'F',  label: 'Poor',          color: 'text-error',     bg: 'bg-error/10',      action: 'Auto-rejected by pipeline' },
]

const TROUBLESHOOT = [
  {
    icon: 'cloud_off',
    title: 'Application shows "Unable to connect to the server"',
    fix: 'The backend server is not running. If you are a developer, start it with: cd hiring-agent && uv run uvicorn main:app --reload. If you are an end user, contact your system administrator.',
  },
  {
    icon: 'hourglass_empty',
    title: 'Candidate stuck on "Pending" for more than 2 minutes',
    fix: 'This usually means the AI pipeline encountered an error mid-run. Refresh the Applications page. If the status does not update, try re-submitting the candidate. Check that your Groq API key is valid.',
  },
  {
    icon: 'block',
    title: 'Resume upload rejected — "Not a hiring document"',
    fix: 'The AI content validator determined the file is not a resume or CV. Make sure you are uploading a genuine resume. If it is a valid resume, try converting it to PDF first. Scanned images with very low resolution may also fail — use a higher quality scan.',
  },
  {
    icon: 'error_outline',
    title: 'Interview session shows an error after starting',
    fix: 'The Applicant ID may be invalid or the candidate may not be in Shortlisted status. Verify the ID on the Applications page. Interviews can only be started for candidates whose status is Shortlisted.',
  },
  {
    icon: 'sentiment_dissatisfied',
    title: 'Score seems too low for a strong candidate',
    fix: 'Scores depend heavily on the content of the resume. A very short resume or one with little structured information produces lower scores. Try re-submitting with a fuller resume, or adjust the Shortlist Threshold in Settings → Pipeline Config to better match your hiring bar.',
  },
]

// ─── Component ─────────────────────────────────────────────────────────────

export default function HelpPage() {
  const [search, setSearch]       = useState('')
  const [openFaq, setOpenFaq]     = useState<number | null>(0)
  const [activeSection, setActiveSection] = useState('workflow')

  const filteredFaqs = useMemo(() => {
    const q = search.toLowerCase().trim()
    if (!q) return FAQS
    return FAQS.filter(
      (f) =>
        f.q.toLowerCase().includes(q) ||
        f.a.toLowerCase().includes(q) ||
        f.category.toLowerCase().includes(q),
    )
  }, [search])

  const faqCategories = useMemo(
    () => Array.from(new Set(filteredFaqs.map((f) => f.category))),
    [filteredFaqs],
  )

  const NAV = [
    { id: 'workflow',      label: 'How It Works',    icon: 'account_tree' },
    { id: 'faq',           label: 'FAQ',             icon: 'help' },
    { id: 'scoring',       label: 'Score Guide',     icon: 'grade' },
    { id: 'troubleshoot',  label: 'Troubleshooting', icon: 'build' },
    { id: 'shortcuts',     label: 'Shortcuts',       icon: 'keyboard' },
  ]

  return (
    <div className="px-8 py-10 animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-1">Help & Documentation</h1>
        <p className="text-on-surface-variant text-sm">
          Everything you need to get the most out of HireIQ
        </p>
      </div>

      {/* Search */}
      <div className="max-w-2xl mb-10">
        <div className="relative">
          <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-outline text-xl">search</span>
          <input
            className="w-full bg-surface-container-low border border-outline-variant/10 rounded-2xl pl-12 pr-6 py-4 text-sm focus:ring-1 focus:ring-primary/50 text-on-surface placeholder:text-outline/40 outline-none transition-all"
            placeholder="Search documentation, FAQs, troubleshooting…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setActiveSection('faq') }}
          />
          {search && (
            <button
              className="absolute right-4 top-1/2 -translate-y-1/2 text-outline hover:text-on-surface transition-colors"
              onClick={() => setSearch('')}
            >
              <span className="material-symbols-outlined text-lg">close</span>
            </button>
          )}
        </div>
        {search && (
          <p className="text-xs text-on-surface-variant mt-2 pl-1">
            {filteredFaqs.length} result{filteredFaqs.length !== 1 ? 's' : ''} for &ldquo;{search}&rdquo;
          </p>
        )}
      </div>

      <div className="grid grid-cols-12 gap-8">
        {/* Sidebar nav */}
        <nav className="col-span-12 lg:col-span-3">
          <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/5 sticky top-6">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => { setActiveSection(n.id); setSearch('') }}
                className={`w-full flex items-center gap-3 px-5 py-3.5 text-left transition-all ${
                  activeSection === n.id && !search
                    ? 'text-primary bg-primary/5 border-l-2 border-primary'
                    : 'text-on-surface-variant hover:text-white hover:bg-surface-container'
                }`}
              >
                <span className="material-symbols-outlined text-[20px]">{n.icon}</span>
                <span className="text-sm font-medium">{n.label}</span>
              </button>
            ))}

            {/* Quick links */}
            <div className="border-t border-outline-variant/10 p-4 space-y-2">
              <p className="text-[10px] uppercase tracking-widest text-outline font-semibold px-1 mb-3">Quick Links</p>
              <Link href="/dashboard/upload" className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-colors">
                <span className="material-symbols-outlined text-sm">upload_file</span> Upload Resume
              </Link>
              <Link href="/dashboard/applications" className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-colors">
                <span className="material-symbols-outlined text-sm">list_alt</span> Applications
              </Link>
              <Link href="/dashboard/interview" className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-colors">
                <span className="material-symbols-outlined text-sm">record_voice_over</span> Live Interview
              </Link>
              <Link href="/dashboard/chatbot" className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-colors">
                <span className="material-symbols-outlined text-sm">smart_toy</span> AI Chatbot
              </Link>
              <Link href="/dashboard/settings" className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-colors">
                <span className="material-symbols-outlined text-sm">settings</span> Settings
              </Link>
            </div>
          </div>
        </nav>

        {/* Main content */}
        <div className="col-span-12 lg:col-span-9 space-y-6">

          {/* ── How It Works ── */}
          {(activeSection === 'workflow' && !search) && (
            <section>
              <h2 className="text-xl font-bold mb-2">How HireIQ Works</h2>
              <p className="text-sm text-on-surface-variant mb-8">
                HireIQ is a fully autonomous AI hiring pipeline. From resume upload to final verdict, every step runs automatically — you only need to review the results.
              </p>
              <div className="space-y-4">
                {WORKFLOW_STEPS.map((step, i) => (
                  <div key={step.num} className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5 flex gap-5">
                    <div className={`w-12 h-12 rounded-xl border-2 ${step.ring} ${step.bg} flex items-center justify-center flex-shrink-0`}>
                      <span className={`material-symbols-outlined text-xl ${step.color}`} style={{ fontVariationSettings: "'FILL' 1" }}>{step.icon}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[10px] font-mono font-bold ${step.color}`}>{step.num}</span>
                        <h3 className="text-sm font-bold text-on-surface">{step.title}</h3>
                      </div>
                      <p className="text-xs text-on-surface-variant leading-relaxed mb-3">{step.desc}</p>
                      <Link href={step.link} className={`inline-flex items-center gap-1 text-xs font-semibold ${step.color} hover:underline`}>
                        {step.linkLabel}
                        <span className="material-symbols-outlined text-sm">arrow_forward</span>
                      </Link>
                    </div>
                    {i < WORKFLOW_STEPS.length - 1 && (
                      <div className="absolute ml-[1.35rem] mt-14 w-0.5 h-4 bg-outline-variant/20" />
                    )}
                  </div>
                ))}
              </div>

              {/* Pipeline diagram */}
              <div className="mt-8 bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                <h3 className="text-sm font-bold mb-4">Pipeline at a Glance</h3>
                <div className="flex items-center gap-2 flex-wrap">
                  {[
                    { label: 'Upload', color: 'bg-primary/20 text-primary' },
                    { label: '→', color: 'text-outline' },
                    { label: 'Validate', color: 'bg-surface-container text-on-surface-variant' },
                    { label: '→', color: 'text-outline' },
                    { label: 'Score', color: 'bg-secondary/20 text-secondary' },
                    { label: '→', color: 'text-outline' },
                    { label: 'Rank', color: 'bg-tertiary/20 text-tertiary' },
                    { label: '→', color: 'text-outline' },
                    { label: 'Interview', color: 'bg-primary/20 text-primary' },
                    { label: '→', color: 'text-outline' },
                    { label: 'Verdict', color: 'bg-secondary/20 text-secondary' },
                  ].map((item, i) => (
                    <span key={i} className={`text-xs font-bold px-3 py-1.5 rounded-full ${item.color}`}>
                      {item.label}
                    </span>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* ── FAQ ── */}
          {(activeSection === 'faq' || search) && (
            <section>
              <h2 className="text-xl font-bold mb-6">
                {search ? `Search results for "${search}"` : 'Frequently Asked Questions'}
              </h2>
              {filteredFaqs.length === 0 ? (
                <div className="flex flex-col items-center py-16 gap-3 text-on-surface-variant">
                  <span className="material-symbols-outlined text-4xl text-outline">search_off</span>
                  <p className="text-sm">No results found for &ldquo;{search}&rdquo;</p>
                  <button onClick={() => setSearch('')} className="text-xs text-primary hover:underline">Clear search</button>
                </div>
              ) : (
                <div className="space-y-8">
                  {faqCategories.map((cat) => (
                    <div key={cat}>
                      <div className="flex items-center gap-2 mb-3">
                        <span className="w-1.5 h-5 bg-primary rounded-full"></span>
                        <h3 className="text-xs font-bold uppercase tracking-widest text-primary">{cat}</h3>
                      </div>
                      <div className="space-y-2">
                        {filteredFaqs.filter((f) => f.category === cat).map((faq, i) => {
                          const key = `${cat}-${i}`
                          const isOpen = openFaq === key.length + i
                          return (
                            <div
                              key={i}
                              className="bg-surface-container-low rounded-xl border border-outline-variant/5 overflow-hidden"
                            >
                              <button
                                onClick={() => setOpenFaq(isOpen ? null : key.length + i)}
                                className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-surface-container transition-colors"
                              >
                                <span className="text-sm font-semibold text-on-surface pr-4">{faq.q}</span>
                                <span className={`material-symbols-outlined text-outline flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}>
                                  expand_more
                                </span>
                              </button>
                              {isOpen && (
                                <div className="px-6 pb-5 pt-1 text-sm text-on-surface-variant leading-relaxed border-t border-outline-variant/5">
                                  {faq.a}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {/* ── Score Guide ── */}
          {(activeSection === 'scoring' && !search) && (
            <section>
              <h2 className="text-xl font-bold mb-2">Score & Grade Reference</h2>
              <p className="text-sm text-on-surface-variant mb-8">
                Every candidate receives a score from 0 to 100. The score is a weighted combination of five AI-evaluated dimensions.
              </p>

              {/* Grade table */}
              <div className="bg-surface-container-low rounded-xl border border-outline-variant/5 overflow-hidden mb-8">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-surface-container text-[11px] uppercase tracking-widest text-on-surface-variant/60 border-b border-outline-variant/10">
                      <th className="px-5 py-3 font-bold">Score Range</th>
                      <th className="px-5 py-3 font-bold">Grade</th>
                      <th className="px-5 py-3 font-bold">Label</th>
                      <th className="px-5 py-3 font-bold">Recommended Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SCORE_GRADES.map((g) => (
                      <tr key={g.grade} className="border-b border-outline-variant/5 last:border-none">
                        <td className="px-5 py-3 font-mono text-sm text-on-surface-variant">{g.range}</td>
                        <td className="px-5 py-3">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${g.bg} ${g.color}`}>{g.grade}</span>
                        </td>
                        <td className={`px-5 py-3 text-sm font-semibold ${g.color}`}>{g.label}</td>
                        <td className="px-5 py-3 text-xs text-on-surface-variant">{g.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Dimensions */}
              <h3 className="text-sm font-bold mb-4">Scoring Dimensions</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
                {[
                  { label: 'Technical Skills',  weight: '30%', icon: 'code',          desc: 'Languages, frameworks, tools, and depth of technical knowledge relevant to the role.' },
                  { label: 'Experience',        weight: '25%', icon: 'work_history',   desc: 'Years of experience, seniority of past roles, industry relevance, and career progression.' },
                  { label: 'Problem Solving',   weight: '20%', icon: 'psychology',     desc: 'Evidence of analytical thinking, past projects, achievements, and impact.' },
                  { label: 'Communication',     weight: '15%', icon: 'forum',          desc: 'Clarity of writing in the resume, structure, grammar, and ability to articulate ideas.' },
                  { label: 'Cultural Fit',      weight: '10%', icon: 'diversity_3',    desc: 'Values alignment, collaboration signals, and soft skills inferred from the resume.' },
                ].map((d) => (
                  <div key={d.label} className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/5">
                    <div className="flex items-center justify-between mb-3">
                      <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>{d.icon}</span>
                      <span className="text-xs font-mono font-bold text-primary bg-primary/10 px-2 py-0.5 rounded">{d.weight}</span>
                    </div>
                    <p className="text-sm font-bold text-on-surface mb-1">{d.label}</p>
                    <p className="text-xs text-on-surface-variant leading-relaxed">{d.desc}</p>
                  </div>
                ))}
              </div>

              {/* Status meanings */}
              <h3 className="text-sm font-bold mb-4">Candidate Status Reference</h3>
              <div className="space-y-2">
                {[
                  { status: 'Pending',     badge: 'badge-pending',  desc: 'The AI pipeline is still processing this application.' },
                  { status: 'Shortlisted', badge: 'badge-pending',  desc: 'Score is above the Shortlist Threshold. Ready for interview.' },
                  { status: 'On Hold',     badge: 'badge-hold',     desc: 'Score is between rejection and shortlist thresholds. Requires manual review.' },
                  { status: 'Rejected',    badge: 'badge-rejected', desc: 'Score fell below the Auto-reject Threshold. Pipeline automatically rejected.' },
                  { status: 'Hired',       badge: 'badge-hired',    desc: 'Interview completed with an Accept verdict. Candidate is hired.' },
                ].map((s) => (
                  <div key={s.status} className="flex items-center gap-4 bg-surface-container-low rounded-xl px-5 py-3 border border-outline-variant/5">
                    <span className={`${s.badge} w-24 text-center flex-shrink-0`}>{s.status}</span>
                    <p className="text-xs text-on-surface-variant">{s.desc}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── Troubleshooting ── */}
          {(activeSection === 'troubleshoot' && !search) && (
            <section>
              <h2 className="text-xl font-bold mb-2">Troubleshooting</h2>
              <p className="text-sm text-on-surface-variant mb-8">
                Common issues and how to resolve them.
              </p>
              <div className="space-y-4">
                {TROUBLESHOOT.map((t) => (
                  <div key={t.title} className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5 flex gap-4">
                    <div className="w-10 h-10 rounded-xl bg-error/10 flex items-center justify-center flex-shrink-0">
                      <span className="material-symbols-outlined text-error text-xl">{t.icon}</span>
                    </div>
                    <div>
                      <p className="text-sm font-bold text-on-surface mb-2">{t.title}</p>
                      <p className="text-xs text-on-surface-variant leading-relaxed">{t.fix}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Still stuck */}
              <div className="mt-8 bg-surface-container-low rounded-xl p-6 border border-primary/20 text-center">
                <p className="text-sm font-semibold mb-1">Still stuck?</p>
                <p className="text-xs text-on-surface-variant mb-4">Open a GitHub issue with your error message and we will help you debug it.</p>
                <a
                  href="https://github.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-5 py-2.5 bg-surface-container-high text-on-surface rounded-xl text-xs font-bold hover:bg-surface-bright transition-colors"
                >
                  <span className="material-symbols-outlined text-sm">bug_report</span>
                  Open GitHub Issue
                </a>
              </div>
            </section>
          )}

          {/* ── Shortcuts ── */}
          {(activeSection === 'shortcuts' && !search) && (
            <section>
              <h2 className="text-xl font-bold mb-2">Keyboard Shortcuts</h2>
              <p className="text-sm text-on-surface-variant mb-8">Speed up your workflow with these shortcuts.</p>
              <div className="bg-surface-container-low rounded-xl border border-outline-variant/5 overflow-hidden">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-surface-container text-[11px] uppercase tracking-widest text-on-surface-variant/60 border-b border-outline-variant/10">
                      <th className="px-6 py-3 font-bold">Shortcut</th>
                      <th className="px-6 py-3 font-bold">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SHORTCUTS.map((s) => (
                      <tr key={s.action} className="border-b border-outline-variant/5 last:border-none">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-1">
                            {s.keys.map((k) => (
                              <kbd key={k} className="px-2 py-1 bg-surface-container-high rounded text-[11px] font-mono text-on-surface border border-outline-variant/20">
                                {k}
                              </kbd>
                            ))}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-sm text-on-surface-variant">{s.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Tips */}
              <div className="mt-8 space-y-3">
                <h3 className="text-sm font-bold mb-4">Pro Tips</h3>
                {[
                  { icon: 'lightbulb', tip: 'In the Interview page, press Enter to send your response — no need to click the send button.' },
                  { icon: 'lightbulb', tip: 'On the Applications page, use the search bar to instantly filter by candidate name, email, or role.' },
                  { icon: 'lightbulb', tip: 'Ask the Chatbot in natural language: "Who scored above 80 this week?" or "Summarise the top candidate for the ML role".' },
                  { icon: 'lightbulb', tip: 'Set your Pipeline Config thresholds before starting a batch upload — they apply to all future submissions.' },
                  { icon: 'lightbulb', tip: 'Export CSV from the Applications page to share candidate lists with your hiring team without giving them system access.' },
                ].map((t, i) => (
                  <div key={i} className="flex items-start gap-3 bg-surface-container-low rounded-xl px-5 py-4 border border-outline-variant/5">
                    <span className="material-symbols-outlined text-primary text-sm mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>{t.icon}</span>
                    <p className="text-xs text-on-surface-variant leading-relaxed">{t.tip}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

        </div>
      </div>
    </div>
  )
}
