import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { api } from '../api'
import { errorMessage } from '../errors'
import { FormError } from './Field'

/** Offered once after a role moves to Rejected. Optional: Skip is as easy as Save. */
export function LearningPrompt({
  applicationId,
  roleTitle,
  onDone,
  autoFocus = true,
}: {
  applicationId: string
  roleTitle: string
  onDone: (saved: boolean) => void
  /** False where focus should stay put (the tracker keeps it on the moved card). */
  autoFocus?: boolean
}) {
  const id = useId()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return onDone(false)
    setBusy(true)
    try {
      await api.addEntry('learning', text.trim(), applicationId)
      onDone(true)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <form className="learning-prompt" onSubmit={save} aria-label="A learning from this role">
      <label htmlFor={id}>
        {roleTitle} moved to Rejected. One thing you&apos;d keep or change next time? (optional)
      </label>
      <textarea id={id} ref={ref} rows={2} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
      <p className="hint">Saved to your Dira learnings, only for you.</p>
      <FormError message={error} />
      <div className="form-actions">
        <button className="primary" disabled={busy}>
          Save learning
        </button>
        <button type="button" onClick={() => onDone(false)}>
          Skip
        </button>
      </div>
    </form>
  )
}
