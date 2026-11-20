import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, STAGE_LABELS, STAGES, type ApplicationDetail, type ApplicationInput, type Stage } from '../api'
import { Field, FormError } from '../components/Field'
import { errorMessage } from '../errors'

const EMPTY: ApplicationInput = {
  role_title: '',
  company_name: '',
  job_url: null,
  stage: 'saved',
  deadline: null,
  applied_on: null,
  salary_note: null,
  notes: '',
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
  }
}

const orNull = (v: string) => (v.trim() === '' ? null : v)

export function ApplicationPage() {
  const { id } = useParams()
  const isNew = id === undefined
  const navigate = useNavigate()
  const [form, setForm] = useState<ApplicationInput>(EMPTY)
  const [detail, setDetail] = useState<ApplicationDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(isNew)
  const stageId = useId()
  const notesId = useId()

  useEffect(() => {
    if (isNew) return
    api
      .getApplication(id)
      .then((a) => {
        setDetail(a)
        setForm(toInput(a))
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
    try {
      if (isNew) await api.createApplication(form)
      else await api.updateApplication(id, form)
      navigate('/')
    } catch (e) {
      setError(errorMessage(e))
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
      <form onSubmit={save} noValidate>
        <Field label="Role title" required maxLength={200} value={form.role_title} onChange={(e) => set('role_title', e.target.value)} />
        <Field label="Company" required maxLength={200} value={form.company_name} onChange={(e) => set('company_name', e.target.value)} />
        <Field
          label="Job link"
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
          <Field label="Deadline" type="date" value={form.deadline ?? ''} onChange={(e) => set('deadline', orNull(e.target.value))} />
          <Field label="Applied on" type="date" value={form.applied_on ?? ''} onChange={(e) => set('applied_on', orNull(e.target.value))} />
        </div>
        <Field
          label="Salary note"
          maxLength={200}
          placeholder="e.g. KSh 150k–180k gross, from the ad"
          value={form.salary_note ?? ''}
          onChange={(e) => set('salary_note', orNull(e.target.value))}
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
        <FormError message={error} />
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
