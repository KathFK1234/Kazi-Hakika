import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'
import { api, type Checkin, type DiraOverview, type Entry, type EntryKind } from '../api'
import { ConfidenceChart } from '../components/ConfidenceChart'
import { FormError } from '../components/Field'
import { formatDate } from '../dates'
import { errorMessage } from '../errors'
import { useTitle } from '../useTitle'

const FIELDS: { key: keyof Checkin; label: string }[] = [
  { key: 'ideal_role', label: 'Aiming for' },
  { key: 'excited', label: 'Excited by' },
  { key: 'energised', label: 'Gave energy' },
  { key: 'drained', label: 'Drained by' },
  { key: 'changed', label: 'Keep or change' },
]

export function DiraPage() {
  useTitle('Dira')
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice ?? null
  const [data, setData] = useState<DiraOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.dira().then(setData, (e: unknown) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  async function remove(c: Checkin) {
    if (!window.confirm(`Delete your check-in from ${formatDate(c.on_date)}? This can't be undone.`)) return
    try {
      await api.deleteCheckin(c.id)
      load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (data === null) return error ? <FormError message={error} /> : <p aria-busy="true">Loading…</p>
  const { settings, checkins, week } = data

  return (
    <div className="dira">
      <div className="toolbar">
        <h1>
          Dira <span className="muted">· your career compass</span>
        </h1>
        <div className="toolbar-actions">
          <Link className={`button${data.due ? ' primary' : ''}`} to="/dira/checkin">
            Check in
          </Link>
          <Link className="button" to="/dira/patterns">
            Patterns
          </Link>
        </div>
      </div>
      {notice && <p role="status">{notice}</p>}
      <FormError message={error} />

      <p className="lead-small">
        {settings.checkin_interval_weeks
          ? data.due
            ? 'Your check-in is ready whenever you are.'
            : `Next check-in from ${formatDate(settings.next_checkin_on ?? '')}, every ${settings.checkin_interval_weeks} weeks.`
          : 'Check in whenever you like. To get a reminder every 4, 6 or 8 weeks, turn it on in '}
        {!settings.checkin_interval_weeks && <Link to="/settings">Settings</Link>}
        {!settings.checkin_interval_weeks && '.'}
      </p>
      {week.target !== null && (
        <p>
          This week so far: {week.applied_this_week} of your {week.target} well-fit applications.
        </p>
      )}

      <section aria-labelledby="timeline-h">
        <h2 id="timeline-h">Your direction over time</h2>
        {checkins.length === 0 ? (
          <div className="empty">
            <p>No check-ins yet. The first one takes a few minutes.</p>
            <Link to="/dira/checkin">Start your first check-in</Link>
          </div>
        ) : (
          <ol className="timeline" aria-labelledby="timeline-h">
            {checkins.map((c) => (
              <li key={c.id}>
                <article aria-label={`Check-in, ${formatDate(c.on_date)}`}>
                  <p className="timeline-date">{formatDate(c.on_date)}</p>
                  <p className="timeline-ideal">{c.ideal_role}</p>
                  {c.changed && <p>{c.changed}</p>}
                  <details>
                    <summary>All answers</summary>
                    <dl className="answers">
                      {FIELDS.slice(1).map((f) =>
                        c[f.key] ? (
                          <div key={f.key}>
                            <dt>{f.label}</dt>
                            <dd>{c[f.key]}</dd>
                          </div>
                        ) : null,
                      )}
                    </dl>
                    <button type="button" className="link danger-link" onClick={() => void remove(c)}>
                      Delete this check-in
                    </button>
                  </details>
                </article>
              </li>
            ))}
          </ol>
        )}
      </section>

      {checkins.length >= 2 && <Compare checkins={checkins} />}
      <ConfidenceChart checkins={checkins} />
      <Entries />
      <p className="hint">
        Dira is for reflection, not advice or therapy. If things feel heavy, <Link to="/support">see support</Link>.
      </p>
    </div>
  )
}

function Compare({ checkins }: { checkins: Checkin[] }) {
  const olderId = useId()
  const newerId = useId()
  const [older, setOlder] = useState(checkins[checkins.length - 1].id)
  const [newer, setNewer] = useState(checkins[0].id)
  const a = checkins.find((c) => c.id === older)
  const b = checkins.find((c) => c.id === newer)
  return (
    <section aria-labelledby="compare-h">
      <h2 id="compare-h">Compare two check-ins</h2>
      <div className="field-row">
        {[
          { id: olderId, label: 'From', value: older, set: setOlder },
          { id: newerId, label: 'To', value: newer, set: setNewer },
        ].map((s) => (
          <div className="field" key={s.id}>
            <label htmlFor={s.id}>{s.label}</label>
            <select id={s.id} value={s.value} onChange={(e) => s.set(e.target.value)}>
              {checkins.map((c) => (
                <option key={c.id} value={c.id}>
                  {formatDate(c.on_date)}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      {a && b && (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Two check-ins side by side">
          <table className="data-table compare">
            <thead>
              <tr>
                <th scope="col">
                  <span className="visually-hidden">Question</span>
                </th>
                <th scope="col">{formatDate(a.on_date)}</th>
                <th scope="col">{formatDate(b.on_date)}</th>
              </tr>
            </thead>
            <tbody>
              {FIELDS.map((f) => (
                <tr key={f.key}>
                  <th scope="row">{f.label}</th>
                  <td>{a[f.key] ?? '–'}</td>
                  <td>{b[f.key] ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const KIND_LABELS: Record<EntryKind, string> = { win: 'Win', learning: 'Learning', goal: 'Goal' }

function Entries() {
  const kindId = useId()
  const textId = useId()
  const [entries, setEntries] = useState<Entry[] | null>(null)
  const [kind, setKind] = useState<EntryKind>('win')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.entries(new URLSearchParams()).then(setEntries, (e: unknown) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  async function add(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    setError(null)
    try {
      await api.addEntry(kind, text.trim())
      setText('')
      load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function act(entry: Entry, action: 'done' | 'undo' | 'delete') {
    setError(null)
    try {
      if (action === 'delete') await api.deleteEntry(entry.id)
      else await api.updateEntry(entry.id, { done: action === 'done' })
      load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <section aria-labelledby="entries-h">
      <h2 id="entries-h">Wins, learnings and goals</h2>
      <form className="entry-form" onSubmit={add}>
        <div className="field">
          <label htmlFor={kindId}>Kind</label>
          <select id={kindId} value={kind} onChange={(e) => setKind(e.target.value as EntryKind)}>
            <option value="win">Win</option>
            <option value="learning">Learning</option>
            <option value="goal">Goal</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={textId}>What happened, or what you want next</label>
          <input id={textId} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <button className="primary">Add</button>
      </form>
      <FormError message={error} />
      {entries?.length === 0 && <p className="muted">Nothing yet. Small wins count.</p>}
      <ul className="entries">
        {entries?.map((e) => (
          <li key={e.id} className={e.done_at ? 'done' : undefined}>
            <span className={`badge kind-${e.kind}`}>{KIND_LABELS[e.kind]}</span> {e.text}{' '}
            <span className="hint">
              {formatDate(e.happened_on)}
              {e.application_id && (
                <>
                  {' · '}
                  <Link to={`/applications/${e.application_id}`}>about a role</Link>
                </>
              )}
              {e.done_at && ' · done'}
            </span>
            <span className="entry-actions">
              {e.kind === 'goal' && (
                <button type="button" className="link" onClick={() => void act(e, e.done_at ? 'undo' : 'done')}>
                  {e.done_at ? 'Not done yet' : 'Mark done'}
                </button>
              )}
              <button type="button" className="link" onClick={() => void act(e, 'delete')} aria-label={`Delete: ${e.text}`}>
                Delete
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
