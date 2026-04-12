'use client'

import { useState, useEffect } from 'react'
import { useUser } from '@clerk/nextjs'
import { api, PipelineConfig } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

// ─── Types ─────────────────────────────────────────────────────────────────

interface NotifSetting {
  key: string
  label: string
  desc: string
}

// ─── Constants ─────────────────────────────────────────────────────────────

const TABS = [
  { label: 'General',           icon: 'person' },
  { label: 'Notifications',     icon: 'notifications' },
  { label: 'API & Integrations', icon: 'code' },
  { label: 'Pipeline Config',   icon: 'tune' },
  { label: 'Team & Permissions', icon: 'group' },
  { label: 'Billing & Plan',    icon: 'credit_card' },
  { label: 'Security',          icon: 'lock' },
]

const NOTIF_SETTINGS: NotifSetting[] = [
  { key: 'email_resume',   label: 'Email on resume analyzed',  desc: 'Get notified when AI finishes scoring a resume' },
  { key: 'email_decision', label: 'Email on hiring decision',  desc: 'Receive final hire/reject/hold verdicts' },
  { key: 'weekly_report',  label: 'Weekly summary report',     desc: 'Pipeline performance digest every Monday' },
  { key: 'ai_alerts',      label: 'AI detection alerts',       desc: 'Immediate alert when AI-generated response detected' },
  { key: 'browser_push',   label: 'Browser push notifications', desc: 'Real-time desktop notifications' },
]

const DEFAULT_NOTIFS: Record<string, boolean> = {
  email_resume: true, email_decision: true, weekly_report: true, ai_alerts: true, browser_push: false,
}

// Sensitivity label → ai_detection_threshold value
const SENSITIVITY_MAP: Record<string, number> = {
  Low: 0.5, Medium: 0.65, High: 0.75, 'Very High': 0.90,
}
const SENSITIVITY_LABELS = ['Low', 'Medium', 'High', 'Very High']

function thresholdToLabel(val: number): string {
  const entries = Object.entries(SENSITIVITY_MAP)
  // Find closest
  let best = entries[0][0]
  let bestDiff = Math.abs(entries[0][1] - val)
  for (const [label, v] of entries) {
    const diff = Math.abs(v - val)
    if (diff < bestDiff) { bestDiff = diff; best = label }
  }
  return best
}

