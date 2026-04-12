'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { api, Applicant } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

// ─── Helpers ───────────────────────────────────────────────────────────────

function computeGrade(score: number | null | undefined): string {
  if (score == null) return '—'
  if (score >= 95) return 'A+'
  if (score >= 85) return 'A'
  if (score >= 70) return 'B'
  if (score >= 60) return 'C'
  if (score >= 50) return 'D'
  return 'F'
}

// SVG full-circle circumference for r=88: 2π×88 ≈ 552.9
const CIRCUMFERENCE = 552.9

function scoreOffset(score: number): number {
  return CIRCUMFERENCE * (1 - score / 100)
}

const STATUS_BADGE_CLASS: Record<string, string> = {
  accepted:    'bg-secondary text-on-secondary',
  shortlisted: 'bg-primary text-on-primary',
  on_hold:     'bg-tertiary text-on-tertiary',
  rejected:    'bg-error text-on-error',
  pending:     'bg-outline text-on-surface',
}

const STATUS_LABEL: Record<string, string> = {
  accepted:    'HIRED',
  shortlisted: 'SHORTLISTED',
  on_hold:     'ON HOLD',
  rejected:    'REJECTED',
  pending:     'PENDING',
}

const STATUS_ICON: Record<string, string> = {
  accepted:    'verified',
  shortlisted: 'star',
  on_hold:     'pause_circle',
  rejected:    'cancel',
  pending:     'hourglass_empty',
}

const ROUND_LABEL: Record<string, string> = {
  not_started: 'Not Started',
  round_1:     'Round 1 — Screening',
  round_2:     'Round 2 — Technical',
  round_3:     'Round 3 — Final',
  completed:   'Completed',
}

function experienceLabel(months: number): string {
  if (months === 0) return 'Fresher'
  const y = Math.floor(months / 12)
  const m = months % 12
  if (y === 0) return `${m}mo`
  if (m === 0) return `${y}yr`
  return `${y}yr ${m}mo`
}

// ─── Empty state ───────────────────────────────────────────────────────────

