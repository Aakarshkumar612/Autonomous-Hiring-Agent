'use client'

import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { api, Applicant } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

// ─── Helpers ───────────────────────────────────────────────────────────────

function getFileType(a: Applicant): 'PDF' | 'DOCX' | 'Image' | 'CSV' | 'Form' {
  const url = (a.resume_url ?? '').toLowerCase()
  if (url.endsWith('.pdf'))  return 'PDF'
  if (url.endsWith('.docx') || url.endsWith('.doc')) return 'DOCX'
  if (url.endsWith('.jpg') || url.endsWith('.jpeg') || url.endsWith('.png') || url.endsWith('.webp')) return 'Image'
  if (a.source?.includes('bulk') || a.source?.includes('csv')) return 'CSV'
  return 'Form'
}

const TYPE_COLOR: Record<string, string> = {
  PDF:   'text-error bg-error/10',
  DOCX:  'text-primary bg-primary/10',
  Image: 'text-secondary bg-secondary/10',
  CSV:   'text-tertiary bg-tertiary/10',
  Form:  'text-outline bg-surface-container',
}

const TYPE_ICON: Record<string, string> = {
  PDF:   'picture_as_pdf',
  DOCX:  'description',
  Image: 'image',
  CSV:   'table_chart',
  Form:  'person',
}

const STATUS_BADGE: Record<string, string> = {
  accepted:    'badge-hired',
  shortlisted: 'badge-pending',
  on_hold:     'badge-hold',
  rejected:    'badge-rejected',
  pending:     'badge-pending',
}

const STATUS_LABEL: Record<string, string> = {
  accepted:    'Hired',
  shortlisted: 'Shortlisted',
  on_hold:     'On Hold',
  rejected:    'Rejected',
  pending:     'Pending',
}

const FILTERS = ['All Files', 'PDF', 'DOCX', 'Images', 'CSV / Bulk', 'Form']

// ─── Page ──────────────────────────────────────────────────────────────────

export default function UploadsPage() {
  const [applicants,   setApplicants]   = useState<Applicant[]>([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState<string | null>(null)
  const [activeFilter, setActiveFilter] = useState('All Files')

  useEffect(() => {
    api.listApplicants({ limit: 200 })
      .then((res) => { setApplicants(res.applicants); setLoading(false) })
      .catch((err) => { setError(friendlyError(err)); setLoading(false) })
  }, [])

  const filtered = useMemo(() => {
    if (activeFilter === 'All Files') return applicants
    return applicants.filter((a) => {
      const t = getFileType(a)
      if (activeFilter === 'PDF')       return t === 'PDF'
      if (activeFilter === 'DOCX')      return t === 'DOCX'
      if (activeFilter === 'Images')    return t === 'Image'
      if (activeFilter === 'CSV / Bulk') return t === 'CSV'
      if (activeFilter === 'Form')      return t === 'Form'
      return true
    })
  }, [applicants, activeFilter])

  return (
    <div className="px-8 py-10 animate-fade-in">
      {/* Header */}
      <div className="mb-8 flex flex-col sm:flex-row items-start sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-1">My Uploads</h1>
          <p className="text-on-surface-variant text-sm">
            {loading ? 'Loading…' : `${applicants.length} candidate${applicants.length !== 1 ? 's' : ''} across all pipelines`}
          </p>
        </div>
        <Link href="/dashboard/upload">
          <button className="px-5 py-2.5 bg-primary text-on-primary rounded-xl font-bold text-sm hover:shadow-lg hover:shadow-primary/20 transition-all active:scale-95 flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">upload</span>
            Upload New File
          </button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-8">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setActiveFilter(f)}
            className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider border transition-all ${
              activeFilter === f
                ? 'bg-primary/10 text-primary border-primary/30'
                : 'border-outline-variant/20 text-on-surface-variant hover:border-outline-variant/50'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center gap-3">
          <span className="material-symbols-outlined text-error text-lg flex-shrink-0">error_outline</span>
          <p className="text-sm text-error">{error}</p>
        </div>
      )}

      {/* Skeleton */}
      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/5 animate-pulse">
              <div className="w-12 h-12 bg-surface-container-highest rounded-xl mb-4" />
              <div className="h-4 bg-surface-container-highest rounded mb-2 w-3/4" />
              <div className="h-3 bg-surface-container-highest rounded w-1/2" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-32 text-center">
          <span className="material-symbols-outlined text-6xl text-outline mb-4">cloud_upload</span>
          <h3 className="text-lg font-bold text-on-surface mb-2">No uploads yet</h3>
          <p className="text-sm text-on-surface-variant max-w-sm mb-6">
            Upload individual resumes or run a bulk CSV ingest to see candidates here.
          </p>
          <Link href="/dashboard/upload">
            <button className="px-5 py-2.5 bg-primary text-on-primary rounded-xl font-bold text-sm hover:opacity-90 transition-opacity">
              Upload First Resume
            </button>
          </Link>
        </div>
      )}

      {/* Grid */}
      {!loading && filtered.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((a) => {
            const type      = getFileType(a)
            const typeColor = TYPE_COLOR[type]
            const typeIcon  = TYPE_ICON[type]
            const badge     = STATUS_BADGE[a.status] ?? 'badge-pending'
            const label     = STATUS_LABEL[a.status] ?? a.status
            const filename  = a.resume_url
              ? a.resume_url.split(/[\\/]/).pop() ?? a.resume_url
              : `${a.full_name.toLowerCase().replace(/\s+/g, '_')}_form`

            return (
              <div
                key={a.id}
                className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/5 hover:border-outline-variant/20 hover:-translate-y-0.5 transition-all group"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${typeColor}`}>
                    <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                      {typeIcon}
                    </span>
                  </div>
                  <span className={badge}>{label}</span>
                </div>

                <p className="text-sm font-bold text-on-surface mb-1 truncate" title={filename}>{filename}</p>
                <p className="text-xs text-primary font-medium mb-3 truncate">{a.full_name}</p>

                <div className="flex items-center justify-between text-[10px] text-on-surface-variant mb-4">
                  <span className="capitalize">{a.role_applied.replace(/_/g, ' ')}</span>
                  <span className="uppercase tracking-widest font-mono">{type}</span>
                </div>

                <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity pt-3 border-t border-outline-variant/10">
                  <Link href={`/dashboard/results?id=${a.id}`} className="flex-1">
                    <button className="w-full px-3 py-1.5 bg-surface-container rounded-lg text-xs font-bold text-on-surface-variant hover:text-white hover:bg-surface-bright transition-colors flex items-center justify-center gap-1">
                      <span className="material-symbols-outlined text-sm">open_in_new</span>
                      View Report
                    </button>
                  </Link>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
