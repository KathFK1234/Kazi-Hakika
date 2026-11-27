import { useCallback, useEffect, useId, useState, type ChangeEvent } from 'react'
import { Navigate } from 'react-router'
import { api, type AdminRole, type ModerationQueue, type NeaStatus } from '../api'
import { useAuth } from '../auth-context'
import { CheckList, StatusBadge } from '../components/Checks'
import { FormError } from '../components/Field'
import { JobLink } from '../components/JobLink'
import { errorMessage } from '../errors'
import { useTitle } from '../useTitle'
import { RoleMeta } from './BoardPage'
import { chunkCsv } from '../csv'

type Action = 'approve' | 'hide' | 'restore'

export function AdminPage() {
  useTitle('Moderation')
  const { me } = useAuth()
  const [queue, setQueue] = useState<ModerationQueue | null>(null)
  const [nea, setNea] = useState<NeaStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const fileId = useId()

  const refresh = useCallback(() => {
    api.moderationQueue().then(setQueue, (e: unknown) => setError(errorMessage(e)))
    api.neaStatus().then(setNea, (e: unknown) => setError(errorMessage(e)))
  }, [])

  useEffect(() => {
    if (me?.is_admin) refresh()
  }, [me?.is_admin, refresh])

  if (!me?.is_admin) return <Navigate to="/" replace />

  async function act(role: AdminRole, action: Action) {
    setError(null)
    try {
      await api.moderate(role.id, action)
      setNotice(`${role.title}: ${action === 'approve' ? 'approved' : action === 'hide' ? 'hidden' : 'restored'}.`)
      refresh()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setError(null)
    try {
      const chunks = chunkCsv(await file.text())
      let status: NeaStatus | null = null
      for (const [index, chunk] of chunks.entries()) {
        status = await api.uploadNea(chunk, index === 0)
      }
      setNea(status)
      setNotice(`Loaded the NEA list: ${status?.total ?? 0} agencies.`)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      event.target.value = ''
    }
  }

  return (
    <div className="admin">
      <h1>Moderation</h1>
      <FormError message={error} />
      {notice && <p role="status">{notice}</p>}
      {queue === null && !error && <p aria-busy="true">Loading…</p>}
      {queue && (
        <>
          <QueueSection title="Waiting for review" roles={queue.pending} actions={['approve', 'hide']} onAct={act} />
          <QueueSection title="Hidden after reports" roles={queue.hidden} actions={['restore']} onAct={act} />
          <QueueSection title="Flagged by the checks" roles={queue.flagged} actions={[]} onAct={act} />
        </>
      )}
      <section className="settings-like" aria-labelledby="nea-h">
        <h2 id="nea-h">NEA licensed agencies</h2>
        <p>
          {nea?.total ? `${nea.total} agencies loaded` : 'No list loaded yet'}
          {nea?.synced_at ? `, last on ${new Date(nea.synced_at).toLocaleDateString()}` : ''}. Upload the list from
          neaims.go.ke as a CSV with a Name (or Agency) column and, if available, a status column. It replaces the
          current list.
        </p>
        <div className="field">
          <label htmlFor={fileId}>Upload the CSV</label>
          <input id={fileId} type="file" accept=".csv,text/csv" onChange={(e) => void upload(e)} />
        </div>
      </section>
    </div>
  )
}

const ACTION_LABEL: Record<Action, string> = { approve: 'Approve', hide: 'Hide', restore: 'Restore' }

function QueueSection({
  title,
  roles,
  actions,
  onAct,
}: {
  title: string
  roles: AdminRole[]
  actions: Action[]
  onAct: (role: AdminRole, action: Action) => Promise<void>
}) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="queue">
      <h2 id={id}>
        {title} <span className="count">({roles.length})</span>
      </h2>
      {roles.length === 0 && <p className="muted">Nothing here.</p>}
      <ul className="role-list">
        {roles.map((role) => (
          <li key={role.id}>
            <article className="role-card" aria-label={role.title}>
              <div className="role-head">
                <h3 className="role-title">{role.title}</h3>
                <StatusBadge status={role.status} />
              </div>
              <p className="card-company">
                {role.company_name} · shared by {role.posted_by}
              </p>
              <RoleMeta role={role} />
              {role.reports.length > 0 && (
                <ul className="reports">
                  {role.reports.map((r) => (
                    <li key={r.created_at}>
                      Reported: {r.reason}
                      {r.note ? `: ${r.note}` : ''}
                    </li>
                  ))}
                </ul>
              )}
              <details className="check-details">
                <summary>Checks</summary>
                <CheckList checks={role.checks} />
              </details>
              <div className="role-actions">
                <JobLink url={role.job_url} />
                {actions.map((a) => (
                  <button key={a} type="button" className={a === 'hide' ? 'danger' : ''} onClick={() => void onAct(role, a)}>
                    {ACTION_LABEL[a]}
                  </button>
                ))}
              </div>
            </article>
          </li>
        ))}
      </ul>
    </section>
  )
}
