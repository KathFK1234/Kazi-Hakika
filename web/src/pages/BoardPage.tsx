import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api, type BoardRole, type ReportReason } from '../api'
import { useAuth } from '../auth-context'
import { checkSummary } from '../checks'
import { CheckList, StatusBadge } from '../components/Checks'
import { FormError } from '../components/Field'
import { JobLink } from '../components/JobLink'
import { dueLabel } from '../dates'
import { errorMessage } from '../errors'
import { useTitle } from '../useTitle'

const REASONS: { value: ReportReason; label: string }[] = [
  { value: 'fee', label: 'It asks for money' },
  { value: 'fake', label: 'The company or role looks fake' },
  { value: 'expired', label: 'The role has closed' },
  { value: 'duplicate', label: 'It is posted twice' },
  { value: 'other', label: 'Something else' },
]

const FILTER_KEYS = ['q', 'location', 'remote', 'due_within_days', 'verified_only'] as const

export function BoardPage() {
  useTitle('Board')
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const [roles, setRoles] = useState<BoardRole[]>([])
  const [total, setTotal] = useState(0)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const queryFor = useCallback(
    (offset: number) => {
      const query = new URLSearchParams()
      for (const key of FILTER_KEYS) {
        const value = params.get(key)
        if (value) query.set(key, value)
      }
      query.set('offset', String(offset))
      return query
    },
    [params],
  )

  // First page for the current filters; a slower, older reply never wins.
  useEffect(() => {
    let active = true
    api.listBoard(queryFor(0)).then(
      (page) => {
        if (!active) return
        setRoles(page.items)
        setTotal(page.total)
        setNextOffset(page.next_offset)
        setError(null)
        setLoading(false)
      },
      (e: unknown) => {
        if (!active) return
        setError(errorMessage(e))
        setLoading(false)
      },
    )
    return () => {
      active = false
    }
  }, [queryFor])

  async function more(offset: number) {
    setLoading(true)
    try {
      const page = await api.listBoard(queryFor(offset))
      setRoles((prev) => [...prev, ...page.items])
      setNextOffset(page.next_offset)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const next = new URLSearchParams()
    for (const key of FILTER_KEYS) {
      const value = String(form.get(key) ?? '').trim()
      if (value) next.set(key, value)
    }
    if (next.toString() === params.toString()) return
    setLoading(true)
    setParams(next)
  }

  return (
    <div className="board-page">
      <div className="toolbar">
        <h1>Board</h1>
        <div className="toolbar-actions">
          <Link className="button primary" to={me ? '/board/new' : '/login'}>
            Share a role
          </Link>
          {me && (
            <Link className="button" to="/board/mine">
              My posts
            </Link>
          )}
        </div>
      </div>
      <p className="lead-small">
        Roles other job seekers found. Every post goes through the same automatic checks as{' '}
        <Link to="/check">Is this job real?</Link>, and anyone signed in can report one. A label is a guide, not a
        guarantee: never pay to apply.
      </p>

      <form className="filters" onSubmit={applyFilters} aria-label="Filter roles">
        <div className="field">
          <label htmlFor="f-q">Search</label>
          <input id="f-q" name="q" type="search" maxLength={100} defaultValue={params.get('q') ?? ''} placeholder="Role or company" />
        </div>
        <div className="field">
          <label htmlFor="f-location">Location</label>
          <input id="f-location" name="location" maxLength={100} defaultValue={params.get('location') ?? ''} placeholder="e.g. Nairobi" />
        </div>
        <div className="field">
          <label htmlFor="f-due">Deadline</label>
          <select id="f-due" name="due_within_days" defaultValue={params.get('due_within_days') ?? ''}>
            <option value="">Any time</option>
            <option value="7">Closing within 7 days</option>
            <option value="30">Closing within 30 days</option>
          </select>
        </div>
        <label className="check">
          <input type="checkbox" name="remote" value="true" defaultChecked={params.get('remote') === 'true'} />
          Remote only
        </label>
        <label className="check">
          <input type="checkbox" name="verified_only" value="true" defaultChecked={params.get('verified_only') === 'true'} />
          Verified only
        </label>
        <button className="primary">Show roles</button>
      </form>

      <FormError message={error} />
      <p className="count-line" role="status" aria-live="polite">
        {loading && roles.length === 0 ? 'Loading roles…' : `${total} role${total === 1 ? '' : 's'}`}
      </p>

      {!loading && roles.length === 0 && !error && (
        <div className="empty">
          <p>No roles match yet.</p>
          {me && <Link to="/board/new">Share one you found</Link>}
        </div>
      )}

      <ul className="role-list">
        {roles.map((role) => (
          <li key={role.id}>
            <RoleCard role={role} signedIn={Boolean(me)} />
          </li>
        ))}
      </ul>

      {nextOffset !== null && (
        <button type="button" disabled={loading} onClick={() => void more(nextOffset)}>
          {loading ? 'Loading…' : 'Show more roles'}
        </button>
      )}
    </div>
  )
}

export function RoleMeta({ role }: { role: BoardRole }) {
  const bits = [role.location, role.remote ? 'Remote' : null, role.deadline ? dueLabel(role.deadline) : null].filter(
    Boolean,
  )
  return bits.length ? <p className="role-meta">{bits.join(' · ')}</p> : null
}

function RoleCard({ role, signedIn }: { role: BoardRole; signedIn: boolean }) {
  const headingId = useId()
  const [notice, setNotice] = useState<{ text: string; to?: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reporting, setReporting] = useState(false)
  const [busy, setBusy] = useState(false)

  async function save() {
    setError(null)
    setBusy(true)
    try {
      const app = await api.saveRole(role.id)
      setNotice({ text: 'Saved to your tracker.', to: `/applications/${app.id}` })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="role-card" aria-labelledby={headingId}>
      <div className="role-head">
        <h2 id={headingId} className="role-title">
          {role.title}
        </h2>
        <StatusBadge status={role.status} pending={role.pending_review} />
      </div>
      <p className="card-company">{role.company_name}</p>
      <RoleMeta role={role} />
      <p className="hint">Shared by {role.posted_by}</p>
      <details className="check-details">
        <summary>Checks: {checkSummary(role.checks)}</summary>
        <CheckList checks={role.checks} />
      </details>
      <div className="role-actions">
        <JobLink url={role.job_url} />
        {signedIn ? (
          <button type="button" onClick={() => void save()} disabled={busy}>
            Save to my tracker
          </button>
        ) : (
          <Link className="button" to="/login">
            Sign in to save
          </Link>
        )}
        {signedIn && !role.mine && !reporting && (
          <button type="button" className="link" onClick={() => setReporting(true)}>
            Report
          </button>
        )}
      </div>
      {notice && (
        <p role="status">
          {notice.text} {notice.to && <Link to={notice.to}>Open it</Link>}
        </p>
      )}
      <FormError message={error} />
      {reporting && (
        <ReportForm
          roleId={role.id}
          onDone={(text) => {
            setReporting(false)
            if (text) setNotice({ text })
          }}
        />
      )}
    </article>
  )
}

function ReportForm({ roleId, onDone }: { roleId: string; onDone: (message: string | null) => void }) {
  const reasonId = useId()
  const noteId = useId()
  const [reason, setReason] = useState<ReportReason>('fee')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.reportRole(roleId, reason, note.trim() || null)
      onDone(result.detail)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <form className="report-form" onSubmit={submit} aria-label="Report this role">
      <div className="field">
        <label htmlFor={reasonId}>What's wrong?</label>
        <select id={reasonId} value={reason} onChange={(e) => setReason(e.target.value as ReportReason)}>
          {REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={noteId}>Anything a moderator should know? (optional)</label>
        <textarea id={noteId} rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      <FormError message={error} />
      <div className="form-actions">
        <button className="primary" disabled={busy}>
          {busy ? 'Sending…' : 'Send report'}
        </button>
        <button type="button" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </form>
  )
}
