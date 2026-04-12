/**
 * lib/api.ts — HireIQ Backend API Client
 *
 * All calls to the FastAPI backend go through this file.
 *
 * Why a single client:
 *   - One place to change the base URL (dev vs staging vs prod)
 *   - All error responses normalized to { message: string }
 *   - Easy to add auth headers (Clerk token) here once and have
 *     every endpoint pick it up automatically
 *
 * Usage:
 *   import { api } from '@/lib/api'
 *   const result = await api.runIngest(formData)
 */

import axios, { AxiosError, AxiosInstance } from 'axios'

// Read from .env.local — falls back to localhost for local dev.
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ─── Types ─────────────────────────────────────────────────────────────────

export interface ApplicantDetailedStatus {
  current_round: string
  total_score: number | null
  rank: number | null
  final_verdict: string | null
  scorer_notes: string | null
}

export interface Applicant {
  id: string
  full_name: string
  email: string
  phone?: string
  location?: string
  role_applied: string
  experience_level: string
  total_experience_months: number
  skills: { name: string; proficiency?: number }[]
  github_url?: string
  portfolio_url?: string
  linkedin_url?: string
  cover_letter?: string
  education?: string
  status: 'pending' | 'shortlisted' | 'accepted' | 'rejected' | 'on_hold'
  source: string
  resume_url?: string
  detailed_status?: ApplicantDetailedStatus
}

export interface ScoredApplicant {
  applicant_id: string
  name: string
  score: number
  grade: string | null
}

export interface IngestResult {
  success: boolean
  summary: string
  total_applicants: number
  shortlisted: number
  on_hold: number
  rejected: number
  failed: number
  skipped: number
  duration_seconds: number | null
  top_shortlisted: ScoredApplicant[]
}

export interface RankResult {
  success: boolean
  summary: string
  stats: Record<string, number>
  shortlisted: number
  on_hold: number
  rejected: number
  thresholds: { shortlist: number; auto_reject: number }
  top_10: Array<{
    rank: number
    applicant_id: string
    name: string
    score: number
    grade: string | null
    percentile: number
  }>
}

export interface InterviewSession {
  applicant_id: string
  name: string
  role: string
  session_id: string | null
  first_question: string | null
  respond_url: string | null
  status_url: string | null
  status: 'started' | 'failed'
  error: string | null
}

export interface InterviewStartResult {
  success: boolean
  total: number
  started: number
  failed: number
  sessions: InterviewSession[]
}

export interface PortalApplicantListResult {
  total: number
  limit: number
  offset: number
  applicants: Applicant[]
}

export interface PortalStatsResult {
  total_applicants: number
  by_status: Record<string, number>
  by_role: Record<string, number>
  timestamp: string
}

export interface HealthResult {
  status: string
  version: string
  timestamp: string
  page_index_size: number
  groq_key_set: boolean
  supabase_set: boolean
}

export interface PipelineConfig {
  shortlist_threshold: number
  auto_reject_threshold: number
  interview_rounds: number
  ai_detection_threshold: number
  max_applicants: number
}

export interface SessionStatusResult {
  session_id: string
  applicant_id: string
  applicant_name: string
  role_applied: string
  status: string
  current_round: number
  total_rounds: number
  questions_asked: number
  responses_given: number
  ai_flags: number
  final_score: number | null
  started_at: string | null
}

export interface InterviewRespondResult {
  is_complete: boolean
  next_question: string | null
  ai_flagged: boolean
  verdict: string | null
  confidence: number | null
  reason: string | null
  next_action: string | null
}

export interface LearnerResult {
  success: boolean
  error: string | null
  summary: string
  data_used: {
    total_accepted: number
    total_rejected: number
    total_on_hold: number
    avg_score_hired: number
    avg_score_rejected: number
    top_red_flags: string[]
  }
  recommendations: {
    weight_adjustments: Record<string, number>
    new_red_flags: string[]
    interview_improvements: string[]
    threshold_recommendations: Record<string, number>
    insights: string[]
  }
}

// ─── API Error ──────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly statusCode: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function toApiError(err: unknown): never {
  if (err instanceof AxiosError) {
    const msg =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message
    throw new ApiError(err.response?.status ?? 500, String(msg))
  }
  throw err
}

// ─── Client factory ─────────────────────────────────────────────────────────

function createClient(): AxiosInstance {
  const client = axios.create({
    baseURL: BASE_URL,
    timeout: 120_000,   // 2 min — ingest can be slow on large CSV files
  })

  // Response interceptor: surface structured error messages.
  client.interceptors.response.use(
    (res) => res,
    (err) => toApiError(err),
  )

  return client
}

const http = createClient()

// ─── API Methods ────────────────────────────────────────────────────────────

