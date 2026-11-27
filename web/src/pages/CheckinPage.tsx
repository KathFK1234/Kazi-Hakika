import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, CONFIDENCE, type CheckinInput, type CheckinPrompt } from '../api'
import { CONFIDENCE_LABELS } from '../dira'
import { FormError } from '../components/Field'
import { formatDate } from '../dates'
import { errorMessage, fieldError, toProblem, type Problem } from '../errors'
import { useTitle } from '../useTitle'

const PROMPTS = [
  { key: 'excited', label: 'What work excited you since last time?', max: 2000 },
  { key: 'energised', label: 'What gave you energy?', max: 1000 },
  { key: 'drained', label: 'What drained you?', max: 1000 },
  { key: 'changed', label: 'What would you keep, or change, about your direction?', max: 2000 },
] as const

const EMPTY: CheckinInput = { ideal_role: '', excited: null, energised: null, drained: null, changed: null }
const orNull = (v: string) => (v.trim() === '' ? null : v)

export function CheckinPage() {
  useTitle('Career check-in')
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState<CheckinPrompt | null>(null)
  const [form, setForm] = useState<CheckinInput>(EMPTY)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const idealId = useId()
  const idealRef = useRef<HTMLTextAreaElement>(null)
  const idealError = fieldError(problem, 'ideal_role')
  // Like Field: a rejected answer takes focus, so it's seen and read out.
  useEffect(() => {
    if (idealError) idealRef.current?.focus()
  }, [idealError, problem])

  useEffect(() => {
    api.checkinPrompt().then(setPrompt, (e: unknown) => setError(errorMessage(e)))
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await api.saveCheckin(form)
      navigate('/dira', { state: { notice: 'Check-in saved. Thank you for taking the time.' } })
    } catch (e) {
      setProblem(toProblem(e))
      setBusy(false)
    }
  }

  if (prompt === null) return error ? <FormError message={error} /> : <p aria-busy="true">Loading…</p>

  if (prompt.checked_in_today) {
    return (
      <section className="form-page">
        <h1>Career check-in</h1>
        <p>You checked in today already. See it on your <Link to="/dira">Dira page</Link>.</p>
      </section>
    )
  }

  return (
    <section className="form-page dira">
      <p>
        <Link to="/dira">← Dira</Link>
      </p>
      <h1>Career check-in</h1>
      <p className="lead-small">
        A few minutes on where you want your career to go. Only the first question is needed; answer the rest if they
        help. Only you can see this.
      </p>

      {prompt.roles_since.length > 0 && (
        <div className="reminders" aria-labelledby="since-h">
          <h2 id="since-h">
            {prompt.last_checkin_on
              ? `Roles you added or moved since ${formatDate(prompt.last_checkin_on)}`
              : 'Roles in your tracker'}
          </h2>
          <p className="hint">To jog your memory. Nothing to do here.</p>
          <ul>
            {prompt.roles_since.map((r) => (
              <li key={r.id}>{r.role_title}</li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={save} noValidate>
        <div className="field">
          <label htmlFor={idealId}>In a sentence, what role are you aiming for now?</label>
          <textarea
            id={idealId}
            ref={idealRef}
            rows={2}
            maxLength={300}
            required
            aria-invalid={idealError ? true : undefined}
            aria-describedby={`${idealId}-hint${idealError ? ` ${idealId}-error` : ''}`}
            value={form.ideal_role}
            onChange={(e) => setForm((f) => ({ ...f, ideal_role: e.target.value }))}
          />
          {idealError && (
            <p className="field-error" id={`${idealId}-error`}>
              {idealError}
            </p>
          )}
          <p className="hint" id={`${idealId}-hint`}>
            For example: “Backend engineer at a fintech, working on payments.” It&apos;s fine if it changes every time.
          </p>
        </div>

        {PROMPTS.map((p) => (
          <TextPrompt
            key={p.key}
            label={p.label}
            max={p.max}
            value={form[p.key] ?? ''}
            onChange={(v) => setForm((f) => ({ ...f, [p.key]: orNull(v) }))}
          />
        ))}

        <fieldset className="confidence">
          <legend>How confident do you feel right now about… (optional)</legend>
          {CONFIDENCE.map((key) => (
            <Rating
              key={key}
              question={CONFIDENCE_LABELS[key].question}
              value={form[`confidence_${key}`] ?? null}
              onChange={(v) => setForm((f) => ({ ...f, [`confidence_${key}`]: v }))}
            />
          ))}
        </fieldset>

        <FormError message={problem && problem.field !== 'ideal_role' ? problem.message : null} />
        <div className="form-actions">
          <button className="primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save check-in'}
          </button>
        </div>
      </form>
      <p className="hint">
        Reflecting on your career can bring up hard feelings. If you&apos;d like someone to talk to,{' '}
        <Link to="/support">see support</Link>.
      </p>
    </section>
  )
}

function TextPrompt({
  label,
  max,
  value,
  onChange,
}: {
  label: string
  max: number
  value: string
  onChange: (v: string) => void
}) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} rows={3} maxLength={max} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

const SCALE = ['Not at all', 'A little', 'Somewhat', 'Quite', 'Very'] as const

function Rating({
  question,
  value,
  onChange,
}: {
  question: string
  value: number | null
  onChange: (v: number | null) => void
}) {
  const name = useId()
  return (
    <fieldset className="rating">
      <legend>{question}</legend>
      <div className="rating-options">
        {SCALE.map((word, i) => (
          <label key={word} className="rating-option">
            <input type="radio" name={name} value={i + 1} checked={value === i + 1} onChange={() => onChange(i + 1)} />
            {word}
          </label>
        ))}
        {value !== null && (
          <button type="button" className="link" onClick={() => onChange(null)}>
            Clear
          </button>
        )}
      </div>
    </fieldset>
  )
}
