'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { api, Applicant } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

const VALID_STATUSES = ['pending', 'shortlisted', 'on_hold', 'accepted', 'rejected'] as const

// ─── Helpers ───────────────────────────────────────────────────────────────

function initials(name: string): string {
  return name
    .split(' ')
    .map((w) => w[0] ?? '')
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

function computeGrade(score: number | null | undefined): string {
  if (score == null) return '—'
  if (score >= 95) return 'A+'
  if (score >= 85) return 'A'
  if (score >= 70) return 'B'
  if (score >= 60) return 'C'
  if (score >= 50) return 'D'
  return 'F'
}

// ─── Constants ─────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  accepted:    'Hired',
  shortlisted: 'Shortlisted',
  on_hold:     'On Hold',
  rejected:    'Rejected',
  pending:     'Pending',
}

const STATUS_BADGE: Record<string, string> = {
  accepted:    'badge-hired',
  shortlisted: 'badge-pending',
  on_hold:     'badge-hold',
  rejected:    'badge-rejected',
  pending:     'badge-pending',
}

// Maps filter label → backend status value (undefined = show all)
const FILTER_TO_STATUS: Record<string, string | undefined> = {
  All:         undefined,
  Hired:       'accepted',
  Shortlisted: 'shortlisted',
  'On Hold':   'on_hold',
  Rejected:    'rejected',
  Pending:     'pending',
}

// Pipeline stage 1-5 derived from status
const STATUS_STAGE: Record<string, number> = {
  pending:     1,
  rejected:    2,
  shortlisted: 3,
  on_hold:     3,
  accepted:    5,
}

const STAGE_LABELS = ['Submitted', 'Scored', 'Ranked', 'Interview', 'Decision']
const PAGE_SIZE = 20