export const api = {
  // ── System ──────────────────────────────────────────────────────────────

  /** Check if the backend is running and configured. */
  async health(): Promise<HealthResult> {
    const { data } = await http.get('/health')
    return data
  },

  // ── Pipelines ──────────────────────────────────────────────────────────

  /**
   * Upload a CSV/Excel file of applicants and run the scoring pipeline.
   * Returns a full breakdown: shortlisted / on_hold / rejected / failed.
   */
  async runIngest(file: File): Promise<IngestResult> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post('/run-ingest', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  /**
   * Re-rank all scored applicants currently in PageIndex.
   * Optional threshold overrides let you tighten or loosen the shortlist band.
   */
  async runRank(
    shortlistThreshold?: number,
    autoRejectThreshold?: number,
  ): Promise<RankResult> {
    const params: Record<string, number> = {}
    if (shortlistThreshold != null) params.shortlist_threshold = shortlistThreshold
    if (autoRejectThreshold != null) params.auto_reject_threshold = autoRejectThreshold
    const { data } = await http.post('/run-rank', null, { params })
    return data
  },

  /**
   * Start autonomous interview sessions for all shortlisted applicants.
   * Returns session IDs + first questions for each.
   */
  async runInterviews(): Promise<InterviewStartResult> {
    const { data } = await http.post('/run-interviews')
    return data
  },

  /**
   * Run LearnerAgent analysis on historical hiring outcomes.
   * Call this after processing 20+ applicants through the full pipeline.
   */
  async runLearn(): Promise<LearnerResult> {
    const { data } = await http.post('/run-learn')
    return data
  },

  // ── Portal: Applicants ─────────────────────────────────────────────────

  /**
   * Submit a single job application from the portal form.
   * Supports optional resume file upload (PDF/DOCX).
   */
  async submitApplication(params: {
    full_name: string
    email: string
    role_applied: string
    experience_years: number
    phone?: string
    location?: string
    github_url?: string
    portfolio_url?: string
    linkedin_url?: string
    cover_letter?: string
    education?: string
    skills_raw?: string
    resume?: File
  }): Promise<{ success: boolean; applicant_id: string; applicant: Applicant }> {
    const form = new FormData()
    form.append('full_name', params.full_name)
    form.append('email', params.email)
    form.append('role_applied', params.role_applied)
    form.append('experience_years', String(params.experience_years))
    if (params.phone)        form.append('phone', params.phone)
    if (params.location)     form.append('location', params.location)
    if (params.github_url)   form.append('github_url', params.github_url)
    if (params.portfolio_url) form.append('portfolio_url', params.portfolio_url)
    if (params.linkedin_url) form.append('linkedin_url', params.linkedin_url)
    if (params.cover_letter) form.append('cover_letter', params.cover_letter)
    if (params.education)    form.append('education', params.education)
    if (params.skills_raw)   form.append('skills_raw', params.skills_raw)
    if (params.resume)       form.append('resume', params.resume)
    const { data } = await http.post('/portal/apply', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  /** Bulk upload applicants from a CSV/Excel file via the portal. */
  async bulkUpload(file: File) {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post('/portal/apply/bulk', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  /** List applicants with optional filters and pagination. */
  async listApplicants(params?: {
    status_filter?: string
    role_filter?: string
    limit?: number
    offset?: number
  }): Promise<PortalApplicantListResult> {
    const { data } = await http.get('/portal/applicants', { params })
    return data
  },

  /** Get a single applicant by ID. */
  async getApplicant(id: string): Promise<Applicant> {
    const { data } = await http.get(`/portal/applicants/${id}`)
    return data
  },

  /** Update an applicant's status (pending/shortlisted/accepted/rejected/on_hold). */
  async updateStatus(
    id: string,
    newStatus: string,
  ): Promise<{ success: boolean; new_status: string }> {
    const form = new FormData()
    form.append('new_status', newStatus)
    const { data } = await http.patch(`/portal/applicants/${id}/status`, form)
    return data
  },

  /** Get hiring pipeline stats: counts by status and role. */
  async getStats(): Promise<PortalStatsResult> {
    const { data } = await http.get('/portal/stats')
    return data
  },

  // ── Settings ───────────────────────────────────────────────

  /** Get current pipeline configuration (thresholds, rounds, etc.). */
  async getPipelineConfig(): Promise<PipelineConfig> {
    const { data } = await http.get('/portal/settings/pipeline')
    return data
  },

  /** Partially update pipeline configuration. Only supplied fields change. */
  async updatePipelineConfig(config: Partial<PipelineConfig>): Promise<{ success: boolean; config: PipelineConfig }> {
    const form = new FormData()
    if (config.shortlist_threshold    != null) form.append('shortlist_threshold',    String(config.shortlist_threshold))
    if (config.auto_reject_threshold  != null) form.append('auto_reject_threshold',  String(config.auto_reject_threshold))
    if (config.interview_rounds       != null) form.append('interview_rounds',        String(config.interview_rounds))
    if (config.ai_detection_threshold != null) form.append('ai_detection_threshold', String(config.ai_detection_threshold))
    if (config.max_applicants         != null) form.append('max_applicants',          String(config.max_applicants))
    const { data } = await http.patch('/portal/settings/pipeline', form)
    return data
  },

  // ── Portal: Interviews ─────────────────────────────────────────────────

  /**
   * Start an interview session for a shortlisted applicant.
   * Returns session_id + first question to present to the applicant.
   */
  async startInterview(applicantId: string): Promise<{
    session_id: string
    first_question: string
    round: number
    total_rounds: number
  }> {
    const { data } = await http.post(`/portal/interview/${applicantId}/start`)
    return data
  },

  /**
   * Submit one applicant response and get the next question.
   * When is_complete is true, the verdict field contains the final decision.
   */
  async respondToInterview(
    sessionId: string,
    responseText: string,
  ): Promise<InterviewRespondResult> {
    const form = new FormData()
    form.append('response_text', responseText)
    const { data } = await http.post(`/portal/interview/${sessionId}/respond`, form)
    return data
  },

  /** Poll the current state of an active interview session. */
  async getInterviewStatus(sessionId: string): Promise<SessionStatusResult> {
    const { data } = await http.get(`/portal/interview/${sessionId}/status`)
    return data
  },
}

export default api
