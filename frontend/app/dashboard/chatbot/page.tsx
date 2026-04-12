'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { friendlyError } from '@/lib/errors'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Message {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean   // true while we're still receiving chunks
}

interface ChatSession {
  id: string            // UUID — server uses this to track history
  title: string         // first user message (truncated)
  messages: Message[]
  createdAt: Date
}

// ─── Suggested starter questions ─────────────────────────────────────────────

const SUGGESTIONS = [
  'How do I upload a resume?',
  'What file formats are accepted?',
  'How do I start an interview?',
  'What does the AI Detection feature do?',
  'How is the scoring calculated?',
  'What does "On Hold" status mean?',
]

// ─── Helpers ─────────────────────────────────────────────────────────────────

function newSessionId(): string {
  // crypto.randomUUID() is available in modern browsers and Node 14.17+
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)
}

function sessionTitle(firstMessage: string): string {
  return firstMessage.length > 40
    ? firstMessage.slice(0, 40) + '…'
    : firstMessage
}

// Render assistant message — convert basic markdown to JSX-safe HTML strings
// We keep this simple: bold (**text**), inline code (`text`), line breaks
function renderContent(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="bg-surface-container px-1 py-0.5 rounded text-primary text-[11px] font-mono">$1</code>')
    .replace(/\n/g, '<br />')
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ─── Component ───────────────────────────────────────────────────────────────

export default function ChatbotPage() {
  const [sessions,       setSessions]       = useState<ChatSession[]>([])
  const [activeId,       setActiveId]       = useState<string | null>(null)
  const [input,          setInput]          = useState('')
  const [streaming,      setStreaming]       = useState(false)
  const [error,          setError]          = useState<string | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef    = useRef<HTMLTextAreaElement>(null)
  const abortRef       = useRef<AbortController | null>(null)

  // The currently active session object
  const activeSession = sessions.find(s => s.id === activeId) ?? null

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeSession?.messages])

  // Auto-resize textarea as user types
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [input])

  // ── Session management ──────────────────────────────────────────────────

  const createSession = useCallback((): ChatSession => {
    const session: ChatSession = {
      id:        newSessionId(),
      title:     'New Chat',
      messages:  [],
      createdAt: new Date(),
    }
    setSessions(prev => [session, ...prev])
    setActiveId(session.id)
    return session
  }, [])

  // Start fresh on first render
  useEffect(() => {
    if (sessions.length === 0) createSession()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function updateSession(id: string, updater: (s: ChatSession) => ChatSession) {
    setSessions(prev => prev.map(s => s.id === id ? updater(s) : s))
  }

  function switchSession(id: string) {
    if (streaming) abortRef.current?.abort()
    setActiveId(id)
    setError(null)
    setInput('')
  }

  // ── Send message ────────────────────────────────────────────────────────

  async function send(text?: string) {
    const msg = (text ?? input).trim()
    if (!msg || streaming) return
    setInput('')
    setError(null)

    // Ensure we have an active session
    let session = activeSession
    if (!session) session = createSession()
    const sessionId = session.id

    // Update title from first message
    if (session.messages.length === 0) {
      updateSession(sessionId, s => ({ ...s, title: sessionTitle(msg) }))
    }

    // Add user message
    const userMsg: Message = { role: 'user', content: msg }
    updateSession(sessionId, s => ({ ...s, messages: [...s.messages, userMsg] }))

    // Add placeholder assistant message (will be filled by stream)
    const assistantMsg: Message = { role: 'assistant', content: '', streaming: true }
    updateSession(sessionId, s => ({ ...s, messages: [...s.messages, assistantMsg] }))

    setStreaming(true)
    abortRef.current = new AbortController()

    const fd = new FormData()
    fd.append('session_id', sessionId)
    fd.append('message', msg)

    try {
      const res = await fetch(`${BASE_URL}/portal/chat/stream`, {
        method: 'POST',
        body:   fd,
        signal: abortRef.current.signal,
      })

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`)
      }

      const reader  = res.body!.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines  = buffer.split('\n')
        buffer = lines.pop() ?? ''   // keep incomplete last line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') break

          try {
            const { chunk } = JSON.parse(data) as { chunk: string }
            if (chunk) {
              // Append chunk to the streaming assistant message
              updateSession(sessionId, s => {
                const msgs = [...s.messages]
                const last = msgs[msgs.length - 1]
                if (last?.role === 'assistant') {
                  msgs[msgs.length - 1] = { ...last, content: last.content + chunk }
                }
                return { ...s, messages: msgs }
              })
            }
          } catch { /* skip malformed lines */ }
        }
      }

    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const msg = friendlyError(err)
      setError(msg)
      // Remove the empty assistant placeholder on error
      updateSession(sessionId, s => ({
        ...s,
        messages: s.messages.filter((_, i) => i !== s.messages.length - 1),
      }))
    } finally {
      // Mark streaming as done — remove the streaming flag from last message
      updateSession(sessionId, s => {
        const msgs = [...s.messages]
        const last = msgs[msgs.length - 1]
        if (last?.streaming) msgs[msgs.length - 1] = { ...last, streaming: false }
        return { ...s, messages: msgs }
      })
      setStreaming(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="h-[calc(100vh-64px)] flex animate-fade-in overflow-hidden">

      {/* ── Left: Session History ── */}
      <aside className="w-72 bg-surface-container-low border-r border-outline-variant/5 flex flex-col flex-shrink-0">
        <div className="p-6 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[11px] font-semibold text-on-surface-variant uppercase tracking-[0.2em]">
              Conversations
            </h2>
            <button
              onClick={() => { createSession(); setError(null) }}
              className="text-[10px] font-bold text-primary uppercase tracking-wider hover:text-white transition-colors"
            >
              + New
            </button>
          </div>

          {sessions.length === 0 ? (
            <p className="text-xs text-on-surface-variant opacity-40 text-center mt-8">No conversations yet</p>
          ) : (
            <div className="space-y-1.5">
              {sessions.map(session => (
                <button
                  key={session.id}
                  onClick={() => switchSession(session.id)}
                  className={`w-full text-left p-3 rounded-xl group transition-colors ${
                    session.id === activeId
                      ? 'bg-surface-container border-l-2 border-primary'
                      : 'hover:bg-surface-container-lowest'
                  }`}
                >
                  <p className={`text-xs font-medium line-clamp-2 mb-1 ${
                    session.id === activeId ? 'text-on-surface' : 'text-on-surface-variant group-hover:text-on-surface'
                  }`}>
                    {session.title}
                  </p>
                  <span className="text-[10px] font-mono text-on-surface-variant opacity-50 uppercase">
                    {session.messages.length} messages
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* KB info card */}
        <div className="p-4 m-4 bg-surface-container rounded-xl border border-outline-variant/10">
          <p className="text-[9px] font-bold text-secondary tracking-widest uppercase mb-1.5">Knowledge Base</p>
          <p className="text-[10px] text-on-surface-variant leading-relaxed">
            Powered by Groq · llama-3.3-70b-versatile · RAG-enabled
          </p>
        </div>
      </aside>

      {/* ── Right: Chat Area ── */}
      <section className="flex-1 flex flex-col relative bg-surface overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-8 py-4 border-b border-outline-variant/5 bg-surface-container-lowest/50 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary-container flex items-center justify-center">
              <span className="material-symbols-outlined text-on-primary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>smart_toy</span>
            </div>
            <div>
              <p className="text-sm font-bold text-on-surface">HireIQ Assistant</p>
              <p className="text-[10px] font-mono text-secondary opacity-80 uppercase tracking-widest">
                Platform Guide · RAG · Groq
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${streaming ? 'bg-primary animate-pulse' : 'bg-secondary'}`}></div>
            <span className="text-xs font-mono text-secondary">{streaming ? 'Thinking…' : 'Online'}</span>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-8 py-6 space-y-6 pb-48">

          {/* Empty state */}
          {(!activeSession || activeSession.messages.length === 0) && (
            <div className="flex flex-col items-center justify-center h-full text-center gap-6 -mt-6">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-primary-container/20 flex items-center justify-center">
                <span className="material-symbols-outlined text-3xl text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>smart_toy</span>
              </div>
              <div>
                <h2 className="text-xl font-bold text-white mb-2">How can I help you?</h2>
                <p className="text-sm text-on-surface-variant max-w-sm">
                  Ask me anything about the HireIQ platform — how to upload resumes, start interviews, read results, or understand the AI pipeline.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2 max-w-lg">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="px-4 py-2 bg-surface-container-high border border-outline-variant/10 text-[11px] font-semibold text-on-surface-variant hover:text-white hover:bg-surface-bright rounded-full transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Message list */}
          {activeSession?.messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 max-w-3xl ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : ''}`}
            >
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-xs font-bold ${
                msg.role === 'assistant'
                  ? 'bg-surface-container border border-outline-variant/10'
                  : 'bg-primary-container'
              }`}>
                {msg.role === 'assistant'
                  ? <span className="material-symbols-outlined text-primary text-[18px]">smart_toy</span>
                  : <span className="material-symbols-outlined text-on-primary-container text-[18px]">person</span>
                }
              </div>

              {/* Bubble */}
              <div className={`rounded-2xl px-5 py-3 text-sm leading-relaxed max-w-[85%] ${
                msg.role === 'user'
                  ? 'bg-primary/10 text-on-surface rounded-tr-none'
                  : 'bg-surface-container-low text-on-surface rounded-tl-none'
              }`}>
                {msg.role === 'assistant' ? (
                  <>
                    {msg.content ? (
                      <div
                        dangerouslySetInnerHTML={{ __html: renderContent(msg.content) }}
                        className="prose-sm"
                      />
                    ) : null}
                    {/* Typing indicator while streaming and content is still empty */}
                    {msg.streaming && !msg.content && (
                      <div className="flex items-center gap-1.5 py-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    )}
                    {/* Blinking cursor while streaming */}
                    {msg.streaming && msg.content && (
                      <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 align-middle animate-pulse" />
                    )}
                  </>
                ) : (
                  <p>{msg.content}</p>
                )}
              </div>
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>

        {/* Error banner */}
        {error && (
          <div className="absolute bottom-[160px] left-8 right-8 p-3 rounded-xl bg-error/10 border border-error/30 flex items-center gap-3">
            <span className="material-symbols-outlined text-error text-sm">error</span>
            <p className="text-xs text-error flex-1">{error}</p>
            <button onClick={() => setError(null)} className="text-error hover:text-white">
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        )}

        {/* Input Area */}
        <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-surface via-surface/95 to-transparent">
          <div className="max-w-4xl mx-auto flex flex-col items-center gap-3">

            {/* Suggestion chips (only show if conversation is active but short) */}
            {activeSession && activeSession.messages.length > 0 && activeSession.messages.length < 3 && (
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.slice(0, 4).map(s => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    disabled={streaming}
                    className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/10 text-[10px] font-semibold text-on-surface-variant hover:text-white hover:bg-surface-bright rounded-full transition-all disabled:opacity-40 uppercase tracking-wider"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {/* Input bar */}
            <div className="w-full bg-surface-container-low border border-outline-variant/10 rounded-2xl p-2 shadow-[0_20px_50px_rgba(0,0,0,0.4)] flex items-end gap-2 focus-within:border-primary/30 transition-colors">
              <textarea
                ref={textareaRef}
                className="flex-1 bg-transparent border-none text-on-surface placeholder:text-on-surface-variant/40 py-2.5 px-3 resize-none focus:ring-0 text-sm outline-none max-h-40"
                placeholder="Ask anything about HireIQ…"
                rows={1}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                disabled={streaming}
              />
              <button
                onClick={() => send()}
                disabled={streaming || !input.trim()}
                className="w-10 h-10 mb-0.5 bg-gradient-to-br from-primary to-primary-container text-on-primary rounded-xl flex items-center justify-center disabled:opacity-40 hover:shadow-[0_0_20px_rgba(77,142,255,0.3)] transition-all active:scale-95 flex-shrink-0"
              >
                {streaming
                  ? <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
                  : <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>send</span>
                }
              </button>
            </div>

            <p className="text-[9px] text-on-surface-variant opacity-30 uppercase tracking-[0.2em]">
              HireIQ Assistant · RAG · Press Enter to send · Shift+Enter for new line
            </p>
          </div>
        </div>

        {/* Background glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-primary-container/5 blur-[120px] rounded-full pointer-events-none -z-10" />
      </section>
    </div>
  )
}
