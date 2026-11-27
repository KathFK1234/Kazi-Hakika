import { useTitle } from '../useTitle'
import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, STAGE_LABELS, STAGES, type ApplicationDetail, type ApplicationInput, type Entry, type Stage } from '../api'
import { Field, FormError } from '../components/Field'
import { JobLink } from '../components/JobLink'
import { LearningPrompt } from '../components/LearningPrompt'
import { formatDate } from '../dates'
import { useFeatures } from '../features'
import { parseTags } from '../tags'
import { errorMessage, fieldError, formError, toProblem, type Problem } from '../errors'

const EMPTY: ApplicationInput = {
  role_title: '',
  company_name: '',
  job_url: null,
  stage: 'saved',
  deadline: null,
  applied_on: null,
  salary_note: null,
  notes: '',
  tags: [],
}

const NOTES_MAX = 5000

function toInput(a: ApplicationDetail): ApplicationInput {
  return {
    role_title: a.role_title,
    company_name: a.company_name,
    job_url: a.job_url,
    stage: a.stage,
    deadline: a.deadline,
    applied_on: a.applied_on,
    salary_note: a.salary_note,
    notes: a.notes,
    tags: a.tags,
  }
}

const orNull = (v: string) => (v.trim() === '' ? null : v)

// Fields that show their own save errors; others go in the form-level alert.
const FIELD_NAMES = ['role_title', 'company_name', 'job_url', 'deadline', 'applied_on', 'salary_note', 'tags'] as const

