import { vi } from 'vitest'

type Handler = (init: RequestInit | undefined, url: URL) => { status?: number; body?: unknown }
export type Call = { method: string; path: string; headers: Record<string, string>; body: unknown }

/** Route fetch() calls to handlers keyed by "METHOD /path". Records every call. */
export function mockApi(routes: Record<string, Handler | object>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      const method = init?.method ?? 'GET'
      const headers = (init?.headers ?? {}) as Record<string, string>
      calls.push({
        method,
        path: url.pathname + url.search,
        headers,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      const route = routes[`${method} ${url.pathname}`]
      if (route === undefined) {
        return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
      }
      const result = typeof route === 'function' ? (route as Handler)(init, url) : { body: route }
      const status = result.status ?? 200
      return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), { status })
    }),
  )
  return calls
}

export const ME = {
  id: 'u1',
  email: 'wanjiru@example.com',
  handle: 'wanjiru',
  email_verified: true,
  reminder_opt_in: true,
  csrf_token: 'csrf-123',
}

export const META = { name: 'Kazi Hakika', tagline: 'verified roles, tracked your way.' }

export function app(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a1',
    role_title: 'Backend Engineer',
    company_name: 'Acme',
    job_url: null,
    source: 'own',
    stage: 'saved',
    deadline: null,
    applied_on: null,
    salary_note: null,
    notes: '',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    ...overrides,
  }
}
