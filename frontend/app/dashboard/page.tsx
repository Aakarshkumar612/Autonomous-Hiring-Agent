'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useUser } from '@clerk/nextjs'
import { api, PortalStatsResult, Applicant, RankResult, InterviewStartResult, LearnerResult } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

// ─── Helpers ────────────────────────────────────────────────────────────────

function timeGreeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

function fmt(n: number | undefined | null): string {
  if (n == null) return '—'
  return n.toLocaleString()
}

const quickActions = [
  { icon: 'upload_file', title: 'Upload Resumes',  desc: 'Analyze new candidates instantly',       href: '/dashboard/upload',      gradient: 'from-primary/10 to-transparent',   border: 'border-primary/20 hover:border-primary',   iconColor: 'text-primary' },
  { icon: 'smart_toy',   title: 'Ask AI Chatbot',  desc: 'Get insights on any candidate or trend', href: '/dashboard/chatbot',     gradient: 'from-tertiary/10 to-transparent',  border: 'border-tertiary/20 hover:border-tertiary', iconColor: 'text-tertiary' },
  { icon: 'analytics',   title: 'View Results',    desc: 'See full hiring decision reports',       href: '/dashboard/results',     gradient: 'from-secondary/10 to-transparent', border: 'border-secondary/20 hover:border-secondary', iconColor: 'text-secondary' },
]

