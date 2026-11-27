import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, type BoardPostInput, type BoardRole, type PostResult } from '../api'
import { useAuth } from '../auth-context'
import { CheckList, StatusBadge } from '../components/Checks'
import { Field, FormError } from '../components/Field'
import { JobLink } from '../components/JobLink'
import { errorMessage, fieldError, formError, toProblem, type Problem } from '../errors'
import { useTitle } from '../useTitle'
import { RoleMeta } from './BoardPage'

const EMPTY: BoardPostInput = {
  title: '',
  company_name: '',
  job_url: '',
  location: null,
  remote: false,
  deadline: null,
  ad_text: '',
  agency_name: null,
}
const AD_TEXT_MAX = 10_000
const FIELDS = ['title', 'company_name', 'job_url', 'location', 'deadline', 'agency_name'] as const
const orNull = (v: string) => (v.trim() === '' ? null : v)

export function BoardPostPage() {
  useTitle('Share a role')
  const { me } = useAuth()
  const [form, setForm] = useState<BoardPostInput>(EMPTY)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<PostResult | null>(null)
  const adId = useId()

  function set<K extends keyof BoardPostInput>(key: K, value: BoardPostInput[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      setResult(await api.postRole(form))
    } catch (e) {
      setProblem(toProblem(e))
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return (
      <section className="form-page" aria-labelledby="posted-h">
        <h1 id="posted-h">{result.role.status === 'flagged' ? 'Not posted' : 'Thank you for sharing'}</h1>
        <p role="status">{result.message}</p>
        {result.lookups_paused && (
          <p className="hint">
            You've run many checks this hour, so we skipped the website lookups this time. The daily check will look at
            the link again.
          </p>
        )}
        <RoleSummary role={result.role} />
        <h2>What the checks found</h2>
        <CheckList checks={result.role.checks} />
        <div className="form-actions">
          <Link className="button primary" to="/board/mine">
            See my posts
          </Link>
          <button
            type="button"
            onClick={() => {
              setResult(null)
              setForm(EMPTY)
            }}
          >
            Share another role
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="form-page">
      <p>
        <Link to="/board">← Board</Link>
      </p>
      <h1>Share a role</h1>
      <p>
        Found a role others should see? Add its link and we'll run the automatic checks. Your handle (
        <strong>{me?.handle}</strong>) is shown with the post; your name and email never are.
      </p>
      <form onSubmit={submit} noValidate>
        <Field label="Role title" name="title" required maxLength={200} error={fieldError(problem, 'title')} value={form.title} onChange={(e) => set('title', e.target.value)} />
        <Field label="Company" name="company_name" required maxLength={200} error={fieldError(problem, 'company_name')} value={form.company_name} onChange={(e) => set('company_name', e.target.value)} />
        <Field
          label="Link to the job ad"
          name="job_url"
          type="url"
          inputMode="url"
          placeholder="https://"
          required
          maxLength={2048}
          hint="The company's own careers page or job site is best. Every post needs a link."
          error={fieldError(problem, 'job_url')}
          value={form.job_url}
          onChange={(e) => set('job_url', e.target.value)}
        />
        <div className="field-row">
          <Field label="Location (optional)" name="location" maxLength={100} placeholder="e.g. Nairobi" error={fieldError(problem, 'location')} value={form.location ?? ''} onChange={(e) => set('location', orNull(e.target.value))} />
          <Field label="Deadline (optional)" name="deadline" type="date" error={fieldError(problem, 'deadline')} value={form.deadline ?? ''} onChange={(e) => set('deadline', orNull(e.target.value))} />
        </div>
        <label className="check">
          <input type="checkbox" checked={form.remote} onChange={(e) => set('remote', e.target.checked)} />
          Remote role
        </label>
        <div className="field">
          <label htmlFor={adId}>The ad's text (optional, recommended)</label>
          <textarea
            id={adId}
            rows={6}
            maxLength={AD_TEXT_MAX}
            value={form.ad_text}
            onChange={(e) => set('ad_text', e.target.value)}
            aria-describedby={`${adId}-hint`}
          />
          <p className="hint" id={`${adId}-hint`}>
            Paste it to check for fees, personal email addresses and WhatsApp-only contact. We use it for the checks and
            then discard it: it isn't saved or shown.
          </p>
        </div>
        <Field
          label="Recruiting agency (only for jobs abroad)"
          name="agency_name"
          maxLength={200}
          hint="Checked against the National Employment Authority's licensed list. Not saved."
          error={fieldError(problem, 'agency_name')}
          value={form.agency_name ?? ''}
          onChange={(e) => set('agency_name', orNull(e.target.value))}
        />
        <FormError message={formError(problem, FIELDS)} />
        <div className="form-actions">
          <button className="primary" disabled={busy}>
            {busy ? 'Checking… (up to 10 seconds)' : 'Check and share'}
          </button>
        </div>
      </form>
    </section>
  )
}

function RoleSummary({ role }: { role: BoardRole }) {
  return (
    <div className="role-card">
      <div className="role-head">
        <p className="role-title">{role.title}</p>
        <StatusBadge status={role.status} pending={role.pending_review} />
      </div>
      <p className="card-company">{role.company_name}</p>
      <RoleMeta role={role} />
      <JobLink url={role.job_url} />
    </div>
  )
}

export function MyPostsPage() {
  useTitle('My posts')
  const [posts, setPosts] = useState<BoardRole[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    api.myPosts().then(
      (page) => setPosts(page.items),
      (e: unknown) => setError(errorMessage(e)),
    )
  }, [])

  async function remove(role: BoardRole) {
    if (!window.confirm(`Delete your post "${role.title}" from the board?`)) return
    setError(null)
    try {
      await api.deletePost(role.id)
      setPosts((list) => (list ?? []).filter((p) => p.id !== role.id))
      setNotice(`Deleted "${role.title}".`)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <section>
      <p>
        <Link to="/board">← Board</Link>
      </p>
      <h1>My posts</h1>
      <FormError message={error} />
      {notice && <p role="status">{notice}</p>}
      {posts === null && !error && <p aria-busy="true">Loading…</p>}
      {posts?.length === 0 && (
        <div className="empty">
          <p>You haven't shared any roles yet.</p>
          <Link to="/board/new">Share a role</Link>
        </div>
      )}
      <ul className="role-list">
        {posts?.map((role) => (
          <li key={role.id}>
            <article className="role-card" aria-label={role.title}>
              <div className="role-head">
                <h2 className="role-title">{role.title}</h2>
                <StatusBadge status={role.status} pending={role.pending_review} />
              </div>
              <p className="card-company">{role.company_name}</p>
              <RoleMeta role={role} />
              {role.status === 'flagged' && (
                <p className="field-error">The checks flagged this ad, so it isn't on the board. See why below.</p>
              )}
              {role.status === 'hidden' && <p className="hint">Reported by several people; a moderator will look at it.</p>}
              <details className="check-details" open={role.status === 'flagged'}>
                <summary>What the checks found</summary>
                <CheckList checks={role.checks} />
              </details>
              <div className="role-actions">
                <JobLink url={role.job_url} />
                <button type="button" className="danger" onClick={() => void remove(role)}>
                  Delete post
                </button>
              </div>
            </article>
          </li>
        ))}
      </ul>
    </section>
  )
}
