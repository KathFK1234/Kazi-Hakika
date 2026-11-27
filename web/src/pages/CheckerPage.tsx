import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, type CheckerResult, type CheckInput } from '../api'
import { CheckList } from '../components/Checks'
import { Field, FormError } from '../components/Field'
import { fieldError, formError, toProblem, type Problem } from '../errors'
import { useTitle } from '../useTitle'

const EMPTY: CheckInput = { url: null, text: '', company: '', agency: null }
const TEXT_MAX = 10_000
const FIELDS = ['url', 'company', 'agency'] as const
const orNull = (v: string) => (v.trim() === '' ? null : v)

const VERDICT_TITLE = {
  flagged: 'Likely a scam',
  unverified: 'Not confirmed',
  verified: 'Checks passed',
} as const

export function CheckerPage() {
  useTitle('Is this job real?')
  const [form, setForm] = useState<CheckInput>(EMPTY)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CheckerResult | null>(null)
  const textId = useId()
  const resultRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (result) resultRef.current?.focus()
  }, [result])

  function set<K extends keyof CheckInput>(key: K, value: CheckInput[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    setResult(null)
    try {
      setResult(await api.checkJob(form))
    } catch (e) {
      setProblem(toProblem(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="form-page checker">
      <h1>Is this job real?</h1>
      <p className="lead-small">
        Paste a job ad, its link, or both. We run the same automatic checks for everyone, with no account needed. We
        don't save what you paste.
      </p>
      <form onSubmit={submit} noValidate>
        <Field
          label="Link to the ad"
          name="url"
          type="url"
          inputMode="url"
          placeholder="https://"
          maxLength={2048}
          error={fieldError(problem, 'url')}
          value={form.url ?? ''}
          onChange={(e) => set('url', orNull(e.target.value))}
        />
        <div className="field">
          <label htmlFor={textId}>The ad's text</label>
          <textarea id={textId} rows={8} maxLength={TEXT_MAX} value={form.text} onChange={(e) => set('text', e.target.value)} aria-describedby={`${textId}-hint`} />
          <p className="hint" id={`${textId}-hint`}>
            Include the contact details and anything about payment. Used for this check only, then discarded.
          </p>
        </div>
        <div className="field-row">
          <Field label="Company named in the ad (optional)" name="company" maxLength={200} error={fieldError(problem, 'company')} value={form.company} onChange={(e) => set('company', e.target.value)} />
          <Field label="Recruiting agency, for jobs abroad (optional)" name="agency" maxLength={200} error={fieldError(problem, 'agency')} value={form.agency ?? ''} onChange={(e) => set('agency', orNull(e.target.value))} />
        </div>
        <FormError message={formError(problem, FIELDS)} />
        <button className="primary" disabled={busy}>
          {busy ? 'Checking… (up to 10 seconds)' : 'Check this job'}
        </button>
      </form>

      {result && (
        <section className={`verdict verdict-${result.verdict}`} aria-labelledby="verdict-h">
          <h2 id="verdict-h" tabIndex={-1} ref={resultRef}>
            {VERDICT_TITLE[result.verdict]}
          </h2>
          <p>{result.summary}</p>
          {result.lookups_paused && (
            <p className="hint">You've run many checks this hour, so the website lookups were skipped this time.</p>
          )}
          <CheckList checks={result.checks} />
          <p className="hint">
            These are automatic checks, not a guarantee. Real employers never ask you to pay to apply, train or get a
            medical. See also the <Link to="/board">board</Link> of roles others have shared.
          </p>
        </section>
      )}
    </section>
  )
}
