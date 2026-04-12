import Link from 'next/link'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'HireIQ — Autonomous AI Hiring Platform',
  description:
    'HireIQ autonomously scores resumes, conducts AI interviews, detects AI-generated responses, and delivers data-driven hiring decisions — in minutes, not weeks.',
}

// ─── Data ──────────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: 'article',
    color: 'primary',
    title: 'AI Resume Scoring',
    desc: 'Every resume is evaluated across five weighted dimensions — Technical Skills, Experience, Problem Solving, Communication, and Cultural Fit — powered by Groq llama-3.3-70b. Results in under 30 seconds.',
  },
  {
    icon: 'record_voice_over',
    color: 'secondary',
    title: 'Autonomous Interviews',
    desc: 'Three structured rounds — Screening, Technical, Cultural — conducted entirely by AI. Questions are tailored to the role and candidate profile. No human interviewer required.',
  },
  {
    icon: 'policy',
    color: 'primary',
    title: 'AI Detection Engine',
    desc: 'Real-time analysis of interview responses for AI-generated content. Multi-layer linguistic pattern recognition flags suspicious answers without blocking legitimate candidates.',
  },
  {
    icon: 'hub',
    color: 'secondary',
    title: 'Orchestrated Pipeline',
    desc: 'Six specialised LangGraph agents — Orchestrator, Scorer, Interviewer, Detector, Researcher, and Learner — work in sequence to process each candidate end-to-end.',
  },
  {
    icon: 'smart_toy',
    color: 'primary',
    title: 'Conversational Chatbot',
    desc: 'Ask anything about your candidate pool in plain language. "Who are the top 5 candidates for the ML role?" gets you a ranked list with reasoning in seconds.',
  },
  {
    icon: 'tune',
    color: 'secondary',
    title: 'Configurable Thresholds',
    desc: 'Set your own shortlist threshold, auto-reject floor, interview rounds, and AI detection sensitivity from the Settings panel. No engineering required.',
  },
]

const PIPELINE_AGENTS = [
  { label: 'Resume Upload',       icon: 'description',      sub: 'PDF · DOCX · Image' },
  { label: 'Document Validator',  icon: 'verified_user',    sub: 'Content gate' },
  { label: 'Scorer Agent',        icon: 'psychology',       sub: 'llama-3.3-70b' },
  { label: 'Rank Pipeline',       icon: 'sort',             sub: 'Weighted score' },
  { label: 'Interviewer Agent',   icon: 'record_voice_over',sub: 'llama-4-maverick' },
  { label: 'Detector Agent',      icon: 'policy',           sub: 'llama-3.1-8b' },
  { label: 'Orchestrator',        icon: 'hub',              sub: 'llama-3.3-70b' },
  { label: 'Final Verdict',       icon: 'verified',         sub: 'Accept · Hold · Reject' },
]

const COMPARE = [
  {
    dimension: 'Resume screening speed',
    hireiq: '< 30 seconds',
    manual: '2–3 days',
    ats: '1–2 days',
    hireiqWins: true,
  },
  {
    dimension: 'Interview consistency',
    hireiq: '100% standardised',
    manual: 'Varies by interviewer',
    ats: 'Partially standardised',
    hireiqWins: true,
  },
  {
    dimension: 'AI-generated answer detection',
    hireiq: 'Built-in · 90%+ accuracy',
    manual: 'None',
    ats: 'None',
    hireiqWins: true,
  },
  {
    dimension: 'Scales to 100+ applicants/day',
    hireiq: 'Yes — no extra cost',
    manual: 'Needs additional headcount',
    ats: 'Paid upgrade required',
    hireiqWins: true,
  },
  {
    dimension: 'Bias-free scoring',
    hireiq: 'Structured weighted dimensions',
    manual: 'Subjective',
    ats: 'Partial keyword match',
    hireiqWins: true,
  },
  {
    dimension: 'Natural language chatbot over data',
    hireiq: 'Full database Q&A',
    manual: 'None',
    ats: 'None',
    hireiqWins: true,
  },
  {
    dimension: 'Setup time',
    hireiq: '< 5 minutes',
    manual: 'Immediate (no tool)',
    ats: 'Days to weeks',
    hireiqWins: true,
  },
]

