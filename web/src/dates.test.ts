import { daysUntil, dueLabel, dueSoon, todayIso } from './dates'

const NOW = new Date(2026, 10, 20, 9, 0) // 20 Nov 2026, local time

describe('dates', () => {
  it('formats today as YYYY-MM-DD', () => {
    expect(todayIso(NOW)).toBe('2026-11-20')
  })

  it('counts calendar days', () => {
    expect(daysUntil('2026-11-20', NOW)).toBe(0)
    expect(daysUntil('2026-11-23', NOW)).toBe(3)
    expect(daysUntil('2026-11-19', NOW)).toBe(-1)
  })

  it('labels deadlines in plain words', () => {
    expect(dueLabel('2026-11-20', NOW)).toBe('Due today')
    expect(dueLabel('2026-11-21', NOW)).toBe('Due tomorrow')
    expect(dueLabel('2026-11-25', NOW)).toBe('Due in 5 days')
    expect(dueLabel('2026-11-18', NOW)).toBe('2 days overdue')
  })

  it('lists open roles due within 7 days, soonest first', () => {
    const apps = [
      { id: 'late', deadline: '2026-11-30', stage: 'saved' },
      { id: 'soon', deadline: '2026-11-22', stage: 'applied' },
      { id: 'overdue', deadline: '2026-11-19', stage: 'saved' },
      { id: 'rejected', deadline: '2026-11-21', stage: 'rejected' },
      { id: 'none', deadline: null, stage: 'saved' },
    ]
    expect(dueSoon(apps, 7, NOW).map((a) => a.id)).toEqual(['overdue', 'soon'])
  })
})
