export type Features = { dira: boolean }
export type Meta = { name: string; tagline: string; features?: Features }

export const STAGES = [
  'saved',
  'applied',
  'screening',
  'interview',
  'offer',
  'rejected',
  'withdrawn',
] as const
export type Stage = (typeof STAGES)[number]

export const STAGE_LABELS: Record<Stage, string> = {
  saved: 'Saved',
  applied: 'Applied',
  screening: 'Screening',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

export type Me = {
  id: string
  email: string
  handle: string
  email_verified: boolean
  reminder_opt_in: boolean
  is_admin: boolean
  csrf_token: string
}

export type Application = {
  id: string
  role_title: string
  company_name: string
  job_url: string | null
  source: string
  board_role_id: string | null
  stage: Stage
  deadline: string | null
  applied_on: string | null
  salary_note: string | null
  notes: string
  tags: string[]
  created_at: string
  updated_at: string
}

export type StageEvent = { from_stage: Stage | null; to_stage: Stage; at: string }
export type ApplicationDetail = Application & { events: StageEvent[] }
export type ApplicationPage = { items: Application[]; total: number; next_offset: number | null }

export type ApplicationInput = {
  role_title: string
  company_name: string
  job_url: string | null
  stage: Stage
  deadline: string | null
  applied_on: string | null
  salary_note: string | null
  notes: string
  tags: string[]
}

export type DigestPreview = {
  will_send: boolean
  reasons: string[]
  items: { role_title: string; company_name: string; stage: Stage; deadline: string }[]
}

export type CheckResult = 'pass' | 'warn' | 'flag' | 'unknown' | 'skip'
export type Check = { id: string; label: string; result: CheckResult; detail: string }
export type Verdict = 'verified' | 'unverified' | 'flagged'
export type BoardStatus = Verdict | 'hidden' | 'archived'

export type BoardRole = {
  id: string
  title: string
  company_name: string
  job_url: string
  location: string | null
  remote: boolean
  deadline: string | null
  status: BoardStatus
  checks: Check[]
  posted_by: string
  created_at: string
  checked_at: string
  mine: boolean
  pending_review: boolean
}
export type BoardPage = { items: BoardRole[]; total: number; next_offset: number | null }

export type BoardPostInput = {
  title: string
  company_name: string
  job_url: string
  location: string | null
  remote: boolean
  deadline: string | null
  ad_text: string
  agency_name: string | null
}
export type PostResult = { role: BoardRole; message: string; lookups_paused: boolean }
export type ReportReason = 'fee' | 'fake' | 'expired' | 'duplicate' | 'other'

export type CheckInput = { url: string | null; text: string; company: string; agency: string | null }
export type CheckerResult = { verdict: Verdict; summary: string; checks: Check[]; lookups_paused: boolean }

export type AdminRole = BoardRole & {
  report_count: number
  reports: { reason: ReportReason; note: string | null; created_at: string }[]
  approved: boolean
}
export type ModerationQueue = { pending: AdminRole[]; hidden: AdminRole[]; flagged: AdminRole[] }
export type NeaStatus = { total: number; synced_at: string | null }

export type CheckinInterval = 4 | 6 | 8
export type DiraSettings = {
  checkin_interval_weeks: CheckinInterval | null
  next_checkin_on: string | null
  weekly_target: number | null
}
export const CONFIDENCE = ['planning', 'control', 'curiosity', 'action'] as const
export type ConfidenceKey = (typeof CONFIDENCE)[number]
export type CheckinInput = {
  ideal_role: string
  excited: string | null
  energised: string | null
  drained: string | null
  changed: string | null
} & Partial<Record<`confidence_${ConfidenceKey}`, number | null>>
export type Checkin = Required<CheckinInput> & { id: string; on_date: string }
export type DiraOverview = {
  settings: DiraSettings
  due: boolean
  week: { target: number | null; applied_this_week: number }
  checkins: Checkin[]
}
export type CheckinPrompt = {
  last_checkin_on: string | null
  checked_in_today: boolean
  roles_since: { id: string; role_title: string }[]
}
export type EntryKind = 'win' | 'learning' | 'goal'
export type Entry = {
  id: string
  kind: EntryKind
  text: string
  happened_on: string
  application_id: string | null
  done_at: string | null
}
export type PatternGroup = { name: string; total: number; reached_screening: number }
export type Patterns = {
  min_group: number
  applications: number
  by_tag: PatternGroup[]
  by_source: PatternGroup[]
  stops: { stage: Stage; count: number; ended: number } | null
  direction: { recent: number; matching: number; tags: string[] } | null
  ideal_role: string | null
}

export class ApiError extends Error {
  readonly status: number
  /** The request field the server rejected, when it named one. */
  readonly field?: string
  constructor(status: number, message: string, field?: string) {
    super(message)
    this.status = status
    this.field = field
  }
}

let csrfToken = ''

export function setCsrfToken(token: string) {
  csrfToken = token
}

const FIELD_LABELS: Record<string, string> = {
  email: 'Email',
  password: 'Password', // pragma: allowlist secret (a field label)
  handle: 'Handle',
  role_title: 'Role title',
  company_name: 'Company',
  job_url: 'Job link',
  stage: 'Stage',
  deadline: 'Deadline',
  applied_on: 'Applied on',
  salary_note: 'Salary note',
  notes: 'Notes',
  title: 'Role title',
  location: 'Location',
  ad_text: 'Ad text',
  agency_name: 'Agency name',
  url: 'Job link',
  text: 'Ad text',
  company: 'Company',
  agency: 'Agency name',
  reason: 'Reason',
  note: 'Note',
  tags: 'Tags',
  ideal_role: 'Ideal role',
  weekly_target: 'Weekly target',
}

/** A message people can read, and the field it's about. */
export function describe(detail: unknown, fallback: string): { message: string; field?: string } {
  if (typeof detail === 'string') return { message: detail }
  // FastAPI validation errors: [{loc, msg}, ...]
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown }
    if (typeof first.msg === 'string') {
      const key = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : ''
      const field = key && key !== 'body' ? key : undefined
      // Our own validators write whole sentences; show them as they are.
      if (first.msg.startsWith('Value error, ')) return { message: first.msg.slice('Value error, '.length), field }
      const label = field ? (FIELD_LABELS[field] ?? field.replace(/_/g, ' ')) : ''
      return { message: label ? `${label}: ${first.msg}` : first.msg, field }
    }
  }
  return { message: fallback }
}