const STATS = [
  { value: '< 30s', label: 'Resume to Score', sub: 'End-to-end analysis' },
  { value: '5',     label: 'Scoring Dimensions', sub: 'Weighted & explainable' },
  { value: '90%+',  label: 'AI Detection Rate', sub: 'On flagged responses' },
  { value: '3',     label: 'Interview Rounds', sub: 'Screening · Tech · Cultural' },
]

const TESTIMONIALS = [
  {
    quote: 'The precision of the autonomous interviews is remarkable. It surfaced candidates our team had overlooked, and they turned out to be our top performers.',
    name: 'Marcus Thorne',
    title: 'VP Engineering, VeloScale',
    initials: 'MT',
  },
  {
    quote: 'We screened 2,000 graduate applications over a weekend without losing a single hour to scheduling or bias debates. HireIQ just handled it.',
    name: 'Sarah Jenkins',
    title: 'Director of Talent, NovaSoft',
    initials: 'SJ',
  },
  {
    quote: 'The AI Detection Engine alone justified switching. We caught three candidates using ChatGPT during live interviews. That never would have surfaced manually.',
    name: 'David Park',
    title: 'CTO, CyberPath',
    initials: 'DP',
  },
]

const PAIN_POINTS = [
  {
    icon: 'schedule',
    title: 'Screening 200 resumes takes a week',
    desc: 'The average recruiter spends 6 seconds per resume. Even then, qualified candidates are missed and unqualified ones slip through.',
  },
  {
    icon: 'person_off',
    title: 'Interviews are inconsistent and subjective',
    desc: 'Two interviewers evaluate the same candidate and reach opposite conclusions. Gut feel is not a hiring framework.',
  },
  {
    icon: 'smart_toy',
    title: 'You cannot detect AI-generated interview answers',
    desc: 'With ChatGPT, candidates can generate perfect answers in real time. Traditional tools have no way to detect or flag this.',
  },
]

const HOW_STEPS = [
  {
    num: '01',
    icon: 'upload_file',
    color: 'primary',
    title: 'Upload or submit a candidate',
    desc: 'Drop a PDF, DOCX, or image of a resume — or fill in the candidate form directly. HireIQ validates the document, rejects non-resume content, and queues the applicant.',
  },
  {
    num: '02',
    icon: 'psychology',
    color: 'secondary',
    title: 'AI scores the resume',
    desc: 'The Scorer Agent evaluates the candidate across five weighted dimensions. A final score from 0–100 is generated in under 30 seconds and triggers automatic shortlisting or rejection.',
  },
  {
    num: '03',
    icon: 'list_alt',
    color: 'primary',
    title: 'Review the ranked pipeline',
    desc: 'Every candidate appears in your Applications dashboard with their score, grade, and pipeline stage. Filter, search, and export to CSV at any time.',
  },
  {
    num: '04',
    icon: 'record_voice_over',
    color: 'secondary',
    title: 'Conduct the AI interview',
    desc: 'Start a live interview session with the candidate\'s ID. The AI runs three structured rounds. Responses are analysed for AI-generated content in real time.',
  },
  {
    num: '05',
    icon: 'verified',
    color: 'primary',
    title: 'Receive a final verdict',
    desc: 'After the last interview round, HireIQ delivers Accept, Reject, or Hold with a confidence score and written reasoning. The candidate\'s status is updated automatically.',
  },
]

