import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes } from './App'
import { AuthProvider } from './auth'
import { chunkCsv } from './csv'
import { app, ME, META, mockApi } from './test/mockApi'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const signedOut = () => ({ status: 401, body: { detail: 'Please sign in.' } })

const CHECKS = [
  { id: 'link_present', label: 'Link to the job', result: 'pass', detail: 'A link was given.' },
  { id: 'domain_age', label: 'Website age', result: 'warn', detail: 'Registered 12 days ago.' },
  { id: 'fee_language', label: 'Asks for money', result: 'pass', detail: 'No request for fees.' },
]

function role(overrides: Record<string, unknown> = {}) {
  return {
    id: 'r1',
    title: 'Data Analyst',
    company_name: 'Tausi Analytics',
    job_url: 'https://tausi.co.ke/jobs/1',
    location: 'Nairobi',
    remote: false,
    deadline: null,
    status: 'unverified',
    checks: CHECKS,
    posted_by: 'amina',
    created_at: '2026-11-27T06:00:00Z',
    checked_at: '2026-11-27T06:00:00Z',
    mine: false,
    pending_review: false,
    ...overrides,
  }
}

const page = (items: unknown[]) => ({ items, total: items.length, next_offset: null })

describe('board', () => {
  it('lists roles for visitors, with labels and the checks behind them', async () => {
    mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': signedOut, 'GET /api/board': page([role()]) })
    renderAt('/board')
    const card = await screen.findByRole('article', { name: 'Data Analyst' })
    expect(within(card).getByText('Unverified')).toBeInTheDocument()
    expect(within(card).getByText('Shared by amina')).toBeInTheDocument()
    expect(within(card).getByText('Checks: 1 warning')).toBeInTheDocument()
    // Results are words, not just colours; warnings come before passes.
    const items = within(card).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Warning')
    expect(items[0]).toHaveTextContent('Website age.')
    expect(within(card).getByRole('link', { name: 'Sign in to save' })).toHaveAttribute('href', '/login')
    expect(within(card).queryByRole('button', { name: 'Report' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('1 role')
  })

  it('sends the filters and keeps them in the address', async () => {
    const calls = mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': signedOut, 'GET /api/board': page([]) })
    renderAt('/board')
    await screen.findByText('No roles match yet.')
    await userEvent.type(screen.getByLabelText('Search'), 'analyst')
    await userEvent.click(screen.getByText('More filters'))
    await userEvent.click(screen.getByLabelText('Remote only'))
    await userEvent.selectOptions(screen.getByLabelText('Deadline'), '7')
    await userEvent.click(screen.getByRole('button', { name: 'Show roles' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path.includes('q=analyst') && c.path.includes('remote=true') && c.path.includes('due_within_days=7'))).toBe(true),
    )
  })

  it('saves a role to the tracker and reports another', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/board': page([role(), role({ id: 'r2', title: 'Clerk', mine: true })]),
      'POST /api/board/r1/save': () => ({ status: 201, body: { ...app({ id: 'a9', source: 'board' }), events: [] } }),
      'POST /api/board/r1/report': () => ({ status: 201, body: { detail: 'Thank you. Three reports take a role off.' } }),
    })
    renderAt('/board')
    const card = await screen.findByRole('article', { name: 'Data Analyst' })
    await userEvent.click(within(card).getByRole('button', { name: 'Save to my tracker' }))
    expect(await within(card).findByRole('link', { name: 'Open it' })).toHaveAttribute('href', '/applications/a9')
    expect(calls.find((c) => c.path === '/api/board/r1/save')?.headers['X-CSRF-Token']).toBe('csrf-123')

    // Your own post can't be reported.
    const mine = screen.getByRole('article', { name: 'Clerk' })
    expect(within(mine).queryByRole('button', { name: 'Report' })).not.toBeInTheDocument()

    await userEvent.click(within(card).getByRole('button', { name: 'Report' }))
    const form = within(card).getByRole('form', { name: 'Report this role' })
    await userEvent.selectOptions(within(form).getByLabelText("What's wrong?"), 'fake')
    await userEvent.type(within(form).getByLabelText(/Anything a moderator/), 'No such company')
    await userEvent.click(within(form).getByRole('button', { name: 'Send report' }))
    expect(await within(card).findByText(/Three reports take a role off/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/board/r1/report')?.body).toEqual({ reason: 'fake', note: 'No such company' })
  })
})

describe('sharing a role', () => {
  it('posts the role and shows what the checks found', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'POST /api/board': () => ({
        status: 201,
        body: { role: role({ pending_review: true, mine: true }), message: 'Thank you! A moderator will look at it.', lookups_paused: false },
      }),
    })
    renderAt('/board/new')
    await userEvent.type(await screen.findByLabelText('Role title'), 'Data Analyst')
    await userEvent.type(screen.getByLabelText('Company'), 'Tausi Analytics')
    await userEvent.type(screen.getByLabelText('Link to the job ad'), 'https://tausi.co.ke/jobs/1')
    await userEvent.type(screen.getByLabelText(/The ad's text/), 'Apply on our site.')
    await userEvent.click(screen.getByRole('button', { name: 'Check and share' }))
    expect(await screen.findByRole('heading', { name: 'Thank you for sharing' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for review')).toBeInTheDocument()
    expect(screen.getByText(/A moderator will look at it/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/api/board')?.body).toMatchObject({
      title: 'Data Analyst',
      job_url: 'https://tausi.co.ke/jobs/1',
      ad_text: 'Apply on our site.',
      remote: false,
    })
  })

  it('says plainly when a post is flagged', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'POST /api/board': () => ({
        status: 201,
        body: {
          role: role({ status: 'flagged', checks: [{ id: 'fee_language', label: 'Asks for money', result: 'flag', detail: 'Mentions a fee.' }] }),
          message: 'Not posted: the checks flagged this ad as a likely scam.',
          lookups_paused: false,
        },
      }),
    })
    renderAt('/board/new')
    await userEvent.type(await screen.findByLabelText('Role title'), 'x')
    await userEvent.type(screen.getByLabelText('Company'), 'y')
    await userEvent.type(screen.getByLabelText('Link to the job ad'), 'https://y.com/j')
    await userEvent.click(screen.getByRole('button', { name: 'Check and share' }))
    expect(await screen.findByRole('heading', { name: 'Not posted' })).toBeInTheDocument()
    expect(screen.getByText('Flagged: likely scam')).toBeInTheDocument()
    expect(screen.getByText(/Red flag/)).toBeInTheDocument()
  })

  it('shows a rejected link under the link field', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'POST /api/board': () => ({
        status: 422,
        body: { detail: [{ loc: ['body', 'job_url'], msg: 'Value error, Add the link to the job ad, starting with https://' }] },
      }),
    })
    renderAt('/board/new')
    await userEvent.type(await screen.findByLabelText('Role title'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Check and share' }))
    const link = screen.getByLabelText('Link to the job ad')
    await waitFor(() => expect(link).toHaveAttribute('aria-invalid', 'true'))
    expect(link).toHaveAccessibleDescription(/starting with https:\/\//)
  })

  it('lists my posts and deletes one', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/board/mine': page([role({ mine: true, status: 'flagged' })]),
      'DELETE /api/board/r1': () => ({ status: 204 }),
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderAt('/board/mine')
    const card = await screen.findByRole('article', { name: 'Data Analyst' })
    expect(within(card).getByText(/isn't on the board/)).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: 'Delete post' }))
    expect(await screen.findByText('Deleted "Data Analyst".')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/board/r1')).toBe(true)
  })
})

describe('Is this job real?', () => {
  it('checks pasted text without an account and focuses the answer', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': signedOut,
      'POST /api/check': {
        verdict: 'flagged',
        summary: "Be careful: this looks like a scam. Don't pay anything.",
        checks: [{ id: 'fee_language', label: 'Asks for money', result: 'flag', detail: 'Mentions a registration fee.' }],
        lookups_paused: false,
      },
    })
    renderAt('/check')
    await userEvent.type(await screen.findByLabelText("The ad's text"), 'Pay a registration fee')
    await userEvent.click(screen.getByRole('button', { name: 'Check this job' }))
    const heading = await screen.findByRole('heading', { name: 'Likely a scam' })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(screen.getByText(/Mentions a registration fee/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/check')?.body).toEqual({
      url: null,
      text: 'Pay a registration fee',
      company: '',
      agency: null,
    })
  })
})

