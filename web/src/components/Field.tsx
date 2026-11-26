import { useEffect, useId, useRef, type InputHTMLAttributes, type ReactNode } from 'react'

type Props = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }

export function Field({ label, hint, error, ...input }: Props) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const ref = useRef<HTMLInputElement>(null)
  // A new error moves focus here, so it's seen on a phone and read out
  // (the message is part of the field's description).
  useEffect(() => {
    if (error) ref.current?.focus()
  }, [error])
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        ref={ref}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={[errorId, hintId].filter(Boolean).join(' ') || undefined}
        {...input}
      />
      {error && (
        <p className="field-error" id={errorId}>
          {error}
        </p>
      )}
      {hint && (
        <p className="hint" id={hintId}>
          {hint}
        </p>
      )}
    </div>
  )
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  )
}
