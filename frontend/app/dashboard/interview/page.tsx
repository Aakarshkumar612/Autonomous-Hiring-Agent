'use client'
import { useState } from 'react'
import { api, ApiError } from '@/lib/api'
import { friendlyError } from '@/lib/errors'

/**
 * Interview Page — /dashboard/interview
 *
 * Flow:
 *  1. Enter applicant ID → click Start → call POST /portal/interview/{id}/start
 *  2. Backend returns session_id + first_question
 *  3. User types answer → Submit → call POST /portal/interview/{sessionId}/respond
 *  4. Backend returns next_question (or is_complete + verdict when done)
 *  5. Repeat until interview is complete
 *
 * This is a turn-based conversation. Each round has 5 questions.
 * Total: 3 rounds = up to 15 questions.
 */

type Phase = 'setup' | 'interviewing' | 'complete'

interface Message {
  role: 'agent' | 'user'
  text: string
  aiFlag?: boolean
}

export default function InterviewPage() {
  // ── Setup state ─────────────────────────────────────────────
  const [applicantId,   setApplicantId]   = useState('')
  const [sessionId,     setSessionId]     = useState('')
  const [currentRound,  setCurrentRound]  = useState(1)
  const [totalRounds,   setTotalRounds]   = useState(3)

  // ── Conversation state ──────────────────────────────────────
  const [phase,     setPhase]     = useState<Phase>('setup')
  const [messages,  setMessages]  = useState<Message[]>([])
  const [response,  setResponse]  = useState('')
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)

  // ── Final result ────────────────────────────────────────────
  const [verdict,    setVerdict]    = useState<string | null>(null)
  const [confidence, setConfidence] = useState<number | null>(null)
  const [reason,     setReason]     = useState<string | null>(null)
  const [nextAction, setNextAction] = useState<string | null>(null)

  // ── Handlers ────────────────────────────────────────────────

  async function startInterview() {
    if (!applicantId.trim()) return
    setError(null)
    setLoading(true)

    try {
      const result = await api.startInterview(applicantId.trim())
      setSessionId(result.session_id)
      setCurrentRound(result.round)
      setTotalRounds(result.total_rounds)
      setMessages([{ role: 'agent', text: result.first_question }])
      setPhase('interviewing')
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setLoading(false)
    }
  }

  async function submitResponse() {
    if (!response.trim() || loading) return
    const userMsg = response.trim()
    setResponse('')
    setError(null)
    setLoading(true)

    // Optimistically add user message
    setMessages((prev) => [...prev, { role: 'user', text: userMsg }])

    try {
      const result = await api.respondToInterview(sessionId, userMsg)

      if (result.is_complete) {
        // Interview done — show verdict
        setVerdict(result.verdict)
        setConfidence(result.confidence)
        setReason(result.reason)
        setNextAction(result.next_action)
        setPhase('complete')
        if (result.ai_flagged) {
          setMessages((prev) => [
            ...prev,
            { role: 'agent', text: '⚠️ AI-generated content detected in this response.', aiFlag: true },
          ])
        }
      } else if (result.next_question) {
        setMessages((prev) => [
          ...prev,
          ...(result.ai_flagged
            ? [{ role: 'agent' as const, text: '⚠️ Note: AI content detected.', aiFlag: true }]
            : []),
          { role: 'agent' as const, text: result.next_question ?? '' },
        ])
        // Update round from session status
        try {
          const status = await api.getInterviewStatus(sessionId)
          setCurrentRound(status.current_round)
        } catch { /* non-critical */ }
      }
    } catch (err) {
      setError(friendlyError(err))
      // Remove optimistic user message on error
      setMessages((prev) => prev.slice(0, -1))
      setResponse(userMsg)
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setApplicantId('')
    setSessionId('')
    setPhase('setup')
    setMessages([])
    setResponse('')
    setError(null)
    setVerdict(null)
  }

  // ── Render ──────────────────────────────────────────────────

  const verdictConfig = {
    accept: { color: 'text-secondary border-secondary/30 bg-secondary/10', icon: 'check_circle', label: 'ACCEPTED' },
    reject: { color: 'text-error border-error/30 bg-error/10', icon: 'cancel', label: 'REJECTED' },
    hold:   { color: 'text-tertiary border-tertiary/30 bg-tertiary/10', icon: 'pending', label: 'ON HOLD' },
  }
  const vc = verdict ? (verdictConfig[verdict as keyof typeof verdictConfig] ?? verdictConfig.hold) : null

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-1">Live Interview</h1>
        <p className="text-on-surface-variant text-sm">
          Conduct a 3-round autonomous AI interview for a shortlisted applicant.
        </p>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-xl bg-error/10 border border-error/30 flex items-center gap-3">
          <span className="material-symbols-outlined text-error">error</span>
          <p className="text-sm text-error">{error}</p>
        </div>
      )}

      {/* ── Setup Phase ── */}
      {phase === 'setup' && (
        <div className="max-w-lg bg-surface-container-low rounded-2xl p-8">
          <h2 className="text-lg font-semibold mb-6">Start Interview Session</h2>
          <div className="space-y-4">
            <div>
              <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block mb-2">
                Applicant ID
              </label>
              <input
                className="input-dark w-full"
                placeholder="APP-XXXXXXXX"
                value={applicantId}
                onChange={(e) => setApplicantId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && startInterview()}
              />
              <p className="text-xs text-on-surface-variant mt-2">
                Get the ID from the Applications page or from /run-interviews output.
              </p>
            </div>
            <button
              onClick={startInterview}
              disabled={loading || !applicantId.trim()}
              className="w-full bg-primary text-on-primary py-3 rounded-xl font-bold disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? (
                <><span className="material-symbols-outlined animate-spin">progress_activity</span> Starting…</>
              ) : (
                <><span className="material-symbols-outlined">play_arrow</span> Start Interview</>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── Interview Phase ── */}
      {phase === 'interviewing' && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Sidebar: progress */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-surface-container-low rounded-xl p-5">
              <p className="text-[10px] uppercase tracking-widest text-outline font-semibold mb-3">Round Progress</p>
              <div className="space-y-2">
                {['Screening', 'Technical', 'Cultural'].map((name, i) => {
                  const roundNum = i + 1
                  const isDone    = currentRound > roundNum
                  const isCurrent = currentRound === roundNum
                  return (
                    <div key={name} className={`flex items-center gap-3 p-2 rounded-lg ${isCurrent ? 'bg-primary/10' : ''}`}>
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                        isDone ? 'bg-secondary text-on-secondary' : isCurrent ? 'bg-primary text-on-primary' : 'bg-surface-container-high text-outline'
                      }`}>
                        {isDone ? '✓' : roundNum}
                      </div>
                      <span className={`text-sm ${isCurrent ? 'text-primary font-semibold' : 'text-on-surface-variant'}`}>{name}</span>
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="bg-surface-container-low rounded-xl p-5">
              <p className="text-[10px] uppercase tracking-widest text-outline font-semibold mb-2">Session</p>
              <p className="font-mono text-xs text-on-surface-variant break-all">{sessionId}</p>
            </div>
          </div>

          {/* Chat window */}
          <div className="lg:col-span-3 bg-surface-container-low rounded-2xl flex flex-col" style={{ height: '65vh' }}>
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
                >
                  <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold ${
                    msg.role === 'agent' ? 'bg-primary/20 text-primary' : 'bg-secondary/20 text-secondary'
                  }`}>
                    {msg.role === 'agent' ? 'AI' : 'You'}
                  </div>
                  <div className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                    msg.aiFlag
                      ? 'bg-error/10 border border-error/30 text-error'
                      : msg.role === 'agent'
                      ? 'bg-surface-container text-on-surface'
                      : 'bg-primary/10 text-on-surface'
                  }`}>
                    {msg.text}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-xs text-primary font-bold">AI</div>
                  <div className="bg-surface-container px-4 py-3 rounded-2xl flex items-center gap-2">
                    <span className="material-symbols-outlined animate-spin text-primary text-sm">progress_activity</span>
                    <span className="text-xs text-on-surface-variant">Processing…</span>
                  </div>
                </div>
              )}
            </div>

            {/* Input */}
            <div className="p-4 border-t border-outline-variant/10">
              <div className="flex gap-3">
                <textarea
                  className="flex-1 bg-surface-container-lowest rounded-xl px-4 py-3 text-sm text-on-surface placeholder:text-outline/40 resize-none outline-none border border-outline-variant/10 focus:border-primary/40 transition-colors"
                  placeholder="Type your response… (Shift+Enter for new line)"
                  rows={3}
                  value={response}
                  onChange={(e) => setResponse(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      submitResponse()
                    }
                  }}
                />
                <button
                  onClick={submitResponse}
                  disabled={loading || !response.trim()}
                  className="w-12 h-12 self-end bg-primary text-on-primary rounded-xl flex items-center justify-center disabled:opacity-40 hover:scale-105 transition-transform"
                >
                  <span className="material-symbols-outlined">send</span>
                </button>
              </div>
              <p className="text-[10px] text-outline mt-2">Press Enter to send • Shift+Enter for new line</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Complete Phase ── */}
      {phase === 'complete' && vc && (
        <div className="max-w-2xl space-y-6">
          <div className={`rounded-2xl p-8 border ${vc.color}`}>
            <div className="flex items-center gap-4 mb-6">
              <span className={`material-symbols-outlined text-4xl ${vc.color.split(' ')[0]}`} style={{ fontVariationSettings: "'FILL' 1" }}>
                {vc.icon}
              </span>
              <div>
                <p className="text-xs uppercase tracking-widest font-semibold opacity-60">Final Verdict</p>
                <h2 className={`text-3xl font-bold font-mono ${vc.color.split(' ')[0]}`}>{vc.label}</h2>
              </div>
              {confidence != null && (
                <div className="ml-auto text-right">
                  <p className="text-xs uppercase tracking-widest opacity-60">Confidence</p>
                  <p className="text-2xl font-mono font-bold">{(confidence * 100).toFixed(0)}%</p>
                </div>
              )}
            </div>
            {reason && <p className="text-sm leading-relaxed opacity-80">{reason}</p>}
            {nextAction && (
              <div className="mt-4 inline-block px-3 py-1 rounded-full bg-surface-container text-xs font-mono">
                Next action: {nextAction}
              </div>
            )}
          </div>

          {/* Transcript summary */}
          <div className="bg-surface-container-low rounded-2xl p-6">
            <h3 className="font-semibold text-sm mb-4">Interview Transcript ({messages.length} turns)</h3>
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {messages.map((msg, i) => (
                <div key={i} className="flex gap-2">
                  <span className={`text-[10px] uppercase font-bold w-8 flex-shrink-0 ${msg.role === 'agent' ? 'text-primary' : 'text-secondary'}`}>
                    {msg.role === 'agent' ? 'AI' : 'You'}
                  </span>
                  <p className="text-xs text-on-surface-variant leading-relaxed">{msg.text}</p>
                </div>
              ))}
            </div>
          </div>

          <button
            onClick={reset}
            className="bg-surface-container-high text-on-surface px-6 py-3 rounded-xl font-semibold text-sm hover:bg-surface-bright transition-colors flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">restart_alt</span>
            Start New Interview
          </button>
        </div>
      )}
    </div>
  )
}