// ─── Page ──────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="bg-surface min-h-screen overflow-x-hidden text-on-surface">

      {/* ═══════════════════ NAVBAR ═══════════════════ */}
      <nav className="fixed top-0 left-0 right-0 h-16 z-[100] flex items-center justify-between px-6 md:px-10 bg-surface/80 backdrop-blur-xl border-b border-outline-variant/10">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold tracking-tight text-primary">HireIQ</span>
          <span className="hidden sm:inline text-[9px] font-bold uppercase tracking-[0.2em] text-outline px-2 py-0.5 border border-outline-variant/30 rounded-full">
            Autonomous
          </span>
        </div>

        <div className="hidden md:flex items-center gap-8">
          {[
            { href: '#features',    label: 'Product' },
            { href: '#how-it-works',label: 'How It Works' },
            { href: '#compare',     label: 'Compare' },
            { href: '#pipeline',    label: 'Architecture' },
          ].map((l) => (
            <a key={l.href} href={l.href} className="text-sm font-medium text-on-surface-variant hover:text-white transition-colors">
              {l.label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <Link href="/sign-in">
            <span className="text-sm font-medium text-on-surface-variant hover:text-white transition-colors cursor-pointer hidden sm:inline">
              Sign In
            </span>
          </Link>
          <Link href="/sign-up">
            <span className="bg-primary text-on-primary px-5 py-2 text-sm font-bold rounded-xl hover:shadow-lg hover:shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer">
              Get Started Free
            </span>
          </Link>
        </div>
      </nav>

      <main>

        {/* ═══════════════════ HERO ═══════════════════ */}
        <section className="relative min-h-screen flex flex-col items-center justify-center pt-28 pb-20 px-6 overflow-hidden">
          {/* Background glows */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[900px] radial-glow-primary z-0 pointer-events-none opacity-70" />
          <div className="absolute top-1/4 right-0 w-[600px] h-[600px] radial-glow-secondary z-0 opacity-40 pointer-events-none" />
          <div className="absolute bottom-0 left-0 w-[500px] h-[500px] radial-glow-secondary z-0 opacity-20 pointer-events-none" />

          <div className="relative z-10 text-center max-w-5xl mx-auto">
            {/* Live badge */}
            <div className="inline-flex items-center gap-2 px-4 py-1.5 mb-8 rounded-full bg-surface-container-low border border-outline-variant/20">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse" />
              <span className="text-[11px] font-bold tracking-wider uppercase text-secondary">
                Groq-powered · Live Inference
              </span>
            </div>

            {/* Headline */}
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-[1.08]">
              <span className="hero-text-gradient">The Autonomous</span>
              <br />
              <span className="blue-green-gradient">Hiring Engine</span>
            </h1>

            <p className="text-lg md:text-xl text-on-surface-variant max-w-2xl mx-auto mb-4 leading-relaxed">
              HireIQ scores resumes, conducts structured AI interviews, detects AI-generated answers, and delivers hire-or-reject decisions — fully automated, in minutes.
            </p>
            <p className="text-sm text-outline max-w-xl mx-auto mb-12">
              Built for HR teams that need to move fast without sacrificing quality or fairness.
            </p>

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-6">
              <Link href="/sign-up">
                <span className="cursor-pointer inline-flex items-center gap-2 bg-primary text-on-primary px-8 py-4 text-base font-bold rounded-xl shadow-2xl shadow-primary/20 hover:shadow-primary/30 hover:scale-[1.02] active:scale-[0.98] transition-all">
                  Start Hiring Free
                  <span className="material-symbols-outlined text-lg">arrow_forward</span>
                </span>
              </Link>
              <a href="#how-it-works">
                <span className="cursor-pointer inline-flex items-center gap-2 glass-panel border border-outline-variant/30 text-on-surface px-8 py-4 text-base font-bold rounded-xl hover:bg-surface-container transition-colors">
                  <span className="material-symbols-outlined text-lg">play_circle</span>
                  See How It Works
                </span>
              </a>
            </div>

            {/* Trust line */}
            <p className="text-xs text-outline">
              No credit card required &nbsp;·&nbsp; Free to get started &nbsp;·&nbsp; GDPR compliant
            </p>
          </div>

          {/* Pipeline flow visualization */}
          <div className="relative z-10 mt-20 w-full max-w-4xl mx-auto">
            <div className="flex items-center justify-center gap-2 flex-wrap">
              {[
                { icon: 'description',       label: 'Upload',    active: false },
                { icon: 'psychology',        label: 'Score',     active: false },
                { icon: 'list_alt',          label: 'Rank',      active: false },
                { icon: 'record_voice_over', label: 'Interview', active: true  },
                { icon: 'policy',            label: 'Detect',    active: false },
                { icon: 'verified',          label: 'Decide',    active: false },
              ].map((step, i, arr) => (
                <div key={step.label} className="flex items-center gap-2">
                  <div className={`flex flex-col items-center gap-2 px-4 py-3 rounded-xl border transition-all hover:-translate-y-1 ${
                    step.active
                      ? 'bg-primary/10 border-primary/40 shadow-lg shadow-primary/10'
                      : 'bg-surface-container-low border-outline-variant/10'
                  }`}>
                    <span
                      className={`material-symbols-outlined text-xl ${step.active ? 'text-primary' : 'text-on-surface-variant'}`}
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      {step.icon}
                    </span>
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${step.active ? 'text-primary' : 'text-on-surface-variant'}`}>
                      {step.label}
                    </span>
                  </div>
                  {i < arr.length - 1 && (
                    <span className="material-symbols-outlined text-outline-variant text-sm">chevron_right</span>
                  )}
                </div>
              ))}
            </div>
            <p className="text-center text-xs text-outline mt-4">Full autonomous pipeline — no human in the loop required</p>
          </div>
        </section>

        {/* ═══════════════════ PROBLEM ═══════════════════ */}
        <section className="py-24 px-8 bg-surface-container-lowest">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <span className="text-[11px] font-bold uppercase tracking-widest text-error mb-4 block">The Problem</span>
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">
                Traditional hiring is broken.
              </h2>
              <p className="text-on-surface-variant max-w-xl mx-auto text-sm leading-relaxed">
                Slow, inconsistent, and now vulnerable to AI-generated answers. HR teams are spending more time than ever on hiring — and getting worse results.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {PAIN_POINTS.map((p) => (
                <div key={p.title} className="bg-surface-container-low rounded-xl p-7 border border-error/10 hover:border-error/20 transition-all">
                  <div className="w-12 h-12 rounded-xl bg-error/10 flex items-center justify-center mb-5">
                    <span className="material-symbols-outlined text-error text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                      {p.icon}
                    </span>
                  </div>
                  <h3 className="text-sm font-bold text-on-surface mb-2">{p.title}</h3>
                  <p className="text-xs text-on-surface-variant leading-relaxed">{p.desc}</p>
                </div>
              ))}
            </div>

            {/* Bridge line */}
            <div className="mt-16 text-center">
              <div className="inline-flex items-center gap-3 px-6 py-3 rounded-full bg-primary/5 border border-primary/20">
                <span className="material-symbols-outlined text-primary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                <span className="text-sm font-semibold text-primary">HireIQ solves all three — automatically.</span>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════ FEATURES ═══════════════════ */}
        <section id="features" className="py-24 px-8">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col md:flex-row md:items-end justify-between mb-16 gap-8">
              <div className="max-w-xl">
                <span className="text-[11px] font-bold tracking-widest uppercase text-primary mb-4 block">Core Capabilities</span>
                <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
                  Everything your hiring team needs. Nothing it doesn&apos;t.
                </h2>
              </div>
              <p className="text-sm text-on-surface-variant max-w-sm md:text-right leading-relaxed">
                Six tightly integrated capabilities that replace a full recruiting workflow — from first resume to final decision.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {FEATURES.map((f) => (
                <div
                  key={f.title}
                  className={`group p-8 rounded-2xl border border-outline-variant/5 transition-all duration-300 hover:-translate-y-1 ${
                    f.color === 'primary'
                      ? 'bg-surface-container-low hover:border-primary/20 hover:shadow-lg hover:shadow-primary/5'
                      : 'bg-surface-container hover:border-secondary/20 hover:shadow-lg hover:shadow-secondary/5'
                  }`}
                >
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform ${
                    f.color === 'primary' ? 'bg-primary/10' : 'bg-secondary/10'
                  }`}>
                    <span
                      className={`material-symbols-outlined text-2xl ${f.color === 'primary' ? 'text-primary' : 'text-secondary'}`}
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      {f.icon}
                    </span>
                  </div>
                  <h3 className="text-base font-bold mb-3 text-on-surface">{f.title}</h3>
                  <p className="text-sm text-on-surface-variant leading-relaxed">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════ HOW IT WORKS ═══════════════════ */}
        <section id="how-it-works" className="py-24 px-8 bg-surface-container-lowest">
          <div className="max-w-4xl mx-auto">
            <div className="text-center mb-20">
              <span className="text-[11px] font-bold uppercase tracking-widest text-secondary mb-4 block">Workflow</span>
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">Five steps. Zero manual effort.</h2>
              <p className="text-on-surface-variant text-sm max-w-lg mx-auto">
                From resume upload to final verdict, the pipeline runs end-to-end without requiring you to intervene at any step.
              </p>
            </div>

            <div className="space-y-4">
              {HOW_STEPS.map((step, i) => (
                <div key={step.num} className="flex gap-5 group">
                  {/* Step indicator + connector */}
                  <div className="flex flex-col items-center">
                    <div className={`w-12 h-12 rounded-xl border-2 flex items-center justify-center flex-shrink-0 transition-all group-hover:scale-105 ${
                      step.color === 'primary'
                        ? 'border-primary/40 bg-primary/10'
                        : 'border-secondary/40 bg-secondary/10'
                    }`}>
                      <span
                        className={`material-symbols-outlined text-xl ${step.color === 'primary' ? 'text-primary' : 'text-secondary'}`}
                        style={{ fontVariationSettings: "'FILL' 1" }}
                      >
                        {step.icon}
                      </span>
                    </div>
                    {i < HOW_STEPS.length - 1 && (
                      <div className="w-px flex-1 mt-2 bg-outline-variant/20 min-h-[2rem]" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex-1 pb-8">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[10px] font-mono font-bold ${step.color === 'primary' ? 'text-primary' : 'text-secondary'}`}>
                        {step.num}
                      </span>
                      <h3 className="text-base font-bold text-on-surface">{step.title}</h3>
                    </div>
                    <p className="text-sm text-on-surface-variant leading-relaxed">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════ COMPARE ═══════════════════ */}
        <section id="compare" className="py-24 px-8">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tertiary mb-4 block">Comparison</span>
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4">
                Why teams choose HireIQ over the alternatives
              </h2>
              <p className="text-on-surface-variant text-sm max-w-lg mx-auto">
                Compared against traditional manual hiring and legacy ATS platforms.
              </p>
            </div>

            <div className="rounded-2xl border border-outline-variant/10 overflow-hidden">
              {/* Header */}
              <div className="grid grid-cols-4 bg-surface-container border-b border-outline-variant/10">
                <div className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest text-on-surface-variant/60">Feature</div>
                <div className="px-6 py-4 text-center">
                  <span className="text-sm font-bold text-primary">HireIQ</span>
                  <span className="block text-[9px] text-primary/60 uppercase tracking-wider mt-0.5">Autonomous</span>
                </div>
                <div className="px-6 py-4 text-center">
                  <span className="text-sm font-bold text-on-surface-variant">Manual Hiring</span>
                  <span className="block text-[9px] text-outline uppercase tracking-wider mt-0.5">Traditional</span>
                </div>
                <div className="px-6 py-4 text-center">
                  <span className="text-sm font-bold text-on-surface-variant">Legacy ATS</span>
                  <span className="block text-[9px] text-outline uppercase tracking-wider mt-0.5">Keyword-based</span>
                </div>
              </div>

              {/* Rows */}
              {COMPARE.map((row, i) => (
                <div
                  key={row.dimension}
                  className={`grid grid-cols-4 border-b border-outline-variant/5 last:border-none ${
                    i % 2 === 0 ? 'bg-surface-container-low' : 'bg-surface-container-lowest'
                  }`}
                >
                  <div className="px-6 py-4 text-sm text-on-surface-variant flex items-center">{row.dimension}</div>
                  <div className="px-6 py-4 flex items-center justify-center gap-2">
                    <span className="material-symbols-outlined text-secondary text-base" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    <span className="text-xs font-semibold text-secondary text-center">{row.hireiq}</span>
                  </div>
                  <div className="px-6 py-4 flex items-center justify-center">
                    <span className="text-xs text-on-surface-variant text-center">{row.manual}</span>
                  </div>
                  <div className="px-6 py-4 flex items-center justify-center">
                    <span className="text-xs text-on-surface-variant text-center">{row.ats}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════ ARCHITECTURE ═══════════════════ */}
        <section id="pipeline" className="py-24 px-8 bg-surface-container-lowest">
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-16">
              <span className="text-[11px] font-bold uppercase tracking-widest text-primary mb-4 block">Under the Hood</span>
              <h2 className="text-3xl font-bold mb-4">Eight agents. One coordinated decision.</h2>
              <p className="text-on-surface-variant text-sm max-w-lg mx-auto">
                HireIQ is built on LangGraph — a stateful multi-agent orchestration framework. Each agent is assigned a specialised Groq model and runs in sequence.
              </p>
            </div>

            <div className="glass-panel border border-outline-variant/10 rounded-2xl p-8 md:p-12 shadow-2xl shadow-black/40">
              {/* Agent nodes */}
              <div className="flex flex-wrap items-center justify-center gap-3 md:gap-4">
                {PIPELINE_AGENTS.map((node, i, arr) => (
                  <div key={node.label} className="flex items-center gap-2 md:gap-3">
                    <div className="flex flex-col items-center gap-1.5 px-4 py-4 bg-surface-container rounded-xl border border-outline-variant/10 hover:border-primary/30 hover:-translate-y-1 transition-all min-w-[110px] text-center group cursor-default">
                      <span
                        className="material-symbols-outlined text-primary text-xl group-hover:scale-110 transition-transform"
                        style={{ fontVariationSettings: "'FILL' 1" }}
                      >
                        {node.icon}
                      </span>
                      <span className="text-[10px] font-bold uppercase tracking-tight text-on-surface leading-tight">{node.label}</span>
                      <span className="font-mono text-[9px] text-on-surface-variant">{node.sub}</span>
                    </div>
                    {i < arr.length - 1 && (
                      <span className="material-symbols-outlined text-outline-variant text-base hidden sm:inline">arrow_forward</span>
                    )}
                  </div>
                ))}
              </div>

              {/* Tech tags */}
              <div className="flex flex-wrap justify-center gap-2 mt-10 pt-8 border-t border-outline-variant/10">
                {['LangGraph', 'FastAPI', 'Groq', 'Supabase', 'Next.js', 'Clerk Auth', 'PageIndex RAG', 'Python 3.12'].map((tag) => (
                  <span key={tag} className="text-[10px] font-mono px-3 py-1 rounded-full bg-surface-container border border-outline-variant/20 text-on-surface-variant">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════ STATS ═══════════════════ */}
        <section className="py-20 border-y border-outline-variant/10 bg-surface">
          <div className="max-w-5xl mx-auto px-8 grid grid-cols-2 md:grid-cols-4 gap-12 text-center">
            {STATS.map((s) => (
              <div key={s.label}>
                <p className="text-4xl md:text-5xl font-bold font-mono text-primary mb-1">{s.value}</p>
                <p className="text-sm font-semibold text-on-surface mb-1">{s.label}</p>
                <p className="text-[11px] text-outline">{s.sub}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ═══════════════════ TESTIMONIALS ═══════════════════ */}
        <section className="py-24 px-8">
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-16">
              <span className="text-[11px] font-bold uppercase tracking-widest text-secondary mb-4 block">What Teams Are Saying</span>
              <h2 className="text-3xl font-bold">Built for hiring managers who care about signal, not noise.</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {TESTIMONIALS.map((t) => (
                <div
                  key={t.name}
                  className="glass-panel p-8 rounded-2xl border border-outline-variant/10 hover:border-outline-variant/30 hover:-translate-y-1 transition-all duration-300 flex flex-col"
                >
                  <div className="flex gap-0.5 text-secondary mb-6">
                    {[...Array(5)].map((_, i) => (
                      <span key={i} className="material-symbols-outlined text-base" style={{ fontVariationSettings: "'FILL' 1" }}>star</span>
                    ))}
                  </div>
                  <p className="text-on-surface-variant text-sm italic leading-relaxed flex-1 mb-6">&ldquo;{t.quote}&rdquo;</p>
                  <div className="flex items-center gap-3 pt-4 border-t border-outline-variant/10">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xs flex-shrink-0">
                      {t.initials}
                    </div>
                    <div>
                      <p className="text-sm font-bold text-on-surface">{t.name}</p>
                      <p className="text-xs text-on-surface-variant">{t.title}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════ FINAL CTA ═══════════════════ */}
        <section className="py-24 px-8">
          <div className="max-w-5xl mx-auto relative">
            <div className="glass-panel p-12 md:p-20 rounded-3xl border border-primary/15 relative overflow-hidden text-center">
              <div className="absolute -bottom-20 -right-20 w-[400px] h-[400px] radial-glow-primary z-0 opacity-40 pointer-events-none" />
              <div className="absolute -top-20 -left-20 w-[300px] h-[300px] radial-glow-secondary z-0 opacity-20 pointer-events-none" />
              <div className="relative z-10">
                <span className="text-[11px] font-bold uppercase tracking-widest text-primary mb-4 block">Get Started</span>
                <h2 className="text-4xl md:text-5xl font-bold mb-6 tracking-tight">
                  Your next great hire is<br />already in the pipeline.
                </h2>
                <p className="text-on-surface-variant text-base mb-10 max-w-xl mx-auto leading-relaxed">
                  Set up your pipeline in under five minutes. No integrations required. No training needed. Just upload a resume and watch HireIQ work.
                </p>
                <div className="flex flex-col sm:flex-row gap-4 justify-center">
                  <Link href="/sign-up">
                    <span className="cursor-pointer inline-flex items-center gap-2 bg-primary text-on-primary px-10 py-4 text-base font-bold rounded-xl shadow-2xl shadow-primary/20 hover:scale-[1.02] hover:shadow-primary/30 active:scale-[0.98] transition-all">
                      Start Hiring Free
                      <span className="material-symbols-outlined text-base">arrow_forward</span>
                    </span>
                  </Link>
                  <Link href="/dashboard/help">
                    <span className="cursor-pointer inline-flex items-center gap-2 bg-surface-container-high text-on-surface px-10 py-4 text-base font-bold rounded-xl border border-outline-variant/30 hover:bg-surface-bright transition-colors">
                      <span className="material-symbols-outlined text-base">menu_book</span>
                      Read the Docs
                    </span>
                  </Link>
                </div>
                <p className="text-xs text-outline mt-6">No credit card &nbsp;·&nbsp; No lock-in &nbsp;·&nbsp; GDPR compliant</p>
              </div>
            </div>
          </div>
        </section>

      </main>

      {/* ═══════════════════ FOOTER ═══════════════════ */}
      <footer className="pt-20 pb-12 px-8 border-t border-outline-variant/10 bg-surface-container-lowest">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-12 mb-16">
            {/* Brand */}
            <div className="col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-2xl font-bold text-primary">HireIQ</span>
                <span className="text-[9px] font-bold uppercase tracking-widest text-outline border border-outline-variant/30 px-2 py-0.5 rounded-full">Autonomous</span>
              </div>
              <p className="text-on-surface-variant text-sm max-w-xs leading-relaxed mb-6">
                The end-to-end autonomous hiring platform built for teams that refuse to compromise on speed, quality, or fairness.
              </p>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
                <span className="text-xs text-secondary font-semibold">System Operational</span>
              </div>
            </div>

            {/* Links */}
            {[
              {
                title: 'Product',
                links: [
                  { label: 'Resume Upload',  href: '/dashboard/upload' },
                  { label: 'Applications',   href: '/dashboard/applications' },
                  { label: 'AI Interview',   href: '/dashboard/interview' },
                  { label: 'AI Chatbot',     href: '/dashboard/chatbot' },
                  { label: 'Settings',       href: '/dashboard/settings' },
                ],
              },
              {
                title: 'Resources',
                links: [
                  { label: 'Help & Docs',    href: '/dashboard/help' },
                  { label: 'Sign In',        href: '/sign-in' },
                  { label: 'Sign Up',        href: '/sign-up' },
                  { label: 'GitHub',         href: '#' },
                ],
              },
              {
                title: 'Technology',
                links: [
                  { label: 'Groq AI',        href: '#' },
                  { label: 'LangGraph',      href: '#' },
                  { label: 'Supabase',       href: '#' },
                  { label: 'FastAPI',        href: '#' },
                ],
              },
            ].map((col) => (
              <div key={col.title}>
                <h6 className="text-[10px] font-bold uppercase tracking-widest text-on-surface mb-5">{col.title}</h6>
                <ul className="space-y-3">
                  {col.links.map((link) => (
                    <li key={link.label}>
                      <Link href={link.href}>
                        <span className="text-sm text-on-surface-variant hover:text-primary transition-colors cursor-pointer">
                          {link.label}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Bottom bar */}
          <div className="flex flex-col md:flex-row justify-between items-center pt-8 border-t border-outline-variant/5 gap-4">
            <p className="text-xs text-outline font-mono">
              © 2026 HireIQ. All rights reserved.
            </p>
            <div className="flex items-center gap-6 text-xs text-on-surface-variant">
              <a href="#" className="hover:text-primary transition-colors">Privacy Policy</a>
              <a href="#" className="hover:text-primary transition-colors">Terms of Service</a>
              <a href="#" className="hover:text-primary transition-colors">GDPR</a>
              <span className="text-outline">Powered by Groq</span>
            </div>
          </div>
        </div>
      </footer>

    </div>
  )
}
