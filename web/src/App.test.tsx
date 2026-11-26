import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes } from './App'
import { AuthProvider } from './auth'
import { todayIso } from './dates'
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

const page = (items: unknown[]) => ({ items, total: items.length, next_offset: null })

describe('signed out', () => {
  it('sends visitors from a private page to sign in and signs them in', async () => {
    let signedIn = false
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => (signedIn ? { body: ME } : { status: 401, body: { detail: 'Please sign in.' } }),
      'POST /api/auth/login': () => {
        signedIn = true
        return { body: { detail: 'Signed in.' } }
      },
      'GET /api/applications': page([]),
    })
    renderAt('/settings')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Email'), 'wanjiru@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'My applications' })).toBeInTheDocument()
    const login = calls.find((c) => c.path === '/api/auth/login')
    expect(login?.body).toEqual({ email: 'wanjiru@example.com', password: 'correct horse battery' })
    expect(login?.headers['Content-Type']).toBe('application/json')
  })

  it('shows the API error on a failed sign-in', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => ({ status: 401 }),
      'POST /api/auth/login': () => ({ status: 401, body: { detail: 'Wrong email or password.' } }),
    })
    renderAt('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'nope nope nope')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password.')
  })

  it('reads the verification token from the URL fragment', async () => {
    window.history.replaceState(null, '', '/verify-email#token=abcdefghijklmnopqrstuvwxyz')
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => ({ status: 401 }),
      'POST /api/auth/verify-email': { detail: 'Email confirmed.' },
    })
    renderAt('/verify-email')
    expect(await screen.findByText(/Email confirmed/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/verify-email')?.body).toEqual({
      token: 'abcdefghijklmnopqrstuvwxyz',
    })
    expect(window.location.hash).toBe('')
  })
})

