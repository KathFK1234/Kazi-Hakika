import type { Check } from './api'

/** "3 warnings, 1 red flag", for a collapsed check list's summary. */
export function checkSummary(checks: Check[]): string {
  const flags = checks.filter((c) => c.result === 'flag').length
  const warns = checks.filter((c) => c.result === 'warn').length
  const parts = []
  if (flags) parts.push(`${flags} red flag${flags === 1 ? '' : 's'}`)
  if (warns) parts.push(`${warns} warning${warns === 1 ? '' : 's'}`)
  return parts.length ? parts.join(', ') : 'no warnings'
}