export default function SettingsPage() {
  const { user } = useUser()
  const fullName  = user?.fullName ?? user?.firstName ?? ''
  const email     = user?.primaryEmailAddress?.emailAddress ?? ''
  const avatarUrl = user?.imageUrl
  const initials  = fullName.split(' ').filter(Boolean).map(w => w[0]).join('').toUpperCase().slice(0, 2) || 'U'

  const [activeTab, setActiveTab] = useState('Pipeline Config')
  const [notifs, setNotifs]       = useState<Record<string, boolean>>(DEFAULT_NOTIFS)

  // Pipeline config state
  const [config, setConfig]           = useState<PipelineConfig | null>(null)
  const [configLoading, setConfigLoading] = useState(false)
  const [saving, setSaving]           = useState(false)
  const [saveMsg, setSaveMsg]         = useState<{ ok: boolean; text: string } | null>(null)

  // Load pipeline config when Pipeline Config tab is active
  useEffect(() => {
    if (activeTab !== 'Pipeline Config') return
    setConfigLoading(true)
    api.getPipelineConfig()
      .then((c) => { setConfig(c); setConfigLoading(false) })
      .catch(() => {
        // Fall back to defaults if backend is not running
        setConfig({ shortlist_threshold: 30, auto_reject_threshold: 20, interview_rounds: 3, ai_detection_threshold: 0.75, max_applicants: 1000 })
        setConfigLoading(false)
      })
  }, [activeTab])

  async function savePipelineConfig() {
    if (!config) return
    setSaving(true)
    setSaveMsg(null)
    try {
      await api.updatePipelineConfig(config)
      setSaveMsg({ ok: true, text: 'Pipeline configuration saved.' })
    } catch (err: unknown) {
      setSaveMsg({ ok: false, text: friendlyError(err) })
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMsg(null), 4000)
    }
  }

  function setField<K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) {
    setConfig((prev) => prev ? { ...prev, [key]: value } : prev)
  }

  const sensitivityLabel = config ? thresholdToLabel(config.ai_detection_threshold) : 'High'

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-1">Settings</h1>
        <p className="text-on-surface-variant text-sm">Manage your account and preferences</p>
      </div>

      <div className="grid grid-cols-12 gap-8">
        {/* Left: Settings Nav */}
        <div className="col-span-12 lg:col-span-3">
          <nav className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/5">
            {TABS.map((tab) => (
              <button
                key={tab.label}
                onClick={() => setActiveTab(tab.label)}
                className={`w-full flex items-center gap-3 px-5 py-3.5 text-left transition-all ${
                  activeTab === tab.label
                    ? 'text-primary bg-primary/5 border-l-2 border-primary'
                    : 'text-on-surface-variant hover:text-white hover:bg-surface-container'
                }`}
              >
                <span className="material-symbols-outlined text-[20px]">{tab.icon}</span>
                <span className="text-sm font-medium">{tab.label}</span>
              </button>
            ))}
          </nav>
        </div>

        {/* Right: Settings Content */}
        <div className="col-span-12 lg:col-span-9 space-y-8">

          {/* ── General ── */}
          {activeTab === 'General' && (
            <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/5">
              <h2 className="text-lg font-bold mb-6 flex items-center gap-3">
                <span className="w-2 h-6 bg-primary rounded-full"></span>
                General Settings
              </h2>
              <div className="flex items-center gap-6 mb-8">
                {avatarUrl ? (
                  <img src={avatarUrl} alt={fullName} className="w-16 h-16 rounded-full object-cover" />
                ) : (
                  <div className="w-16 h-16 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xl">
                    {initials}
                  </div>
                )}
                <div>
                  <p className="text-sm font-bold text-on-surface">{fullName || 'Your Name'}</p>
                  <p className="text-xs text-on-surface-variant">{email}</p>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                {[
                  { label: 'Display Name', val: fullName },
                  { label: 'Work Email',   val: email },
                  { label: 'Phone',        val: '' },
                  { label: 'Company',      val: '' },
                  { label: 'Job Title',    val: '' },
                ].map(({ label, val }) => (
                  <div key={label} className="space-y-2">
                    <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">{label}</label>
                    <input className="input-dark" defaultValue={val} placeholder={label} />
                  </div>
                ))}
                <div className="space-y-2">
                  <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">Timezone</label>
                  <select className="input-dark appearance-none">
                    <option>Pacific Time (PT) — UTC-8</option>
                    <option>Eastern Time (ET) — UTC-5</option>
                    <option>India Standard Time (IST) — UTC+5:30</option>
                  </select>
                </div>
              </div>
              <p className="text-xs text-on-surface-variant mt-2">
                Name and email are managed by Clerk. To update them, visit your{' '}
                <a
                  href="https://accounts.clerk.com/user"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline"
                >
                  Clerk account settings
                </a>.
              </p>
            </div>
          )}

          {/* ── Pipeline Config ── */}
          {activeTab === 'Pipeline Config' && (
            <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/5">
              <h2 className="text-lg font-bold mb-6 flex items-center gap-3">
                <span className="w-2 h-6 bg-secondary rounded-full"></span>
                AI Pipeline Configuration
              </h2>

              {configLoading || !config ? (
                <div className="flex items-center gap-3 py-8 text-on-surface-variant text-sm">
                  <span className="material-symbols-outlined animate-spin text-primary">progress_activity</span>
                  Loading configuration…
                </div>
              ) : (
                <div className="space-y-8">
                  {/* Shortlist Threshold */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-on-surface">Shortlist Threshold</p>
                      <p className="text-xs text-on-surface-variant">Minimum score to be shortlisted (0–100)</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <input
                        className="w-48 h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer accent-secondary"
                        type="range" min="0" max="100" step="1"
                        value={config.shortlist_threshold}
                        onChange={(e) => setField('shortlist_threshold', Number(e.target.value))}
                      />
                      <span className="font-mono text-sm text-secondary w-8 text-right">
                        {config.shortlist_threshold}
                      </span>
                    </div>
                  </div>

                  {/* Auto-reject Threshold */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-on-surface">Auto-reject Threshold</p>
                      <p className="text-xs text-on-surface-variant">Scores below this are automatically rejected (0–100)</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <input
                        className="w-48 h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer accent-error"
                        type="range" min="0" max="100" step="1"
                        value={config.auto_reject_threshold}
                        onChange={(e) => setField('auto_reject_threshold', Number(e.target.value))}
                      />
                      <span className="font-mono text-sm text-error w-8 text-right">
                        {config.auto_reject_threshold}
                      </span>
                    </div>
                  </div>

                  {/* Interview Rounds */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-on-surface">Interview Rounds</p>
                      <p className="text-xs text-on-surface-variant">Number of AI interview rounds per candidate</p>
                    </div>
                    <div className="flex gap-1">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button
                          key={n}
                          onClick={() => setField('interview_rounds', n)}
                          className={`w-10 h-10 rounded-lg font-mono text-sm font-bold transition-all ${
                            config.interview_rounds === n
                              ? 'bg-primary text-on-primary shadow-lg shadow-primary/20'
                              : 'bg-surface-container text-on-surface-variant hover:text-white'
                          }`}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* AI Detection Sensitivity */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-on-surface">AI Detection Sensitivity</p>
                      <p className="text-xs text-on-surface-variant">
                        Confidence threshold to flag a response as AI-generated
                        {' '}(current: {(config.ai_detection_threshold * 100).toFixed(0)}%)
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {SENSITIVITY_LABELS.map((level) => (
                        <button
                          key={level}
                          onClick={() => setField('ai_detection_threshold', SENSITIVITY_MAP[level])}
                          className={`px-3 py-2 rounded-lg text-xs font-bold transition-all ${
                            sensitivityLabel === level
                              ? 'bg-secondary text-on-secondary shadow-lg shadow-secondary/20'
                              : 'bg-surface-container text-on-surface-variant hover:text-white'
                          }`}
                        >
                          {level}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Max Applicants */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-on-surface">Max Applicants per Batch</p>
                      <p className="text-xs text-on-surface-variant">Maximum candidates stored in the pipeline (1–10,000)</p>
                    </div>
                    <input
                      className="w-24 bg-surface-container-lowest border-none rounded-lg px-4 py-2 text-sm text-center font-mono focus:ring-1 focus:ring-secondary/50 outline-none"
                      type="number" min="1" max="10000"
                      value={config.max_applicants}
                      onChange={(e) => setField('max_applicants', Number(e.target.value))}
                    />
                  </div>
                </div>
              )}

              {saveMsg && (
                <div className={`mt-6 px-4 py-3 rounded-xl text-sm font-medium ${saveMsg.ok ? 'bg-secondary/10 text-secondary border border-secondary/20' : 'bg-error/10 text-error border border-error/20'}`}>
                  {saveMsg.text}
                </div>
              )}

              <button
                onClick={savePipelineConfig}
                disabled={saving || !config}
                className="mt-8 px-6 py-2.5 bg-secondary text-on-secondary rounded-xl font-bold text-sm hover:shadow-lg hover:shadow-secondary/20 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {saving && <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>}
                {saving ? 'Saving…' : 'Save Pipeline Config'}
              </button>
            </div>
          )}

          {/* ── Notifications ── */}
          {activeTab === 'Notifications' && (
            <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/5">
              <h2 className="text-lg font-bold mb-6 flex items-center gap-3">
                <span className="w-2 h-6 bg-tertiary rounded-full"></span>
                Notification Preferences
              </h2>
              <div className="space-y-4">
                {NOTIF_SETTINGS.map((s) => (
                  <div key={s.key} className="flex items-center justify-between py-3 border-b border-outline-variant/5 last:border-none">
                    <div>
                      <p className="text-sm font-bold text-on-surface">{s.label}</p>
                      <p className="text-xs text-on-surface-variant">{s.desc}</p>
                    </div>
                    <button
                      onClick={() => setNotifs((prev) => ({ ...prev, [s.key]: !prev[s.key] }))}
                      className={`w-12 h-7 rounded-full cursor-pointer transition-colors flex items-center px-1 ${
                        notifs[s.key] ? 'bg-secondary justify-end' : 'bg-surface-container-high justify-start'
                      }`}
                    >
                      <div className={`w-5 h-5 rounded-full shadow-md transition-all ${notifs[s.key] ? 'bg-white' : 'bg-outline'}`} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Other tabs (placeholder) ── */}
          {!['General', 'Pipeline Config', 'Notifications'].includes(activeTab) && (
            <div className="bg-surface-container-low rounded-xl p-12 border border-outline-variant/5 flex flex-col items-center gap-4">
              <span className="material-symbols-outlined text-4xl text-outline">construction</span>
              <p className="text-on-surface-variant text-sm">{activeTab} settings coming soon.</p>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
