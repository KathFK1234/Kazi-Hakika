import type { BoardStatus, Check, CheckResult } from '../api'

// Every result is shown as a word and a symbol, never by colour alone.
const RESULT: Record<CheckResult, { word: string; symbol: string }> = {
  pass: { word: 'Pass', symbol: '✓' },
  warn: { word: 'Warning', symbol: '!' },
  flag: { word: 'Red flag', symbol: '✕' },
  unknown: { word: "Couldn't check", symbol: '?' },
  skip: { word: 'Not checked', symbol: '–' },
}

// Red flags first, then warnings, so the important lines come first.
const ORDER: CheckResult[] = ['flag', 'warn', 'unknown', 'skip', 'pass']

export function CheckList({ checks }: { checks: Check[] }) {
  const sorted = [...checks].sort((a, b) => ORDER.indexOf(a.result) - ORDER.indexOf(b.result))
  return (
    <ul className="checks">
      {sorted.map((c) => (
        <li key={c.id} className={`check-item check-${c.result}`}>
          <span className="check-result">
            <span aria-hidden="true">{RESULT[c.result].symbol}</span> {RESULT[c.result].word}
          </span>
          <span className="check-text">
            <strong>{c.label}.</strong> {c.detail}
          </span>
        </li>
      ))}
    </ul>
  )
}

const STATUS: Record<BoardStatus, { label: string; tone: string }> = {
  verified: { label: 'Verified', tone: 'ok' },
  unverified: { label: 'Unverified', tone: 'warn' },
  flagged: { label: 'Flagged: likely scam', tone: 'danger' },
  hidden: { label: 'Hidden', tone: 'warn' },
  archived: { label: 'Archived', tone: 'muted' },
}

export function StatusBadge({ status, pending = false }: { status: BoardStatus; pending?: boolean }) {
  if (pending) return <span className="badge warn">Waiting for review</span>
  const s = STATUS[status]
  return <span className={`badge ${s.tone}`}>{s.label}</span>
}
