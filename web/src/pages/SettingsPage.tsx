import { useTitle } from '../useTitle'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { api, type DigestPreview } from '../api'
import { useAuth } from '../auth-context'
import { Field, FormError } from '../components/Field'
import { errorMessage } from '../errors'
import { dueLabel } from '../dates'

export function SettingsPage() {
  useTitle('Settings')
  const { me, refresh } = useAuth()
  const navigate = useNavigate()
  const [preview, setPreview] = useState<DigestPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirm, setConfirm] = useState('')
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    api.digestPreview().then(setPreview, (e: unknown) => setError(errorMessage(e)))
  }, [me?.reminder_opt_in, me?.email_verified])

  if (!me) return null

  async function toggleReminders(on: boolean) {
    setError(null)
    try {
      await api.updateSettings(on)
      await refresh()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function resend() {
    setError(null)
    try {
      setNotice((await api.resendVerification()).detail)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function deleteAccount(event: FormEvent) {
    event.preventDefault()
    setDeleting(true)
    setError(null)
    try {
      await api.deleteAccount(confirm)
      await refresh()
      navigate('/goodbye')
    } catch (e) {
      setError(errorMessage(e))
      setDeleting(false)
    }
  }

  return (
    <div className="settings">
      <h1>Settings</h1>
      <FormError message={error} />
      {notice && <p role="status">{notice}</p>}

      <section aria-labelledby="account-h">
        <h2 id="account-h">Account</h2>
        <dl>
          <dt>Email</dt>
          <dd>
            {me.email} {me.email_verified ? <span className="badge ok">confirmed</span> : <span className="badge warn">not confirmed</span>}
          </dd>
          <dt>Handle</dt>
          <dd>{me.handle}</dd>
        </dl>
        {!me.email_verified && (
          <button type="button" onClick={resend}>
            Send a new confirmation link
          </button>
        )}
      </section>

      <section aria-labelledby="reminders-h">
        <h2 id="reminders-h">Reminders</h2>
        <label className="check">
          <input type="checkbox" checked={me.reminder_opt_in} onChange={(e) => void toggleReminders(e.target.checked)} />
          Email me one digest each morning when deadlines are in the next 3 days
        </label>
        {preview && (
          <div className="preview">
            <h3>Next digest</h3>
            {preview.will_send ? (
              <ul>
                {preview.items.map((i) => (
                  <li key={`${i.role_title}-${i.deadline}`}>
                    {i.role_title} at {i.company_name}: {dueLabel(i.deadline)}
                  </li>
                ))}
              </ul>
            ) : (
              <ul className="muted">
                {preview.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section aria-labelledby="export-h">
        <h2 id="export-h">Your data</h2>
        <p>Download everything we hold about you: your account details, every application and its stage history, as JSON.</p>
        <a className="button" href="/api/account/export" download>
          Download my data
        </a>
      </section>

      <section aria-labelledby="delete-h" className="danger-zone">
        <h2 id="delete-h">Delete account</h2>
        <p>
          This permanently deletes your account, every application and its history. It can't be undone, so download your data first.
        </p>
        <form onSubmit={deleteAccount}>
          <Field
            label={`Type your handle (${me.handle}) to confirm`}
            autoComplete="off"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <button className="danger" disabled={deleting || confirm.trim().toLowerCase() !== me.handle}>
            {deleting ? 'Deleting…' : 'Delete my account for good'}
          </button>
        </form>
      </section>
    </div>
  )
}

export function GoodbyePage() {
  useTitle('Account deleted')
  return (
    <section className="auth-card">
      <h1>Your account is deleted</h1>
      <p>Everything we held about you is gone. Thank you for trying us, and good luck with your search.</p>
    </section>
  )
}