describe('moderation', () => {
  it('sends non-admins away', async () => {
    mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': ME, 'GET /api/applications': page([]) })
    renderAt('/admin')
    expect(await screen.findByRole('heading', { level: 1, name: 'My applications' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Moderation' })).not.toBeInTheDocument()
  })

  it('lets an admin approve a waiting post', async () => {
    const pending = { ...role({ id: 'p1', title: 'Waiting role' }), report_count: 0, reports: [], approved: false }
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': { ...ME, is_admin: true },
      'GET /api/admin/queue': { pending: [pending], hidden: [], flagged: [] },
      'GET /api/admin/nea': { total: 0, synced_at: null },
      'POST /api/admin/board/p1/approve': { ...pending, approved: true },
    })
    renderAt('/admin')
    expect(await screen.findByRole('link', { name: 'Moderation' })).toBeInTheDocument()
    const card = await screen.findByRole('article', { name: 'Waiting role' })
    await userEvent.click(within(card).getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText('Waiting role: approved.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/admin/board/p1/approve')).toBe(true)
    expect(screen.getByText(/No list loaded yet/)).toBeInTheDocument()
  })
})

describe('chunkCsv', () => {
  it('splits on line ends and repeats the header', () => {
    const csv = 'Name,Status\r\n' + Array.from({ length: 10 }, (_, i) => `Agency ${i},Active`).join('\r\n') + '\r\n'
    const chunks = chunkCsv(csv, 60)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) {
      expect(chunk.startsWith('Name,Status\n')).toBe(true)
      expect(chunk.length).toBeLessThanOrEqual(60)
    }
    expect(chunks.flatMap((c) => c.split('\n').slice(1))).toHaveLength(10)
    expect(chunkCsv('Name\n')).toEqual(['Name'])
  })
})