// ─── Empty state ─────────────────────────────────────────────────────────────

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <span className="material-symbols-outlined text-4xl text-outline mb-3">inbox</span>
      <p className="text-sm text-on-surface-variant">{label}</p>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user } = useUser()
  const firstName = user?.firstName ?? user?.fullName?.split(' ')[0] ?? 'there'

  const [stats, setStats]       = useState<PortalStatsResult | null>(null)
  const [topCandidates, setTop] = useState<Applicant[]>([])
  const [loading, setLoading]   = useState(true)

  // Pipeline action states
  type PipelineKey = 'rank' | 'interviews' | 'learn'
  const [pipelineLoading, setPipelineLoading] = useState<Record<PipelineKey, boolean>>({ rank: false, interviews: false, learn: false })
  const [pipelineResult,  setPipelineResult]  = useState<Record<PipelineKey, string | null>>({ rank: null, interviews: null, learn: null })
  const [pipelineError,   setPipelineError]   = useState<Record<PipelineKey, string | null>>({ rank: null, interviews: null, learn: null })

  async function runPipeline(key: PipelineKey) {
    setPipelineLoading(prev => ({ ...prev, [key]: true }))
    setPipelineResult(prev  => ({ ...prev, [key]: null }))
    setPipelineError(prev   => ({ ...prev, [key]: null }))
    try {
      let msg = ''
      if (key === 'rank') {
        const r = await api.runRank() as RankResult
        msg = `Ranked ${r.shortlisted + r.on_hold + r.rejected} applicants — ${r.shortlisted} shortlisted, ${r.rejected} rejected.`
      } else if (key === 'interviews') {
        const r = await api.runInterviews() as InterviewStartResult
        msg = `Started ${r.started} interview session${r.started !== 1 ? 's' : ''}${r.failed > 0 ? `, ${r.failed} failed` : ''}.`
      } else {
        const r = await api.runLearn() as LearnerResult
        msg = r.summary || 'Learner analysis complete.'
      }
      setPipelineResult(prev => ({ ...prev, [key]: msg }))
    } catch (err) {
      setPipelineError(prev => ({ ...prev, [key]: friendlyError(err) }))
    } finally {
      setPipelineLoading(prev => ({ ...prev, [key]: false }))
    }
  }

  useEffect(() => {
    async function load() {
      try {
        const [s, list] = await Promise.all([
          api.getStats(),
          api.listApplicants({ status_filter: 'shortlisted', limit: 5 }),
        ])
        setStats(s)
        const sorted = [...list.applicants].sort(
          (a, b) => (b.detailed_status?.total_score ?? 0) - (a.detailed_status?.total_score ?? 0)
        )
        setTop(sorted.slice(0, 3))
      } catch {
        // Backend offline — show empty states, no fake numbers
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const byStatus = stats?.by_status ?? {}

  const kpiCards = [
    { label: 'Total Applicants', value: fmt(stats?.total_applicants),   icon: 'groups',       color: 'text-primary',   sparkColor: 'stroke-primary' },
    { label: 'Shortlisted',      value: fmt(byStatus['shortlisted']),   icon: 'check_circle', color: 'text-secondary', sparkColor: 'stroke-secondary' },
    { label: 'Rejected',         value: fmt(byStatus['rejected']),      icon: 'cancel',       color: 'text-error',     sparkColor: 'stroke-error' },
    { label: 'Pending',          value: fmt(byStatus['pending']),       icon: 'pending',      color: 'text-tertiary',  sparkColor: 'stroke-tertiary' },
  ]

  const pipelineStages = [
    { label: 'Submitted',   count: fmt(stats?.total_applicants),  active: (stats?.total_applicants ?? 0) > 0 },
    { label: 'Scored',      count: fmt((byStatus['shortlisted'] ?? 0) + (byStatus['rejected'] ?? 0) + (byStatus['on_hold'] ?? 0)), active: (stats?.total_applicants ?? 0) > 0 },
    { label: 'Shortlisted', count: fmt(byStatus['shortlisted']),  active: (byStatus['shortlisted'] ?? 0) > 0 },
    { label: 'Reviewing',   count: fmt(byStatus['on_hold']),      active: false, current: (byStatus['on_hold'] ?? 0) > 0 },
    { label: 'Decision',    count: fmt(byStatus['accepted']),     active: false },
  ]

  return (
    <div className="px-8 py-10 animate-fade-in">

      {/* Greeting */}
      <section className="mb-10">
        <h2 className="text-3xl font-bold tracking-tight text-on-surface">
          {timeGreeting()}, {firstName} 👋
        </h2>
        <p className="text-on-surface-variant mt-1">
          Here's your hiring performance for{' '}
          <span className="font-mono text-primary">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
          </span>
        </p>
      </section>

      {/* KPI Cards */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        {kpiCards.map((card) => (
          <div key={card.label} className="bg-surface-container-low p-6 rounded-xl hover:bg-surface-container-high transition-colors">
            <div className="flex justify-between items-start mb-4">
              <p className="text-[11px] font-bold uppercase tracking-widest text-on-surface-variant">{card.label}</p>
              <span className={`material-symbols-outlined ${card.color}`}>{card.icon}</span>
            </div>
            {loading ? (
              <div className="h-8 w-20 bg-surface-container-highest rounded animate-pulse"></div>
            ) : (
              <span className="text-3xl font-mono font-bold">{card.value}</span>
            )}
            <div className="mt-4 h-10 w-full overflow-hidden opacity-30">
              <svg className={`w-full h-full ${card.sparkColor} fill-none stroke-[2px]`} viewBox="0 0 100 40">
                <path d="M0 35 Q25 25 50 20 T100 10" />
              </svg>
            </div>
          </div>
        ))}
      </section>

      {/* Pipeline Controls */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
        {([
          {
            key:     'rank'        as PipelineKey,
            icon:    'sort',
            title:   'Re-rank Applicants',
            desc:    'Score & rank all pending applicants using current thresholds.',
            color:   'primary',
          },
          {
            key:     'interviews'  as PipelineKey,
            icon:    'record_voice_over',
            title:   'Start AI Interviews',
            desc:    'Launch autonomous interview sessions for all shortlisted candidates.',
            color:   'secondary',
          },
          {
            key:     'learn'       as PipelineKey,
            icon:    'psychology',
            title:   'Run Learner Analysis',
            desc:    'Analyse past hiring outcomes and update model recommendations.',
            color:   'tertiary',
          },
        ]).map(({ key, icon, title, desc, color }) => {
          const isLoading = pipelineLoading[key]
          const result    = pipelineResult[key]
          const error     = pipelineError[key]
          return (
            <div key={key} className={`bg-surface-container-low rounded-xl p-6 border border-${color}/10 hover:border-${color}/30 transition-all`}>
              <div className="flex items-start justify-between mb-4">
                <div className={`w-10 h-10 rounded-lg bg-${color}/10 flex items-center justify-center`}>
                  <span className={`material-symbols-outlined text-${color} text-xl`} style={{ fontVariationSettings: "'FILL' 1" }}>{icon}</span>
                </div>
                <button
                  onClick={() => runPipeline(key)}
                  disabled={isLoading}
                  className={`px-3 py-1.5 rounded-lg bg-${color}/10 text-${color} text-xs font-bold hover:bg-${color}/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5`}
                >
                  {isLoading
                    ? <><span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>Running…</>
                    : <><span className="material-symbols-outlined text-sm">play_arrow</span>Run</>
                  }
                </button>
              </div>
              <h4 className="text-sm font-bold text-on-surface mb-1">{title}</h4>
              <p className="text-xs text-on-surface-variant leading-relaxed mb-3">{desc}</p>
              {result && (
                <p className={`text-xs text-${color} font-medium bg-${color}/5 px-3 py-2 rounded-lg border border-${color}/10`}>{result}</p>
              )}
              {error && (
                <p className="text-xs text-error font-medium bg-error/5 px-3 py-2 rounded-lg border border-error/10">{error}</p>
              )}
            </div>
          )
        })}
      </section>

      {/* Pipeline + Role breakdown */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">

        {/* Pipeline */}
        <div className="lg:col-span-2 bg-surface-container-low p-8 rounded-xl">
          <h3 className="text-lg font-bold mb-8">Application Pipeline</h3>
          {loading ? (
            <div className="h-16 bg-surface-container-highest rounded animate-pulse"></div>
          ) : (stats?.total_applicants ?? 0) === 0 ? (
            <EmptyRow label="No applicants yet. Upload a CSV or submit applications to see the pipeline." />
          ) : (
            <div className="flex items-center justify-between relative px-2">
              <div className="absolute h-[2px] bg-outline-variant/20 left-0 right-0 top-[8px]"></div>
              {pipelineStages.map((stage) => (
                <div key={stage.label} className="relative z-10 flex flex-col items-center gap-3">
                  <div className={`w-4 h-4 rounded-full ${
                    stage.active   ? 'bg-primary shadow-[0_0_12px_rgba(173,198,255,0.6)]' :
                    stage.current  ? 'bg-surface-variant border-2 border-primary' :
                                     'bg-surface-variant border-2 border-outline-variant'
                  }`}></div>
                  <p className={`text-[10px] font-bold uppercase tracking-tight ${
                    stage.active ? 'text-primary' : 'text-on-surface-variant/50'
                  }`}>{stage.label}</p>
                  <p className={`font-mono text-sm ${stage.active || stage.current ? '' : 'opacity-40'}`}>{stage.count}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Role breakdown */}
        <div className="bg-surface-container-low p-8 rounded-xl">
          <h3 className="text-lg font-bold mb-6">By Role</h3>
          {loading ? (
            <div className="space-y-3">
              {[1,2,3].map(i => <div key={i} className="h-6 bg-surface-container-highest rounded animate-pulse"></div>)}
            </div>
          ) : Object.keys(stats?.by_role ?? {}).length === 0 ? (
            <EmptyRow label="No role data yet." />
          ) : (
            <div className="space-y-4">
              {Object.entries(stats!.by_role).map(([role, count]) => (
                <div key={role}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-on-surface-variant uppercase tracking-wider">{role}</span>
                    <span className="font-mono text-primary">{count as number}</span>
                  </div>
                  <div className="h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{ width: `${Math.min(100, ((count as number) / (stats!.total_applicants || 1)) * 100)}%` }}
                    ></div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Top Candidates */}
      <section className="bg-surface-container-low p-8 rounded-xl mb-10">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold">Top Shortlisted Candidates</h3>
          <Link href="/dashboard/applications" className="text-[11px] font-bold text-primary uppercase tracking-widest hover:underline">View All</Link>
        </div>
        {loading ? (
          <div className="space-y-4">
            {[1,2,3].map(i => <div key={i} className="h-12 bg-surface-container-highest rounded animate-pulse"></div>)}
          </div>
        ) : topCandidates.length === 0 ? (
          <EmptyRow label="No shortlisted candidates yet. Run the ingest pipeline to start scoring applicants." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[11px] uppercase tracking-widest text-on-surface-variant/60 border-b border-outline-variant/10">
                  <th className="pb-4 font-bold">Candidate</th>
                  <th className="pb-4 font-bold">Role</th>
                  <th className="pb-4 font-bold">Score</th>
                  <th className="pb-4 font-bold">Status</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {topCandidates.map((c) => {
                  const initials = c.full_name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
                  const score    = c.detailed_status?.total_score
                  return (
                    <tr key={c.id} className="hover:bg-surface-container/50 transition-colors">
                      <td className="py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xs">
                            {initials}
                          </div>
                          <span className="font-bold">{c.full_name}</span>
                        </div>
                      </td>
                      <td className="py-4 text-on-surface-variant capitalize">{c.role_applied}</td>
                      <td className="py-4 font-mono text-secondary">{score != null ? score.toFixed(1) : '—'}</td>
                      <td className="py-4">
                        <span className="text-[10px] uppercase font-bold text-secondary">{c.status}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Quick Actions */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {quickActions.map((action) => (
          <Link key={action.title} href={action.href}>
            <div className={`bg-gradient-to-br ${action.gradient} p-6 rounded-xl border ${action.border} transition-all group hover:-translate-y-1 duration-200`}>
              <span className={`material-symbols-outlined ${action.iconColor} text-3xl mb-4 block group-hover:scale-110 transition-transform`}>
                {action.icon}
              </span>
              <h4 className="font-bold mb-2">{action.title}</h4>
              <p className="text-xs text-on-surface-variant leading-relaxed">{action.desc}</p>
            </div>
          </Link>
        ))}
      </section>

      {/* FAB */}
      <div className="fixed bottom-8 right-8 z-[70]">
        <Link href="/dashboard/chatbot">
          <button className="w-14 h-14 bg-primary text-on-primary rounded-full shadow-2xl flex items-center justify-center hover:scale-105 transition-transform active:scale-95 group relative">
            <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>smart_toy</span>
            <div className="absolute -top-12 right-0 bg-surface-container-highest px-3 py-1 rounded text-[10px] font-bold uppercase whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
              AI Assistant
            </div>
          </button>
        </Link>
      </div>
    </div>
  )
}
