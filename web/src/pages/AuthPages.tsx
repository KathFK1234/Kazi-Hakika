import { useTitle } from '../useTitle'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api } from '../api'
import { useAuth } from '../auth-context'
import { Field, FormError } from '../components/Field'
import { errorMessage } from '../errors'

function useSubmit<T>(action: () => Promise<T>, onDone: (result: T) => void) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(await action())
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return { error, busy, submit }
}

export function LoginPage() {
  useTitle('Sign in')
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { error, busy, submit } = useSubmit(
    async () => {
      await api.login(email, password)
      await refresh()
    },
    () => navigate('/'),
  )
  return (
    <section className="auth-card">
      <h1>Sign in</h1>
      <form onSubmit={submit} noValidate>
        <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <FormError message={error} />
        <button className="primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <p>
        <Link to="/forgot-password">Forgot your password?</Link>
      </p>
      <p>
        New here? <Link to="/signup">Create a free account</Link>
      </p>
    </section>
  )
}

export function SignupPage() {
  useTitle('Create your account')
  const [email, setEmail] = useState('')
  const [handle, setHandle] = useState('')
  const [password, setPassword] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const { error, busy, submit } = useSubmit(
    () => api.signup(email, password, handle),
    (r) => setDone(r.detail),
  )
  if (done) {
    return (
      <section className="auth-card">
        <h1>Check your email</h1>
        <p>{done} The link works for 24 hours.</p>
        <p>
          You can <Link to="/login">sign in</Link> straight away; reminders start once your email is confirmed.
        </p>
      </section>
    )
  }
  return (
    <section className="auth-card">
      <h1>Create your account</h1>
      <p className="muted">
        Free. Your applications are private to you. <Link to="/privacy">What we store</Link>
      </p>
      <form onSubmit={submit} noValidate>
        <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field
          label="Handle"
          autoComplete="username"
          required
          minLength={3}
          maxLength={30}
          pattern="[a-zA-Z0-9_-]{3,30}"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          hint="Public name for anything you share later. 3 to 30 letters, numbers, - or _. Not your real name."
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint="At least 10 characters. A short phrase is easy to remember."
        />
        <FormError message={error} />
        <button className="primary" disabled={busy}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
      </form>
      <p>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </section>
  )
}

/** Tokens arrive in the URL fragment (#token=...), which never reaches the server's logs. */
function tokenFromHash(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
}

function clearHash() {
  window.history.replaceState(null, '', window.location.pathname)
}

export function VerifyEmailPage() {
  useTitle('Confirm your email')
  const { refresh } = useAuth()
  const [token] = useState(tokenFromHash)
  const [state, setState] = useState<'working' | 'done' | 'failed'>(token ? 'working' : 'failed')
  const [message, setMessage] = useState(
    token ? '' : 'This link is incomplete. Open the link from your email again.',
  )
  const started = useRef(false)

  useEffect(() => {
    clearHash()
    if (started.current || !token) return
    started.current = true
    api.verifyEmail(token).then(
      () => {
        setState('done')
        void refresh()
      },
      (e: unknown) => {
        setState('failed')
        setMessage(errorMessage(e))
      },
    )
  }, [refresh, token])

  return (
    <section className="auth-card" aria-live="polite">
      <h1>Confirm your email</h1>
      {state === 'working' && <p>Confirming…</p>}
      {state === 'done' && (
        <p>
          Email confirmed. Deadline reminders are on. <Link to="/">Go to your tracker</Link>
        </p>
      )}
      {state === 'failed' && (
        <>
          <FormError message={message} />
          <p>
            Signed in? You can send a new link from <Link to="/settings">Settings</Link>.
          </p>
        </>
      )}
    </section>
  )
}

export function ForgotPasswordPage() {
  useTitle('Reset your password')
  const [email, setEmail] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const { error, busy, submit } = useSubmit(
    () => api.requestReset(email),
    (r) => setDone(r.detail),
  )
  return (
    <section className="auth-card">
      <h1>Reset your password</h1>
      {done ? (
        <p role="status">{done} The link works for 1 hour.</p>
      ) : (
        <form onSubmit={submit} noValidate>
          <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <FormError message={error} />
          <button className="primary" disabled={busy}>
            {busy ? 'Sending…' : 'Send reset link'}
          </button>
        </form>
      )}
      <p>
        <Link to="/login">Back to sign in</Link>
      </p>
    </section>
  )
}

export function ResetPasswordPage() {
  useTitle('Choose a new password')
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [token] = useState(tokenFromHash)
  const [password, setPassword] = useState('')
  useEffect(clearHash, [])
  const { error, busy, submit } = useSubmit(
    async () => {
      await api.confirmReset(token, password)
      await refresh()
    },
    () => navigate('/'),
  )
  if (!token) {
    return (
      <section className="auth-card">
        <h1>Choose a new password</h1>
        <FormError message="This link is incomplete. Open the link from your email again." />
        <p>
          <Link to="/forgot-password">Ask for a new link</Link>
        </p>
      </section>
    )
  }
  return (
    <section className="auth-card">
      <h1>Choose a new password</h1>
      <p className="muted">This signs you out on every other device.</p>
      <form onSubmit={submit} noValidate>
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          maxLength={128}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint="At least 10 characters."
        />
        <FormError message={error} />
        <button className="primary" disabled={busy}>
          {busy ? 'Saving…' : 'Save password'}
        </button>
      </form>
    </section>
  )
}
