import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes } from './App'
import { AuthProvider } from './auth'
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

describe('sign-up', () => {
  it('shows "check your email" after signing up', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': signedOut,
      'POST /api/auth/signup': () => ({ status: 202, body: { detail: 'Check your email to finish signing up.' } }),
    })
    renderAt('/signup')
    await userEvent.type(await screen.findByLabelText('Email'), 'amina@example.com')
    await userEvent.type(screen.getByLabelText('Handle'), 'amina')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/signup')?.body).toEqual({
      email: 'amina@example.com',
      password: 'correct horse battery',
      handle: 'amina',
    })
  })

  it('shows the API validation message', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': signedOut,
      'POST /api/auth/signup': () => ({
        status: 422,
        body: { detail: [{ loc: ['body', 'handle'], msg: 'Value error, That handle is reserved. Please pick another.' }] },
      }),
    })
    renderAt('/signup')
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Handle'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('handle: That handle is reserved. Please pick another.')
  })
})

describe('password reset', () => {
  it('requests a reset link', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': signedOut,
      'POST /api/auth/password-reset/request': () => ({
        status: 202,
        body: { detail: 'If that email has an account, a reset link is on its way.' },
      }),
    })
    renderAt('/forgot-password')
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent('a reset link is on its way')
  })

  it('sets a new password with the token from the fragment, then signs in', async () => {
    window.history.replaceState(null, '', '/reset-password#token=resettokenresettokenresettoken')
    let signedIn = false
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => (signedIn ? { body: ME } : signedOut()),
      'POST /api/auth/password-reset/confirm': () => {
        signedIn = true
        return { body: { detail: 'Password changed.' } }
      },
      'GET /api/applications': { items: [], total: 0, next_offset: null },
    })
    renderAt('/reset-password')
    await userEvent.type(await screen.findByLabelText('New password'), 'a brand new passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }))
    expect(await screen.findByRole('heading', { name: 'My applications' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/password-reset/confirm')?.body).toEqual({
      token: 'resettokenresettokenresettoken',
      password: 'a brand new passphrase',
    })
    expect(window.location.hash).toBe('')
  })

  it('explains a link without a token', async () => {
    window.history.replaceState(null, '', '/reset-password')
    mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': signedOut })
    renderAt('/reset-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('This link is incomplete')
  })
})

describe('editing an application', () => {
  const detail = {
    ...app({ id: 'a1', role_title: 'Data Analyst', stage: 'applied', notes: 'Met them at a meetup' }),
    events: [
      { from_stage: null, to_stage: 'saved', at: '2026-11-01T08:00:00Z' },
      { from_stage: 'saved', to_stage: 'applied', at: '2026-11-03T08:00:00Z' },
    ],
  }

  it('loads details and history, and saves changes', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications/a1': detail,
      'PATCH /api/applications/a1': detail,
      'GET /api/applications': { items: [], total: 0, next_offset: null },
    })
    renderAt('/applications/a1')
    expect(await screen.findByDisplayValue('Data Analyst')).toBeInTheDocument()
    const history = screen.getByRole('region', { name: 'Stage history' })
    expect(within(history).getByText(/Saved → Applied/)).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Notes'))
    await userEvent.type(screen.getByLabelText('Notes'), 'Interview on Friday')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByRole('heading', { name: 'My applications' })
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ notes: 'Interview on Friday' })
  })

  it('asks before deleting and does nothing if cancelled', async () => {
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications/a1': detail,
      'DELETE /api/applications/a1': () => ({ status: 204 }),
      'GET /api/applications': { items: [], total: 0, next_offset: null },
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderAt('/applications/a1')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await screen.findByRole('heading', { name: 'My applications' })
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('shows not found for a missing application', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': ME,
      'GET /api/applications/zz': () => ({ status: 404, body: { detail: 'Application not found.' } }),
    })
    renderAt('/applications/zz')
    expect(await screen.findByRole('alert')).toHaveTextContent('Application not found.')
  })
})

describe('account', () => {
  it('turns reminders off', async () => {
    let optIn = true
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => ({ body: { ...ME, reminder_opt_in: optIn } }),
      'GET /api/account/digest-preview': { will_send: false, reasons: ['Reminders are turned off in Settings.'], items: [] },
      'PATCH /api/account/settings': (init) => {
        optIn = JSON.parse(String(init?.body)).reminder_opt_in
        return { body: { reminder_opt_in: optIn } }
      },
    })
    renderAt('/settings')
    const box = await screen.findByRole('checkbox', { name: /Email me one digest/ })
    expect(box).toBeChecked()
    await userEvent.click(box)
    await waitFor(() => expect(box).not.toBeChecked())
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ reminder_opt_in: false })
  })

  it('shows the unconfirmed banner and resends the link', async () => {
    mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': { ...ME, email_verified: false },
      'GET /api/account/digest-preview': { will_send: false, reasons: [], items: [] },
      'POST /api/auth/resend-verification': () => ({ status: 202, body: { detail: 'Check your email.' } }),
    })
    renderAt('/settings')
    expect(await screen.findByText(/Confirm your email to get deadline reminders/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send a new confirmation link' }))
    expect(await screen.findByText('Check your email.')).toBeInTheDocument()
  })

  it('signs out', async () => {
    let signedIn = true
    const calls = mockApi({
      'GET /api/meta': META,
      'GET /api/auth/me': () => (signedIn ? { body: ME } : signedOut()),
      'GET /api/applications': { items: [], total: 0, next_offset: null },
      'POST /api/auth/logout': () => {
        signedIn = false
        return { status: 204 }
      },
    })
    renderAt('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/auth/logout')?.headers['X-CSRF-Token']).toBe('csrf-123')
  })

  it('shows a not-found page for unknown routes', async () => {
    mockApi({ 'GET /api/meta': META, 'GET /api/auth/me': ME })
    renderAt('/no/such/page')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
