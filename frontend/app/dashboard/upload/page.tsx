'use client'
import { useState, useRef, FormEvent } from 'react'
import { api, ApiError, type Applicant, type IngestResult } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

const SUGGESTED_SKILLS = ['Python', 'React', 'FastAPI', 'Docker', 'AWS', 'TypeScript', 'Node.js', 'PostgreSQL']

const ROLES = [
  { label: 'Senior Software Engineer', value: 'sde' },
  { label: 'Backend Engineer',         value: 'backend' },
  { label: 'Frontend Engineer',        value: 'frontend' },
  { label: 'ML Engineer',              value: 'ml_engineer' },
  { label: 'Data Engineer',            value: 'data_engineer' },
  { label: 'DevOps Engineer',          value: 'devops' },
  { label: 'Full Stack Engineer',      value: 'fullstack' },
  { label: 'AI Researcher',            value: 'ai_researcher' },
]

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState<'single' | 'bulk'>('single')

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-1">Upload Resume</h1>
          <p className="text-on-surface-variant text-sm">Initialize the AI analysis engine by providing candidate data.</p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 p-1 bg-surface-container-low rounded-xl w-fit mb-8 border border-outline-variant/10">
        {([
          { key: 'single', label: 'Single Resume',       icon: 'person' },
          { key: 'bulk',   label: 'Bulk CSV Pipeline',   icon: 'table_chart' },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-bold transition-all ${
              activeTab === tab.key
                ? 'bg-primary text-on-primary shadow-lg shadow-primary/20'
                : 'text-on-surface-variant hover:text-white'
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'single' ? <SingleResumeForm /> : <BulkIngestForm />}
    </div>
  )
}

// ─── Bulk CSV Ingest ─────────────────────────────────────────────────────────

function BulkIngestForm() {
  const [csvFile,   setCsvFile]   = useState<File | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [result,    setResult]    = useState<IngestResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!csvFile) return
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      const res = await api.runIngest(csvFile)
      setResult(res)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <div className="bg-surface-container-low rounded-2xl p-8 border border-outline-variant/10 mb-6">
        <h2 className="text-lg font-semibold text-white mb-2 flex items-center gap-3">
          <span className="w-2 h-6 bg-secondary rounded-full"></span>
          Bulk CSV / Excel Pipeline
        </h2>
        <p className="text-sm text-on-surface-variant mb-6">
          Upload a CSV or Excel file with multiple candidates. HireIQ will score every resume,
          rank them, and automatically shortlist or reject based on your configured thresholds.
        </p>

        {/* Required columns hint */}
        <div className="bg-surface-container rounded-xl p-4 mb-6 border border-outline-variant/10">
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2">Required CSV columns</p>
          <div className="flex flex-wrap gap-2">
            {['full_name', 'email', 'role_applied', 'experience_years'].map((col) => (
              <span key={col} className="px-2 py-0.5 bg-primary/10 text-primary text-[10px] font-mono rounded border border-primary/20">
                {col}
              </span>
            ))}
          </div>
          <p className="text-[10px] text-on-surface-variant mt-2">
            Optional: phone, location, github_url, linkedin_url, skills, education, cover_letter
          </p>
        </div>

        <form onSubmit={onSubmit}>
          {/* Drop zone */}
          <div
            onClick={() => fileRef.current?.click()}
            className="custom-dashed rounded-xl p-10 flex flex-col items-center justify-center text-center cursor-pointer hover:bg-surface-container-low/50 transition-all group mb-6"
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={(e) => { setCsvFile(e.target.files?.[0] ?? null); setResult(null); setError(null) }}
            />
            <span className="material-symbols-outlined text-4xl text-secondary mb-3 group-hover:scale-110 transition-transform" style={{ fontVariationSettings: "'FILL' 1" }}>
              table_chart
            </span>
            {csvFile ? (
              <>
                <p className="text-sm font-bold text-secondary mb-1">{csvFile.name}</p>
                <p className="text-xs text-on-surface-variant">{(csvFile.size / 1024).toFixed(0)} KB — click to change</p>
              </>
            ) : (
              <>
                <p className="text-sm font-semibold text-white mb-1">Drop CSV or Excel file here</p>
                <p className="text-xs text-on-surface-variant">or click to browse · Max 50 MB</p>
              </>
            )}
          </div>

          <button
            type="submit"
            disabled={!csvFile || loading}
            className="w-full bg-gradient-to-r from-secondary to-secondary-container text-on-secondary-fixed py-4 rounded-xl font-bold text-base shadow-xl shadow-secondary/20 flex items-center justify-center gap-3 hover:shadow-secondary/30 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {loading ? (
              <>
                <span className="material-symbols-outlined animate-spin">progress_activity</span>
                Processing pipeline… this may take 1–2 min
              </>
            ) : (
              <>
                Run Full Pipeline
                <span className="material-symbols-outlined">bolt</span>
              </>
            )}
          </button>
        </form>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 rounded-xl bg-error/10 border border-error/30 flex items-start gap-3 mb-6">
          <span className="material-symbols-outlined text-error mt-0.5">error</span>
          <p className="text-sm text-error">{error}</p>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="bg-surface-container-low rounded-2xl p-8 border border-secondary/20">
          <div className="flex items-center gap-3 mb-6">
            <span className="material-symbols-outlined text-secondary text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
            <h3 className="text-lg font-bold text-secondary">Pipeline Complete</h3>
          </div>
          <p className="text-sm text-on-surface-variant mb-6">{result.summary}</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            {[
              { label: 'Total',       value: result.total_applicants, color: 'text-on-surface' },
              { label: 'Shortlisted', value: result.shortlisted,      color: 'text-secondary' },
              { label: 'On Hold',     value: result.on_hold,          color: 'text-tertiary' },
              { label: 'Rejected',    value: result.rejected,         color: 'text-error' },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-surface-container rounded-xl p-4 text-center">
                <p className={`text-2xl font-mono font-bold ${color}`}>{value}</p>
                <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mt-1">{label}</p>
              </div>
            ))}
          </div>
          {result.top_shortlisted.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Top Shortlisted</p>
              <div className="space-y-2">
                {result.top_shortlisted.slice(0, 5).map((c) => (
                  <div key={c.applicant_id} className="flex items-center justify-between px-4 py-2 bg-surface-container rounded-lg">
                    <span className="text-sm font-medium text-on-surface">{c.name}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-mono text-secondary">{c.score.toFixed(1)}</span>
                      <span className="text-[10px] font-bold text-secondary/70">{c.grade ?? '—'}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {result.duration_seconds != null && (
            <p className="text-[10px] text-outline mt-4 text-right font-mono">
              Completed in {result.duration_seconds.toFixed(1)}s
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Single Resume Form ───────────────────────────────────────────────────────

function SingleResumeForm() {
  // ── Form state ──────────────────────────────────────────────
  const [fullName,      setFullName]      = useState('')
  const [email,         setEmail]         = useState('')
  const [phone,         setPhone]         = useState('')
  const [role,          setRole]          = useState('sde')
  const [githubUrl,     setGithubUrl]     = useState('')
  const [linkedinUrl,   setLinkedinUrl]   = useState('')
  const [experienceYrs, setExperienceYrs] = useState(5)
  const [skills,        setSkills]        = useState<string[]>(['TypeScript', 'Kubernetes'])
  const [skillInput,    setSkillInput]    = useState('')
  const [resumeFile,    setResumeFile]    = useState<File | null>(null)

  // ── Submission state ────────────────────────────────────────
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)
  const [result,   setResult]   = useState<Applicant | null>(null)

  // ── File preview state ───────────────────────────────────────
  const [filePreviewUrl, setFilePreviewUrl] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Handlers ────────────────────────────────────────────────

  function addSkill(name: string) {
    const trimmed = name.trim()
    if (trimmed && !skills.includes(trimmed)) {
      setSkills((prev) => [...prev, trimmed])
    }
    setSkillInput('')
  }

  function removeSkill(name: string) {
    setSkills((prev) => prev.filter((s) => s !== name))
  }

  function onSkillKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addSkill(skillInput)
    }
  }

  const MAX_FILE_BYTES = 10 * 1024 * 1024  // 10 MB

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    if (file.size > MAX_FILE_BYTES) {
      setError('This file is too large. Please upload a file under 10 MB.')
      // Reset the input so the user can pick a different file
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setError(null)
    setResumeFile(file)
    // Show image preview only for image uploads
    if (file.type.startsWith('image/')) {
      const url = URL.createObjectURL(file)
      setFilePreviewUrl(url)
    } else {
      setFilePreviewUrl(null)
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setLoading(true)

    try {
      const res = await api.submitApplication({
        full_name:        fullName,
        email,
        role_applied:     role,
        experience_years: experienceYrs,
        phone:            phone || undefined,
        github_url:       githubUrl || undefined,
        linkedin_url:     linkedinUrl || undefined,
        skills_raw:       skills.join(','),
        resume:           resumeFile ?? undefined,
      })
      setResult(res.applicant)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setLoading(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────

  return (
    <div>
      {/* Success banner */}
      {result && (
        <div className="mb-8 p-4 rounded-xl bg-secondary/10 border border-secondary/30 flex items-start gap-3">
          <span className="material-symbols-outlined text-secondary mt-0.5">check_circle</span>
          <div>
            <p className="font-semibold text-secondary text-sm">Application submitted</p>
            <p className="text-xs text-on-surface-variant mt-1">
              <span className="font-mono text-white">{result.id}</span> — {result.full_name} ({result.status})
            </p>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="mb-8 p-4 rounded-xl bg-error/10 border border-error/30 flex items-start gap-3">
          <span className="material-symbols-outlined text-error mt-0.5">error</span>
          <div>
            <p className="font-semibold text-error text-sm">Submission failed</p>
            <p className="text-xs text-on-surface-variant mt-1">{error}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start mt-0">
        {/* Left: Drop Zone */}
        <div className="lg:col-span-5 space-y-6">
          <div
            onClick={() => fileInputRef.current?.click()}
            className="custom-dashed rounded-xl p-12 flex flex-col items-center justify-center text-center transition-all hover:bg-surface-container-low/50 group cursor-pointer bg-surface-container-lowest/30 min-h-[320px]"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={onFileChange}
            />
            <div className="w-20 h-20 rounded-full bg-surface-container-highest flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
              <span className="material-symbols-outlined text-4xl text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>cloud_upload</span>
            </div>
            {resumeFile ? (
              <>
                {filePreviewUrl ? (
                  <img
                    src={filePreviewUrl}
                    alt="Document preview"
                    className="max-h-32 max-w-full rounded-lg object-contain mb-3 border border-outline-variant/20"
                  />
                ) : (
                  <div className="w-16 h-16 rounded-xl bg-primary/10 flex items-center justify-center mb-3">
                    <span className="material-symbols-outlined text-3xl text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>
                      description
                    </span>
                  </div>
                )}
                <p className="text-sm font-semibold text-secondary mb-1">{resumeFile.name}</p>
                <p className="text-xs text-on-surface-variant">{(resumeFile.size / 1024).toFixed(0)} KB — click to change</p>
              </>
            ) : (
              <>
                <h3 className="text-xl font-semibold text-white mb-2">Drop document here</h3>
                <p className="text-on-surface-variant text-sm max-w-[260px] mb-8">
                  PDF, DOCX, JPEG, PNG, or WEBP. Maximum 10 MB.
                </p>
                <button type="button" className="bg-surface-container-highest text-white px-6 py-2.5 rounded-lg text-sm font-semibold hover:bg-surface-bright transition-colors">
                  Browse Files
                </button>
              </>
            )}
          </div>

          {/* AI Capabilities */}
          <div className="bg-surface-container-lowest rounded-xl p-6 border border-outline-variant/10">
            <div className="flex items-center gap-3 mb-4">
              <span className="material-symbols-outlined text-primary">auto_awesome</span>
              <h4 className="text-sm font-semibold text-white">AI Processing Capabilities</h4>
            </div>
            <ul className="space-y-3">
              {[
                'Accepts PDF, DOCX, JPEG, PNG, WEBP uploads',
                'Smart validation — rejects non-hiring documents',
                'Vision OCR for image-based documents',
                'Semantic skill extraction and mapping',
                'AI-generated content detection',
                'GitHub contribution analysis (compound-beta)',
              ].map((item) => (
                <li key={item} className="flex items-center gap-3 text-xs text-on-surface-variant">
                  <span className="w-1 h-1 rounded-full bg-secondary flex-shrink-0"></span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Right: Form */}
        <div className="lg:col-span-7">
          <div className="bg-surface-container-low rounded-2xl p-8 lg:p-10 shadow-xl">
            <h2 className="text-lg font-semibold text-white mb-8 flex items-center gap-3">
              <span className="w-2 h-6 bg-primary rounded-full"></span>
              Candidate Information
            </h2>

            <form onSubmit={onSubmit} className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Full Name *</label>
                  <input
                    required
                    className="input-dark"
                    placeholder="e.g. Alexander Pierce"
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Email Address *</label>
                  <input
                    required
                    className="input-dark"
                    placeholder="alex@company.com"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Phone Number</label>
                  <input
                    className="input-dark"
                    placeholder="+1 (555) 000-0000"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Target Role *</label>
                  <select
                    required
                    className="input-dark appearance-none"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">GitHub URL</label>
                  <input
                    className="input-dark"
                    placeholder="https://github.com/username"
                    type="url"
                    value={githubUrl}
                    onChange={(e) => setGithubUrl(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">LinkedIn URL</label>
                  <input
                    className="input-dark"
                    placeholder="https://linkedin.com/in/username"
                    type="url"
                    value={linkedinUrl}
                    onChange={(e) => setLinkedinUrl(e.target.value)}
                  />
                </div>
              </div>

              {/* Experience Slider */}
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider">Experience Level</label>
                  <span className="font-mono text-sm text-primary">{experienceYrs} Year{experienceYrs !== 1 ? 's' : ''}</span>
                </div>
                <input
                  className="w-full h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer accent-primary"
                  type="range"
                  min="0"
                  max="20"
                  value={experienceYrs}
                  onChange={(e) => setExperienceYrs(Number(e.target.value))}
                />
                <div className="flex justify-between text-[10px] text-outline font-mono">
                  <span>0Y</span><span>10Y</span><span>20Y+</span>
                </div>
              </div>

              {/* Skills Tag Input */}
              <div className="space-y-3">
                <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Core Skills</label>
                <div className="w-full bg-surface-container-lowest rounded-lg p-3 flex flex-wrap gap-2 min-h-[80px] border border-outline-variant/10 focus-within:border-primary/40 transition-colors">
                  {skills.map((skill) => (
                    <span key={skill} className="bg-primary/10 text-primary px-3 py-1 rounded text-xs font-medium flex items-center gap-2">
                      {skill}
                      <button type="button" onClick={() => removeSkill(skill)}>
                        <span className="material-symbols-outlined text-[14px] hover:text-white" style={{ fontSize: '14px' }}>close</span>
                      </button>
                    </span>
                  ))}
                  <input
                    className="bg-transparent border-none focus:ring-0 text-xs py-1 px-2 flex-1 min-w-[100px] placeholder:text-outline/30 outline-none"
                    placeholder="Add skill, press Enter…"
                    type="text"
                    value={skillInput}
                    onChange={(e) => setSkillInput(e.target.value)}
                    onKeyDown={onSkillKeyDown}
                    onBlur={() => skillInput && addSkill(skillInput)}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTED_SKILLS.filter((s) => !skills.includes(s)).map((skill) => (
                    <button
                      key={skill}
                      type="button"
                      onClick={() => addSkill(skill)}
                      className="text-[10px] px-2 py-1 rounded-full bg-surface-container-high text-on-surface-variant hover:text-white border border-outline-variant/20 hover:border-outline-variant/50 transition-colors"
                    >
                      + {skill}
                    </button>
                  ))}
                </div>
              </div>

              {/* Submit */}
              <div className="pt-4">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-gradient-to-r from-secondary to-secondary-container text-on-secondary-fixed py-4 rounded-xl font-bold text-lg shadow-xl shadow-secondary/20 active:scale-[0.99] transition-all flex items-center justify-center gap-3 hover:shadow-secondary/30 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {loading ? (
                    <>
                      <span className="material-symbols-outlined animate-spin text-xl">progress_activity</span>
                      Analysing…
                    </>
                  ) : (
                    <>
                      Analyze Resume
                      <span className="material-symbols-outlined">bolt</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}
