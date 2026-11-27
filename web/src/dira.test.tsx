import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AppRoutes } from './App'
import { AuthProvider } from './auth'
import { parseTags } from './tags'
import { app, ME, META, mockApi } from './test/mockApi'

const ON = { ...META, features: { dira: true } }

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  )
}

function checkin(overrides: Record<string, unknown> = {}) {
  return {
    id: 'c1',
    on_date: '2026-10-01',
    ideal_role: 'Backend engineer at a fintech',
    excited: 'Payments work',
    energised: null,
    drained: null,
    changed: 'Less frontend',
    confidence_planning: 3,
    confidence_control: 2,
    confidence_curiosity: null,
    confidence_action: 4,
    ...overrides,
  }
}

const OVERVIEW = {
  settings: { checkin_interval_weeks: 6, next_checkin_on: '2026-11-27', weekly_target: 3 },
  due: true,
  week: { target: 3, applied_this_week: 1 },
  checkins: [
    checkin({ id: 'c2', on_date: '2026-11-12', ideal_role: 'Platform engineer', confidence_planning: 4 }),
    checkin(),
  ],
}

describe('Dira switched off', () => {
  it('shows no Dira links and no Dira pages', async () => {
    mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': ME, 'GET /api/applications': { items: [], total: 0, next_offset: null } })
    renderAt('/dira')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Dira' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Support' })).not.toBeInTheDocument()
  })
})