function NoApplicantSelected() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-surface-container flex items-center justify-center">
        <span className="material-symbols-outlined text-3xl text-outline">manage_search</span>
      </div>
      <div className="text-center">
        <h2 className="text-xl font-bold text-on-surface mb-2">No Applicant Selected</h2>
        <p className="text-on-surface-variant text-sm max-w-xs">
          Open this page from the Applications table to view a candidate's full hiring decision report.
        </p>
      </div>
      <Link href="/dashboard/applications">
        <button className="px-6 py-2.5 bg-primary text-on-primary rounded-xl text-sm font-bold hover:opacity-90 transition-opacity flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          Go to Applications
        </button>
      </Link>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function ResultsPage() {
  const searchParams = useSearchParams()
  const id = searchParams.get('id')

  const [applicant, setApplicant] = useState<Applicant | null>(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    setError(null)
    api
      .getApplicant(id)
      .then((a) => {
        setApplicant(a)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(friendlyError(err))
        setLoading(false)
      })
  }, [id])

  if (!id) return <NoApplicantSelected />

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] gap-3 text-on-surface-variant text-sm">
        <span className="material-symbols-outlined animate-spin text-primary">progress_activity</span>
        Loading report…
      </div>
    )
  }

  if (error || !applicant) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 animate-fade-in">
        <span className="material-symbols-outlined text-4xl text-error">error</span>
        <p className="text-on-surface-variant text-sm">{error ?? 'Applicant not found.'}</p>
        <Link href="/dashboard/applications">
          <button className="px-5 py-2 bg-surface-container rounded-xl text-sm font-bold hover:bg-surface-container-high transition-colors">
            ← Back to Applications
          </button>
        </Link>
      </div>
    )
  }

  const score        = applicant.detailed_status?.total_score ?? null
  const grade        = computeGrade(score)
  const statusClass  = STATUS_BADGE_CLASS[applicant.status] ?? 'bg-outline text-on-surface'
  const statusLabel  = STATUS_LABEL[applicant.status] ?? applicant.status.toUpperCase()
  const statusIcon   = STATUS_ICON[applicant.status] ?? 'info'
  const currentRound = ROUND_LABEL[applicant.detailed_status?.current_round ?? 'not_started']
  const expLabel     = experienceLabel(applicant.total_experience_months)
  const skillNames   = applicant.skills.map((s) => s.name)

  const gaugeOffset = score != null ? scoreOffset(score) : CIRCUMFERENCE

  return (
    <div className="px-8 py-10 animate-fade-in">
      {/* Header + Verdict */}
      <section className="mt-2 mb-12 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 mb-1">
            <Link href="/dashboard/applications" className="text-on-surface-variant hover:text-on-surface transition-colors">
              <span className="material-symbols-outlined text-sm">arrow_back</span>
            </Link>
            <h2 className="text-on-surface-variant font-label text-[0.75rem] font-bold tracking-widest uppercase">
              Report ID: #{applicant.id}
            </h2>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">
            Hiring Decision Analysis: {applicant.full_name}
          </h1>
          <p className="text-on-surface-variant capitalize">
            {applicant.role_applied.replace(/_/g, ' ')}
            {applicant.location ? ` | ${applicant.location}` : ''}
          </p>
        </div>

        <div className="relative group">
          <div className={`absolute -inset-1 blur-xl opacity-20 group-hover:opacity-40 transition-opacity rounded-xl ${statusClass}`}></div>
          <div className="relative flex flex-col items-end gap-1">
            <div className={`px-8 py-4 ${statusClass} rounded-xl font-bold text-2xl flex items-center gap-3`}>
              <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                {statusIcon}
              </span>
              {statusLabel}
            </div>
            <span className="text-[10px] font-mono text-on-surface-variant tracking-widest uppercase">
              {currentRound}
            </span>
          </div>
        </div>
      </section>

      {/* Bento Layout */}
      <div className="grid grid-cols-12 gap-8">
        {/* Left Column */}
        <div className="col-span-12 lg:col-span-5 flex flex-col gap-8">

          {/* Score Card */}
          <div className="bg-surface-container-low rounded-xl p-8 flex flex-col items-center gap-8 border-b border-white/5 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 blur-[60px] rounded-full -mr-16 -mt-16 pointer-events-none"></div>

            {/* Circular gauge */}
            <div className="relative w-48 h-48 flex items-center justify-center">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 192 192">
                <circle
                  className="text-surface-variant"
                  cx="96" cy="96" fill="transparent" r="88"
                  stroke="currentColor" strokeWidth="8"
                />
                <circle
                  className="text-primary-container"
                  cx="96" cy="96" fill="transparent" r="88"
                  stroke="currentColor"
                  strokeDasharray={CIRCUMFERENCE}
                  strokeDashoffset={gaugeOffset}
                  strokeWidth="12"
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute flex flex-col items-center">
                <span className="text-5xl font-mono font-bold text-on-surface">
                  {score != null ? Math.round(score) : '—'}
                </span>
                <span className="text-sm font-semibold text-primary uppercase tracking-widest">
                  {score != null ? 'Score / 100' : 'Not Scored'}
                </span>
              </div>
            </div>

            <div className="flex flex-col items-center gap-2">
              {score != null ? (
                <>
                  <div className="px-4 py-1.5 rounded-full border border-primary/20 bg-primary/5 flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
                    <span className="text-xs font-mono font-medium text-primary tracking-tight">
                      AI-Scored Profile
                    </span>
                  </div>
                  <div className="text-4xl font-bold text-on-surface mt-2">
                    {grade}{' '}
                    <span className="text-on-surface-variant text-lg font-normal">Grade</span>
                  </div>
                </>
              ) : (
                <p className="text-xs text-on-surface-variant text-center">
                  Run the scoring pipeline to generate a score for this candidate.
                </p>
              )}
            </div>

            {/* Skills list */}
            {skillNames.length > 0 && (
              <div className="w-full pt-2">
                <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Skills</p>
                <div className="flex flex-wrap gap-2">
                  {skillNames.slice(0, 12).map((s) => (
                    <span
                      key={s}
                      className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-primary/10 text-primary border border-primary/20"
                    >
                      {s}
                    </span>
                  ))}
                  {skillNames.length > 12 && (
                    <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-surface-container text-outline">
                      +{skillNames.length - 12}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Contact & Details */}
          <div className="bg-surface-container-low rounded-xl p-8 flex flex-col gap-5">
            <h3 className="text-sm font-bold uppercase tracking-widest text-on-surface">Candidate Profile</h3>
            <div className="space-y-4">
              {[
                { icon: 'mail', label: 'Email',      value: applicant.email },
                { icon: 'call', label: 'Phone',      value: applicant.phone },
                { icon: 'location_on', label: 'Location', value: applicant.location },
                { icon: 'work', label: 'Experience', value: expLabel },
                { icon: 'school', label: 'Education', value: applicant.education },
              ]
                .filter((row) => row.value)
                .map(({ icon, label, value }) => (
                  <div key={label} className="flex items-start gap-3">
                    <span className="material-symbols-outlined text-outline text-sm mt-0.5">{icon}</span>
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{label}</p>
                      <p className="text-sm text-on-surface">{value}</p>
                    </div>
                  </div>
                ))}

              {/* External links */}
              {(applicant.github_url || applicant.portfolio_url || applicant.linkedin_url) && (
                <div className="flex items-center gap-3 pt-1">
                  {applicant.github_url && (
                    <a href={applicant.github_url} target="_blank" rel="noopener noreferrer"
                      className="text-xs text-primary hover:underline flex items-center gap-1">
                      <span className="material-symbols-outlined text-sm">code</span> GitHub
                    </a>
                  )}
                  {applicant.portfolio_url && (
                    <a href={applicant.portfolio_url} target="_blank" rel="noopener noreferrer"
                      className="text-xs text-primary hover:underline flex items-center gap-1">
                      <span className="material-symbols-outlined text-sm">language</span> Portfolio
                    </a>
                  )}
                  {applicant.linkedin_url && (
                    <a href={applicant.linkedin_url} target="_blank" rel="noopener noreferrer"
                      className="text-xs text-primary hover:underline flex items-center gap-1">
                      <span className="material-symbols-outlined text-sm">person</span> LinkedIn
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Column */}
        <div className="col-span-12 lg:col-span-7 flex flex-col gap-8">

          {/* Cover Letter / Executive Summary */}
          {applicant.cover_letter ? (
            <div className="bg-surface-container rounded-xl p-8 relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-primary-container/5 to-transparent pointer-events-none"></div>
              <div className="relative flex flex-col gap-4">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary-container">auto_awesome</span>
                  <h3 className="text-sm font-bold uppercase tracking-widest text-primary">Cover Letter</h3>
                </div>
                <p className="text-base text-on-surface/90 leading-relaxed whitespace-pre-line">
                  {applicant.cover_letter.length > 600
                    ? applicant.cover_letter.slice(0, 600) + '…'
                    : applicant.cover_letter}
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-surface-container rounded-xl p-8 relative overflow-hidden">
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-outline">auto_awesome</span>
                  <h3 className="text-sm font-bold uppercase tracking-widest text-on-surface-variant">No Cover Letter</h3>
                </div>
                <p className="text-sm text-on-surface-variant">
                  This applicant did not submit a cover letter.
                </p>
              </div>
            </div>
          )}

          {/* Pipeline Status */}
          <div className="bg-surface-container-low rounded-xl p-6 flex flex-col gap-4 border border-outline-variant/10">
            <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">
              Pipeline Status
            </h4>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'Interview Round',  value: currentRound },
                { label: 'Application Status', value: statusLabel },
                { label: 'Data Source',      value: applicant.source },
                { label: 'Experience Level', value: applicant.experience_level },
              ].map(({ label, value }) => (
                <div key={label} className="flex flex-col gap-1">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{label}</p>
                  <p className="text-sm font-semibold text-on-surface capitalize">{value.replace(/_/g, ' ')}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Scorer Notes */}
          {applicant.detailed_status?.scorer_notes && (
            <div className="bg-surface-container-low rounded-xl p-6 flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-lg">psychology</span>
                <h4 className="text-xs font-bold uppercase tracking-widest text-on-surface">AI Scorer Notes</h4>
              </div>
              <p className="text-sm text-on-surface/90 leading-relaxed">
                {applicant.detailed_status.scorer_notes}
              </p>
            </div>
          )}

          {/* Action row */}
          <div className="flex items-center gap-3 flex-wrap">
            <Link href="/dashboard/chatbot">
              <button className="px-5 py-2.5 bg-primary/10 text-primary border border-primary/20 rounded-xl text-sm font-bold hover:bg-primary/20 transition-colors flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">smart_toy</span>
                Ask AI About This Candidate
              </button>
            </Link>
            <Link href="/dashboard/applications">
              <button className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant rounded-xl text-sm font-bold hover:text-white transition-colors flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">arrow_back</span>
                Back to Applications
              </button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