export default function ApplicationsPage() {
  const [allApplicants, setAllApplicants] = useState<Applicant[]>([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState<string | null>(null)
  const [activeFilter, setActiveFilter]   = useState('All')
  const [search, setSearch]               = useState('')
  const [page, setPage]                   = useState(0)
  const [statusUpdating, setStatusUpdating] = useState<string | null>(null)  // applicant id being updated

  // Fetch all applicants once (PageIndex cap ~1000; 200 covers typical usage)
  useEffect(() => {
    setLoading(true)
    api
      .listApplicants({ limit: 200 })
      .then((res) => {
        setAllApplicants(res.applicants)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(friendlyError(err))
        setLoading(false)
      })
  }, [])

  // Client-side filter + search
  const filtered = useMemo(() => {
    const statusVal = FILTER_TO_STATUS[activeFilter]
    return allApplicants.filter((a) => {
      const matchesStatus = statusVal == null || a.status === statusVal
      const q = search.toLowerCase()
      const matchesSearch =
        q === '' ||
        a.full_name.toLowerCase().includes(q) ||
        a.role_applied.toLowerCase().includes(q) ||
        a.email.toLowerCase().includes(q)
      return matchesStatus && matchesSearch
    })
  }, [allApplicants, activeFilter, search])

  // Count per status for filter badges
  const counts = useMemo(() => {
    const c: Record<string, number> = { All: allApplicants.length }
    for (const a of allApplicants) {
      const label = STATUS_LABEL[a.status] ?? a.status
      c[label] = (c[label] ?? 0) + 1
    }
    return c
  }, [allApplicants])

  // Pagination
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const pageItems  = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  // Reset page when filter/search changes
  useEffect(() => { setPage(0) }, [activeFilter, search])

  async function changeStatus(applicantId: string, newStatus: string) {
    setStatusUpdating(applicantId)
    try {
      await api.updateStatus(applicantId, newStatus)
      setAllApplicants(prev =>
        prev.map(a => a.id === applicantId ? { ...a, status: newStatus as Applicant['status'] } : a)
      )
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setStatusUpdating(null)
    }
  }

  const filters = ['All', 'Hired', 'Shortlisted', 'On Hold', 'Rejected', 'Pending']

  function exportCsv() {
    if (filtered.length === 0) return
    const headers = ['Name', 'Email', 'Role', 'Status', 'Score', 'Grade', 'Experience (months)']
    const rows = filtered.map((a) => {
      const score = a.detailed_status?.total_score ?? null
      const grade = score == null ? '—' : score >= 95 ? 'A+' : score >= 85 ? 'A' : score >= 70 ? 'B' : score >= 60 ? 'C' : score >= 50 ? 'D' : 'F'
      return [
        `"${a.full_name.replace(/"/g, '""')}"`,
        `"${a.email}"`,
        `"${a.role_applied}"`,
        `"${a.status}"`,
        score != null ? score.toFixed(1) : '—',
        grade,
        a.total_experience_months,
      ].join(',')
    })
    const csv  = [headers.join(','), ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `hireiq-applicants-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-1">My Applications</h1>
        <p className="text-on-surface-variant text-sm">
          {loading ? 'Loading…' : `${allApplicants.length} total candidates across all hiring pipelines`}
        </p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
        <div className="flex flex-wrap gap-2">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setActiveFilter(f)}
              className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider transition-all border ${
                activeFilter === f
                  ? 'bg-primary/10 text-primary border-primary/30'
                  : 'border-outline-variant/20 text-on-surface-variant hover:border-outline-variant/50'
              }`}
            >
              {f}{' '}
              <span className="opacity-60">
                ({counts[f === 'All' ? 'All' : f] ?? 0})
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-sm">
              search
            </span>
            <input
              className="bg-surface-container-lowest border-none rounded-lg pl-9 pr-4 py-2 text-sm focus:ring-1 focus:ring-primary/50 text-on-surface-variant w-48 placeholder:text-outline/40 outline-none"
              placeholder="Search name, role…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button
            onClick={exportCsv}
            disabled={filtered.length === 0}
            className="px-4 py-2 bg-surface-container-low border border-outline-variant/20 rounded-lg text-xs font-bold text-on-surface-variant hover:text-white hover:border-outline-variant/50 transition-all flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined text-sm">download</span>
            Export CSV
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center gap-3">
          <span className="material-symbols-outlined text-error text-lg flex-shrink-0">error_outline</span>
          <p className="text-error text-sm">{error}</p>
        </div>
      )}

      {/* Table */}
      <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/5">
        {loading ? (
          <div className="flex items-center justify-center py-20 text-on-surface-variant text-sm gap-3">
            <span className="material-symbols-outlined animate-spin text-primary">progress_activity</span>
            Loading applicants…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <span className="material-symbols-outlined text-4xl text-outline">inbox</span>
            <p className="text-on-surface-variant text-sm">No applicants match this filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-surface-container border-b border-outline-variant/10 text-[11px] uppercase tracking-widest text-on-surface-variant/60">
                  <th className="px-6 py-4 font-bold">
                    <input type="checkbox" className="accent-primary w-4 h-4" />
                  </th>
                  <th className="px-4 py-4 font-bold">#</th>
                  <th className="px-4 py-4 font-bold">Candidate</th>
                  <th className="px-4 py-4 font-bold">Role</th>
                  <th className="px-4 py-4 font-bold">Score</th>
                  <th className="px-4 py-4 font-bold">Grade</th>
                  <th className="px-4 py-4 font-bold">Status</th>
                  <th className="px-4 py-4 font-bold">Pipeline Stage</th>
                  <th className="px-4 py-4 font-bold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((a, idx) => {
                  const score  = a.detailed_status?.total_score ?? null
                  const grade  = computeGrade(score)
                  const stage  = STATUS_STAGE[a.status] ?? 1
                  const badge  = STATUS_BADGE[a.status] ?? 'badge-pending'
                  const label  = STATUS_LABEL[a.status] ?? a.status

                  return (
                    <tr
                      key={a.id}
                      className="border-b border-outline-variant/5 hover:bg-surface-container/50 transition-colors group cursor-pointer"
                    >
                      <td className="px-6 py-4">
                        <input type="checkbox" className="accent-primary w-4 h-4" />
                      </td>
                      <td className="px-4 py-4 font-mono text-[11px] text-outline">
                        {String(page * PAGE_SIZE + idx + 1).padStart(3, '0')}
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xs flex-shrink-0">
                            {initials(a.full_name)}
                          </div>
                          <div className="flex flex-col">
                            <span className="text-sm font-bold text-on-surface">{a.full_name}</span>
                            <span className="text-[10px] text-outline font-mono">{a.email}</span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-sm text-on-surface-variant capitalize">
                        {a.role_applied.replace(/_/g, ' ')}
                      </td>
                      <td className="px-4 py-4 font-mono text-sm text-secondary">
                        {score != null ? score.toFixed(1) : '—'}
                      </td>
                      <td className="px-4 py-4">
                        <span className="px-2 py-0.5 rounded bg-primary/10 text-primary text-xs font-bold font-mono">
                          {grade}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        {statusUpdating === a.id ? (
                          <span className="material-symbols-outlined animate-spin text-primary text-sm">progress_activity</span>
                        ) : (
                          <select
                            value={a.status}
                            onChange={(e) => changeStatus(a.id, e.target.value)}
                            className={`${badge} border-none bg-transparent cursor-pointer text-xs font-bold uppercase tracking-wider focus:outline-none focus:ring-1 focus:ring-primary/50 rounded-full px-3 py-1`}
                          >
                            {VALID_STATUSES.map(s => (
                              <option key={s} value={s} className="bg-surface-container text-on-surface normal-case tracking-normal font-normal">
                                {STATUS_LABEL[s] ?? s}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-1">
                          {STAGE_LABELS.map((s, i) => (
                            <div
                              key={s}
                              title={s}
                              className={`w-6 h-1.5 rounded-full ${i < stage ? 'bg-primary' : 'bg-surface-container-high'}`}
                            />
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Link href={`/dashboard/results?id=${a.id}`}>
                            <button
                              className="p-1.5 rounded-lg hover:bg-surface-container text-on-surface-variant hover:text-primary transition-colors"
                              title="View Results"
                            >
                              <span className="material-symbols-outlined text-sm">open_in_new</span>
                            </button>
                          </Link>
                          <Link href="/dashboard/chatbot">
                            <button
                              className="p-1.5 rounded-lg hover:bg-surface-container text-on-surface-variant hover:text-secondary transition-colors"
                              title="Ask AI"
                            >
                              <span className="material-symbols-outlined text-sm">smart_toy</span>
                            </button>
                          </Link>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && filtered.length > 0 && (
          <div className="px-6 py-4 bg-surface-container border-t border-outline-variant/5 flex items-center justify-between">
            <span className="text-xs text-on-surface-variant">
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length} candidates
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface-variant text-xs font-bold hover:text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setPage(i)}
                  className={`w-8 h-8 rounded-lg text-xs font-bold transition-colors ${
                    page === i ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:text-white hover:bg-surface-container-high'
                  }`}
                >
                  {i + 1}
                </button>
              ))}
              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface-variant text-xs font-bold hover:text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