describe('Dira', () => {
  it('shows the timeline, compares check-ins and charts confidence', async () => {
    mockApi({ 'GET /api/meta': ON, 'GET /api/auth/me': ME, 'GET /api/dira': OVERVIEW, 'GET /api/dira/entries': [] })
    renderAt('/dira')
    expect(await screen.findByText('Your check-in is ready whenever you are.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dira' })).toHaveAttribute('href', '/dira')
    expect(screen.getByRole('link', { name: 'Support' })).toHaveAttribute('href', '/support')
    expect(screen.getByText('This week so far: 1 of your 3 well-fit applications.')).toBeInTheDocument()
    const timeline = screen.getByRole('list', { name: 'Your direction over time' })
    const items = within(timeline).getAllByRole('article')
    expect(items[0]).toHaveTextContent('Platform engineer')
    expect(items[1]).toHaveTextContent('Backend engineer at a fintech')

    const compare = screen.getByRole('table')
    expect(within(compare).getByRole('rowheader', { name: 'Aiming for' })).toBeInTheDocument()
    expect(within(compare).getAllByText('Backend engineer at a fintech').length).toBe(1)

    // Small multiples, each an image with a text alternative; and a table view.
    expect(screen.getByRole('img', { name: /Planning: .* 3, .* 4\./ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show as a table' }))
    expect(screen.getByRole('columnheader', { name: 'Exploring' })).toBeInTheDocument()
  })

  it('saves a check-in with the roles listed as reminders', async () => {
    const calls = mockApi({
      'GET /api/meta': ON,
      'GET /api/auth/me': ME,
      'GET /api/dira/checkin': {
        last_checkin_on: '2026-10-01',
        checked_in_today: false,
        roles_since: [{ id: 'a1', role_title: 'Data Analyst' }],
      },
      'POST /api/dira/checkins': () => ({ status: 201, body: checkin() }),
      'GET /api/dira': OVERVIEW,
      'GET /api/dira/entries': [],
    })
    renderAt('/dira/checkin')
    expect(await screen.findByText('Data Analyst')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/what role are you aiming for/), 'Platform engineer')
    await userEvent.type(screen.getByLabelText('What drained you?'), 'Cold applications')
    const planning = screen.getByRole('group', { name: 'Planning what comes next in my career' })
    await userEvent.click(within(planning).getByLabelText('Quite'))
    expect(screen.getByRole('link', { name: 'see support' })).toHaveAttribute('href', '/support')
    await userEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
    expect(await screen.findByText(/Check-in saved/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/dira/checkins')?.body).toEqual({
      ideal_role: 'Platform engineer',
      excited: null,
      energised: null,
      drained: 'Cold applications',
      changed: null,
      confidence_planning: 4,
    })
  })

  it('shows a missing ideal role under that question', async () => {
    mockApi({
      'GET /api/meta': ON,
      'GET /api/auth/me': ME,
      'GET /api/dira/checkin': { last_checkin_on: null, checked_in_today: false, roles_since: [] },
      'POST /api/dira/checkins': () => ({
        status: 422,
        body: { detail: [{ loc: ['body', 'ideal_role'], msg: "Value error, Write a sentence about the role you're aiming for." }] },
      }),
    })
    renderAt('/dira/checkin')
    await userEvent.click(await screen.findByRole('button', { name: 'Save check-in' }))
    const ideal = screen.getByLabelText(/what role are you aiming for/)
    await waitFor(() => expect(ideal).toHaveAttribute('aria-invalid', 'true'))
    expect(ideal).toHaveAccessibleDescription(/Write a sentence/)
  })

  it('explains patterns that need more data, and shows ones that have it', async () => {
    mockApi({
      'GET /api/meta': ON,
      'GET /api/auth/me': ME,
      'GET /api/dira/patterns': {
        min_group: 5,
        applications: 7,
        by_tag: [{ name: 'backend', total: 5, reached_screening: 2 }],
        by_source: [],
        stops: null,
        direction: { recent: 6, matching: 4, tags: ['backend'] },
        ideal_role: 'Backend engineer',
      },
    })
    renderAt('/dira/patterns')
    expect(await screen.findByRole('rowheader', { name: 'backend' })).toBeInTheDocument()
    expect(screen.getByText('2 (40%)')).toBeInTheDocument()
    expect(screen.getByText(/By where you found the role: nothing yet/)).toBeInTheDocument()
    expect(screen.getByText(/once 5 or more of your applications have ended/)).toBeInTheDocument()
    expect(screen.getByText(/4 of your 6 roles from the last 60 days/)).toBeInTheDocument()
  })

  it('turns check-ins on in Settings', async () => {
    const calls = mockApi({
      'GET /api/meta': ON,
      'GET /api/auth/me': ME,
      'GET /api/account/digest-preview': { will_send: false, reasons: [], items: [] },
      'GET /api/dira': { ...OVERVIEW, settings: { checkin_interval_weeks: null, next_checkin_on: null, weekly_target: null } },
      'PATCH /api/dira/settings': { checkin_interval_weeks: 4, next_checkin_on: '2026-11-27', weekly_target: 2 },
    })
    renderAt('/settings')
    await userEvent.selectOptions(await screen.findByLabelText('Check-ins'), '4')
    await userEvent.type(screen.getByLabelText(/Weekly target/), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save check-in settings' }))
    expect(await screen.findByText(/Next check-in from/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ checkin_interval_weeks: 4, weekly_target: 2 })
  })

  it('offers one optional learning prompt after a move to Rejected', async () => {
    const calls = mockApi({
      'GET /api/meta': ON,
      'GET /api/auth/me': ME,
      'GET /api/applications': { items: [app({ role_title: 'Data Analyst', stage: 'interview' })], total: 1, next_offset: null },
      'PATCH /api/applications/a1': { ...app({ role_title: 'Data Analyst', stage: 'rejected' }), events: [] },
      'POST /api/dira/entries': () => ({ status: 201, body: { id: 'e1' } }),
    })
    renderAt('/')
    await userEvent.selectOptions(await screen.findByLabelText('Move Data Analyst to'), 'rejected')
    const prompt = await screen.findByRole('form', { name: 'A learning from this role' })
    expect(screen.getByRole('status')).toHaveTextContent('An optional question about it is above the board.')
    await userEvent.type(within(prompt).getByRole('textbox'), 'Prepare system design')
    await userEvent.click(within(prompt).getByRole('button', { name: 'Save learning' }))
    await waitFor(() => expect(screen.queryByRole('form', { name: 'A learning from this role' })).not.toBeInTheDocument())
    expect(calls.find((c) => c.path === '/api/dira/entries')?.body).toEqual({
      kind: 'learning',
      text: 'Prepare system design',
      application_id: 'a1',
      happened_on: null,
    })
  })

  it('lists no invented phone numbers or organisations on /support', async () => {
    mockApi({ 'GET /api/meta': ON, 'GET /api/auth/me': ME })
    renderAt('/support')
    expect(await screen.findByRole('heading', { level: 1, name: 'Support' })).toBeInTheDocument()
    expect(screen.getByRole('main').textContent).not.toMatch(/\d{3}/)
    expect(screen.getByRole('note')).toHaveTextContent(/every contact is real and current/)
  })
})

describe('parseTags', () => {
  it('lowercases and hyphenates', () => {
    expect(parseTags(' Backend, AI  infra,, ')).toEqual(['backend', 'ai-infra'])
  })
})