export function ApplicationPage() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()
  const [form, setForm] = useState<ApplicationInput>(EMPTY)
  const [detail, setDetail] = useState<ApplicationDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Save errors, shown under the field they're about when there is one.
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(isNew)
  const [tagText, setTagText] = useState('')
  // Set after a save that moved the role to Rejected (Dira on): offer one prompt.
  const [rejected, setRejected] = useState<{ id: string; title: string } | null>(null)
  const { dira } = useFeatures()
  useTitle(isNew ? 'Add a role' : 'Edit role')
  const stageId = useId()
  const notesId = useId()

  useEffect(() => {
    if (isNew) return
    api
      .getApplication(id)
      .then((a) => {
        setDetail(a)
        setForm(toInput(a))
        setTagText(a.tags.join(', '))
      })
      .catch((e: unknown) => setError(errorMessage(e)))
      .finally(() => setLoaded(true))
  }, [id, isNew])

  function set<K extends keyof ApplicationInput>(key: K, value: ApplicationInput[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setProblem(null)
    try {
      const input = { ...form, tags: parseTags(tagText) }
      const saved = isNew ? await api.createApplication(input) : await api.updateApplication(id, input)
      const newlyRejected = saved.stage === 'rejected' && (isNew || detail?.stage !== 'rejected')
      if (dira && newlyRejected) {
        setRejected({ id: saved.id, title: saved.role_title })
        return
      }
      navigate('/')
    } catch (e) {
      setProblem(toProblem(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (isNew || !window.confirm('Delete this application and its history? This cannot be undone.')) return
    try {
      await api.deleteApplication(id)
      navigate('/')
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (rejected) {
    return (
      <section className="form-page">
        <h1>Saved</h1>
        <LearningPrompt applicationId={rejected.id} roleTitle={rejected.title} onDone={() => navigate('/')} />
      </section>
    )
  }

  if (!loaded) return <p aria-busy="true">Loading…</p>
  if (!isNew && !detail) {
    return (
      <section>
        <FormError message={error ?? 'Application not found.'} />
        <Link to="/">Back to my applications</Link>
      </section>
    )
  }

  return (
    <section className="form-page">
      <p>
        <Link to="/">← My applications</Link>
      </p>
      <h1>{isNew ? 'Add a role' : 'Edit role'}</h1>
      {detail && <JobLink url={detail.job_url} />}
      <form onSubmit={save} noValidate>
        <Field label="Role title" name="role_title" error={fieldError(problem, 'role_title')} required maxLength={200} value={form.role_title} onChange={(e) => set('role_title', e.target.value)} />
        <Field label="Company" name="company_name" error={fieldError(problem, 'company_name')} required maxLength={200} value={form.company_name} onChange={(e) => set('company_name', e.target.value)} />
        <Field
          label="Job link"
          name="job_url"
          error={fieldError(problem, 'job_url')}
          type="url"
          inputMode="url"
          placeholder="https://"
          maxLength={2048}
          value={form.job_url ?? ''}
          onChange={(e) => set('job_url', orNull(e.target.value))}
        />
        <div className="field">
          <label htmlFor={stageId}>Stage</label>
          <select id={stageId} value={form.stage} onChange={(e) => set('stage', e.target.value as Stage)}>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="field-row">
          <Field label="Deadline" name="deadline" error={fieldError(problem, 'deadline')} type="date" value={form.deadline ?? ''} onChange={(e) => set('deadline', orNull(e.target.value))} />
          <Field label="Applied on" name="applied_on" error={fieldError(problem, 'applied_on')} type="date" value={form.applied_on ?? ''} onChange={(e) => set('applied_on', orNull(e.target.value))} />
        </div>
        <Field
          label="Salary note"
          name="salary_note"
          error={fieldError(problem, 'salary_note')}
          maxLength={200}
          placeholder="e.g. KSh 150k–180k gross, from the ad"
          value={form.salary_note ?? ''}
          onChange={(e) => set('salary_note', orNull(e.target.value))}
        />
        <Field
          label="Tags (optional)"
          name="tags"
          error={fieldError(problem, 'tags')}
          placeholder="e.g. backend, ai-infra"
          hint="Up to 5, separated by commas. They group your roles in Dira patterns."
          maxLength={200}
          value={tagText}
          onChange={(e) => setTagText(e.target.value)}
        />
        <div className="field">
          <label htmlFor={notesId}>Notes</label>
          <textarea
            id={notesId}
            rows={6}
            maxLength={NOTES_MAX}
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            aria-describedby={`${notesId}-count`}
          />
          <p className="hint" id={`${notesId}-count`}>
            {form.notes.length.toLocaleString()} / {NOTES_MAX.toLocaleString()} characters. Don't paste your CV here; keep it to notes about this role.
          </p>
        </div>
        <FormError message={error ?? formError(problem, FIELD_NAMES)} />
        <div className="form-actions">
          <button className="primary" disabled={busy}>
            {busy ? 'Saving…' : isNew ? 'Add role' : 'Save changes'}
          </button>
          {!isNew && (
            <button type="button" className="danger" onClick={remove}>
              Delete
            </button>
          )}
        </div>
      </form>
      {dira && detail && <RoleEntries applicationId={detail.id} />}
      {detail && detail.events.length > 0 && (
        <section className="history" aria-labelledby="history-heading">
          <h2 id="history-heading">Stage history</h2>
          <ol>
            {detail.events.map((e) => (
              <li key={`${e.at}-${e.to_stage}`}>
                {new Date(e.at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}: {e.from_stage ? `${STAGE_LABELS[e.from_stage]} → ` : 'Added as '}
                {STAGE_LABELS[e.to_stage]}
              </li>
            ))}
          </ol>
        </section>
      )}
    </section>
  )
}

function RoleEntries({ applicationId }: { applicationId: string }) {
  const id = useId()
  const [entries, setEntries] = useState<Entry[] | null>(null)
  const [kind, setKind] = useState<'learning' | 'win'>('learning')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.entries(new URLSearchParams({ application_id: applicationId })).then(setEntries, (e: unknown) => setError(errorMessage(e)))
  }, [applicationId])

  async function add(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    try {
      const entry = await api.addEntry(kind, text.trim(), applicationId)
      setEntries((list) => [entry, ...(list ?? [])])
      setText('')
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <section className="history" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>Learnings and wins from this role</h2>
      {entries && entries.length > 0 && (
        <ul className="entries">
          {entries.map((e) => (
            <li key={e.id}>
              <span className={`badge kind-${e.kind}`}>{e.kind === 'win' ? 'Win' : e.kind === 'goal' ? 'Goal' : 'Learning'}</span>{' '}
              {e.text} <span className="hint">{formatDate(e.happened_on)}</span>
            </li>
          ))}
        </ul>
      )}
      <form className="entry-form" onSubmit={add}>
        <div className="field">
          <label htmlFor={`${id}-kind`}>Kind</label>
          <select id={`${id}-kind`} value={kind} onChange={(e) => setKind(e.target.value as 'learning' | 'win')}>
            <option value="learning">Learning</option>
            <option value="win">Win</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-text`}>Note it down</label>
          <input id={`${id}-text`} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <button>Add</button>
      </form>
      <FormError message={error} />
    </section>
  )
}