describe('tracker', () => {
  it('shows columns, the due panel, and moves a card with CSRF', async () => {
    const today = todayIso()
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([
        app({ id: 'a1', role_title: 'Data Analyst', deadline: today }),
        app({ id: 'a2', role_title: 'SRE', stage: 'interview' }),
      ]),
      'PATCH /api/applications/a1': (init) => ({
        body: { ...app({ id: 'a1', role_title: 'Data Analyst', deadline: today }), ...JSON.parse(String(init?.body)) },
      }),
    })
    renderAt('/')
    const due = await screen.findByRole('region', { name: 'Due in the next 7 days' })
    expect(within(due).getByText(/Data Analyst/)).toBeInTheDocument()
    expect(within(due).getByText('Due today')).toBeInTheDocument()

    const interview = screen.getByRole('region', { name: /Interview/ })
    expect(within(interview).getByText('SRE')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Move Data Analyst to'), 'applied')
    await waitFor(() => {
      const applied = screen.getByRole('region', { name: /Applied/ })
      expect(within(applied).getByText('Data Analyst')).toBeInTheDocument()
    })
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toEqual({ stage: 'applied' })
    // Keyboard users stay on the card they moved, and hear where it went.
    await waitFor(() => expect(screen.getByLabelText('Move Data Analyst to')).toHaveFocus())
    expect(await screen.findByText('Moved Data Analyst to Applied.')).toBeInTheDocument()
    expect(patch?.headers['X-CSRF-Token']).toBe('csrf-123')
  })

  it('puts the card back if the move fails', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([app({ id: 'a1', role_title: 'Data Analyst' })]),
      'PATCH /api/applications/a1': () => ({ status: 500, body: { detail: 'Server trouble' } }),
    })
    renderAt('/')
    await userEvent.selectOptions(await screen.findByLabelText('Move Data Analyst to'), 'offer')
    expect(await screen.findByRole('alert')).toHaveTextContent('Server trouble')
    const saved = screen.getByRole('region', { name: /Saved/ })
    expect(within(saved).getByText('Data Analyst')).toBeInTheDocument()
  })

  it('a failed move does not undo another card that moved meanwhile', async () => {
    let failFirst: (r: Response) => void = () => {}
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([
        app({ id: 'a1', role_title: 'Data Analyst' }),
        app({ id: 'a2', role_title: 'SRE' }),
      ]),
      'PATCH /api/applications/a2': (init) => ({
        body: { ...app({ id: 'a2', role_title: 'SRE' }), ...JSON.parse(String(init?.body)) },
      }),
    })
    // a1's request hangs until we fail it by hand.
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', (input: string, init?: RequestInit) =>
      input.endsWith('/a1') && init?.method === 'PATCH'
        ? new Promise<Response>((resolve) => {
            failFirst = resolve
          })
        : realFetch(input, init),
    )
    renderAt('/')
    await userEvent.selectOptions(await screen.findByLabelText('Move Data Analyst to'), 'offer')
    await userEvent.selectOptions(screen.getByLabelText('Move SRE to'), 'interview')
    await waitFor(() =>
      expect(within(screen.getByRole('region', { name: /Interview/ })).getByText('SRE')).toBeInTheDocument(),
    )
    failFirst(new Response(JSON.stringify({ detail: 'Server trouble' }), { status: 500 }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Server trouble')
    expect(within(screen.getByRole('region', { name: /Saved/ })).getByText('Data Analyst')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: /Interview/ })).getByText('SRE')).toBeInTheDocument()
  })

  it('links to the job ad safely, and never to a non-http URL', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([
        app({ id: 'a1', role_title: 'Data Analyst', job_url: 'https://jobs.example.com/1' }),
        app({ id: 'a2', role_title: 'SRE', job_url: 'javascript:alert(1)' }),
      ]),
    })
    renderAt('/')
    const links = await screen.findAllByRole('link', { name: /Open job ad/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', 'https://jobs.example.com/1')
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer')
    expect(links[0]).toHaveAttribute('target', '_blank')
  })

  it('switches to the list view', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([app({ role_title: 'Data Analyst', deadline: '2030-01-05' })]),
    })
    renderAt('/')
    await userEvent.click(await screen.findByRole('button', { name: 'List' }))
    const list = screen.getByRole('list', { name: 'Applications sorted by deadline' })
    expect(within(list).getByText('Data Analyst')).toBeInTheDocument()
  })

  it('adds a role', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications': page([]),
      'POST /api/applications': { ...app(), events: [] },
    })
    renderAt('/applications/new')
    await userEvent.type(await screen.findByLabelText('Role title'), 'QA Engineer')
    await userEvent.type(screen.getByLabelText('Company'), 'Twiga')
    await userEvent.click(screen.getByRole('button', { name: 'Add role' }))
    await screen.findByRole('heading', { name: 'My applications' })
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toMatchObject({ role_title: 'QA Engineer', company_name: 'Twiga', stage: 'saved', job_url: null })
  })

  it('shows a rejected field under that field and focuses it', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'POST /api/applications': () => ({
        status: 422,
        body: { detail: [{ loc: ['body', 'job_url'], msg: 'Value error, Use a full http(s) link.' }] },
      }),
    })
    renderAt('/applications/new')
    await userEvent.type(await screen.findByLabelText('Role title'), 'QA Engineer')
    await userEvent.type(screen.getByLabelText('Company'), 'Twiga')
    await userEvent.type(screen.getByLabelText('Job link'), 'ftp://x')
    await userEvent.click(screen.getByRole('button', { name: 'Add role' }))
    const link = screen.getByLabelText('Job link')
    await waitFor(() => expect(link).toHaveAttribute('aria-invalid', 'true'))
    expect(link).toHaveAccessibleDescription('Use a full http(s) link.')
    expect(link).toHaveFocus()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('settings', () => {
  it('only enables delete once the handle is typed', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/account/digest-preview': { will_send: false, reasons: ['Nothing is due in the next 3 days.'], items: [] },
      'DELETE /api/account': () => ({ status: 204 }),
    })
    renderAt('/settings')
    const button = await screen.findByRole('button', { name: 'Delete my account for good' })
    expect(button).toBeDisabled()
    expect(await screen.findByText('Nothing is due in the next 3 days.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Type your handle/), 'Wanjiru')
    expect(button).toBeEnabled()
    await userEvent.click(button)
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')?.body).toEqual({ confirm_handle: 'Wanjiru' })
  })
})
