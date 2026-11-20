export type Meta = { name: string; tagline: string }

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
  csrf_token: string
}

export type Application = {
  id: string
  role_title: string
  company_name: string
  job_url: string | null
  source: string
  stage: Stage
  deadline: string | null
  applied_on: string | null
  salary_note: string | null
  notes: string
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
}

export type DigestPreview = {
  will_send: boolean
  reasons: string[]
  items: { role_title: string; company_name: string; stage: Stage; deadline: string }[]
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let csrfToken = ''

export function setCsrfToken(token: string) {
  csrfToken = token
}

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  // FastAPI validation errors: [{loc, msg}, ...]
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown }
    if (typeof first.msg === 'string') {
      const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : ''
      const msg = first.msg.replace(/^Value error, /, '')
      return field && field !== 'body' ? `${field.replace(/_/g, ' ')}: ${msg}` : msg
    }
  }
  return fallback
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
    let message = response.status === 429 ? 'Too many attempts. Please wait a minute.' : 'Something went wrong. Please try again.'
    try {
      const data = (await response.json()) as { detail?: unknown }
      message = describe(data.detail, message)
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
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
  deleteAccount: (confirm_handle: string) =>
    request<void>('DELETE', '/api/account', { confirm_handle }),
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