export async function request<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message =
      response.status === 429
        ? 'Too many attempts. Please wait a minute.'
        : 'Something went wrong. Please try again.'
    let field: string | undefined
    try {
      const data = (await response.json()) as { detail?: unknown }
      ;({ message, field } = describe(data.detail, message))
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, message, field)
  }
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch {
    // e.g. a proxy's HTML page while the service is waking up
    throw new ApiError(response.status, 'The server sent an unexpected reply. Please try again.')
  }
}

export const getJson = <T>(path: string) => request<T>('GET', path)

export const api = {
  meta: () => getJson<Meta>('/api/meta'),
  me: () => getJson<Me>('/api/auth/me'),
  signup: (email: string, password: string, handle: string) =>
    request<{ detail: string }>('POST', '/api/auth/signup', { email, password, handle }),
  login: (email: string, password: string) =>
    request<{ detail: string }>('POST', '/api/auth/login', { email, password }),
  logout: () => request<void>('POST', '/api/auth/logout'),
  verifyEmail: (token: string) =>
    request<{ detail: string }>('POST', '/api/auth/verify-email', { token }),
  resendVerification: () => request<{ detail: string }>('POST', '/api/auth/resend-verification'),
  requestReset: (email: string) =>
    request<{ detail: string }>('POST', '/api/auth/password-reset/request', { email }),
  confirmReset: (token: string, password: string) =>
    request<{ detail: string }>('POST', '/api/auth/password-reset/confirm', { token, password }),

  listApplications: (params: URLSearchParams) =>
    getJson<ApplicationPage>(`/api/applications?${params.toString()}`),
  getApplication: (id: string) =>
    getJson<ApplicationDetail>(`/api/applications/${encodeURIComponent(id)}`),
  createApplication: (input: ApplicationInput) =>
    request<ApplicationDetail>('POST', '/api/applications', input),
  updateApplication: (id: string, patch: Partial<ApplicationInput>) =>
    request<ApplicationDetail>('PATCH', `/api/applications/${encodeURIComponent(id)}`, patch),
  deleteApplication: (id: string) =>
    request<void>('DELETE', `/api/applications/${encodeURIComponent(id)}`),

  updateSettings: (reminder_opt_in: boolean) =>
    request<{ reminder_opt_in: boolean }>('PATCH', '/api/account/settings', { reminder_opt_in }),
  digestPreview: () => getJson<DigestPreview>('/api/account/digest-preview'),
  deleteAccount: (confirm_handle: string, remove_posts = false) =>
    request<void>('DELETE', '/api/account', { confirm_handle, remove_posts }),

  listBoard: (params: URLSearchParams) => getJson<BoardPage>(`/api/board?${params.toString()}`),
  myPosts: () => getJson<BoardPage>('/api/board/mine'),
  postRole: (input: BoardPostInput) => request<PostResult>('POST', '/api/board', input),
  deletePost: (id: string) => request<void>('DELETE', `/api/board/${encodeURIComponent(id)}`),
  saveRole: (id: string) =>
    request<ApplicationDetail>('POST', `/api/board/${encodeURIComponent(id)}/save`),
  reportRole: (id: string, reason: ReportReason, note: string | null) =>
    request<{ detail: string }>('POST', `/api/board/${encodeURIComponent(id)}/report`, { reason, note }),
  checkJob: (input: CheckInput) => request<CheckerResult>('POST', '/api/check', input),

  dira: () => getJson<DiraOverview>('/api/dira'),
  updateDiraSettings: (checkin_interval_weeks: CheckinInterval | null, weekly_target: number | null) =>
    request<DiraSettings>('PATCH', '/api/dira/settings', { checkin_interval_weeks, weekly_target }),
  checkinPrompt: () => getJson<CheckinPrompt>('/api/dira/checkin'),
  saveCheckin: (input: CheckinInput) => request<Checkin>('POST', '/api/dira/checkins', input),
  deleteCheckin: (id: string) => request<void>('DELETE', `/api/dira/checkins/${encodeURIComponent(id)}`),
  patterns: () => getJson<Patterns>('/api/dira/patterns'),
  entries: (params: URLSearchParams) => getJson<Entry[]>(`/api/dira/entries?${params.toString()}`),
  addEntry: (kind: EntryKind, text: string, application_id: string | null = null, happened_on: string | null = null) =>
    request<Entry>('POST', '/api/dira/entries', { kind, text, application_id, happened_on }),
  updateEntry: (id: string, patch: { text?: string; done?: boolean }) =>
    request<Entry>('PATCH', `/api/dira/entries/${encodeURIComponent(id)}`, patch),
  deleteEntry: (id: string) => request<void>('DELETE', `/api/dira/entries/${encodeURIComponent(id)}`),

  moderationQueue: () => getJson<ModerationQueue>('/api/admin/queue'),
  moderate: (id: string, action: 'approve' | 'hide' | 'restore') =>
    request<AdminRole>('POST', `/api/admin/board/${encodeURIComponent(id)}/${action}`),
  neaStatus: () => getJson<NeaStatus>('/api/admin/nea'),
  uploadNea: (csv: string, replace: boolean) =>
    request<NeaStatus>('POST', '/api/admin/nea', { csv, replace }),
}

/** Every page of a list, 50 at a time (the API's cap). */
export async function listAll(params: URLSearchParams, maxPages = 40): Promise<Application[]> {
  const items: Application[] = []
  let offset: number | null = 0
  for (let page = 0; offset !== null && page < maxPages; page++) {
    params.set('offset', String(offset))
    const result: ApplicationPage = await api.listApplications(params)
    items.push(...result.items)
    offset = result.next_offset
  }
  return items
}
