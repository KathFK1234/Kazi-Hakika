/** Calendar dates as YYYY-MM-DD in the user's own time zone. */
export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function daysUntil(iso: string, now: Date = new Date()): number {
  const [y, m, d] = iso.split('-').map(Number)
  const target = Date.UTC(y, m - 1, d)
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((target - today) / 86_400_000)
}

export function dueLabel(iso: string, now: Date = new Date()): string {
  const days = daysUntil(iso, now)
  if (days < -1) return `${-days} days overdue`
  if (days === -1) return 'Overdue by a day'
  if (days === 0) return 'Due today'
  if (days === 1) return 'Due tomorrow'
  return `Due in ${days} days`
}

export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const ACTIVE = new Set(['saved', 'applied', 'screening', 'interview', 'offer'])

/** Open roles with a deadline within `days` (overdue included), soonest first. */
export function dueSoon<T extends { deadline: string | null; stage: string }>(
  apps: T[],
  days = 7,
  now: Date = new Date(),
): T[] {
  return apps
    .filter((a) => a.deadline !== null && ACTIVE.has(a.stage) && daysUntil(a.deadline, now) <= days)
    .sort((a, b) => (a.deadline ?? '').localeCompare(b.deadline ?? ''))
}
