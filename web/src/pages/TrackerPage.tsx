import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react'
import { Link } from 'react-router'
import { api, listAll, STAGE_LABELS, STAGES, type Application, type Stage } from '../api'
import { FormError } from '../components/Field'
import { JobLink } from '../components/JobLink'
import { errorMessage } from '../errors'
import { daysUntil, dueLabel, dueSoon, formatDate } from '../dates'

type View = 'board' | 'list'
const VIEW_KEY = 'kazi.view'

function loadView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'board'
  } catch {
    return 'board'
  }
}

function saveView(view: View) {
  try {
    localStorage.setItem(VIEW_KEY, view)
  } catch {
    // private mode: the choice just isn't remembered
  }
}

export function TrackerPage() {
  const [apps, setApps] = useState<Application[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>(loadView)

  useEffect(() => {
    let active = true
    listAll(new URLSearchParams({ sort: 'deadline' })).then(
      (items) => {
        if (active) setApps(items)
      },
      (e: unknown) => {
        if (active) setError(errorMessage(e))
      },
    )
    return () => {
      active = false
    }
  }, [])

  const moveTo = useCallback(async (id: string, stage: Stage, from: Stage) => {
    const setStage = (target: Stage) =>
      setApps((list) => list?.map((a) => (a.id === id ? { ...a, stage: target } : a)) ?? null)
    setStage(stage)
    try {
      const updated = await api.updateApplication(id, { stage })
      setApps((list) => list?.map((a) => (a.id === id ? updated : a)) ?? null)
    } catch (e) {
      // Put back only this card; other moves made meanwhile stay.
      setStage(from)
      setError(errorMessage(e))
    }
  }, [])

  function choose(next: View) {
    setView(next)
    saveView(next)
  }

  if (apps === null) {
    return error ? <FormError message={error} /> : <p aria-busy="true">Loading your tracker…</p>
  }

  return (
    <div className="tracker">
      <div className="toolbar">
        <h1>My applications</h1>
        <div className="toolbar-actions">
          <div className="segmented" role="group" aria-label="View">
            <button aria-pressed={view === 'board'} onClick={() => choose('board')}>
              Board
            </button>
            <button aria-pressed={view === 'list'} onClick={() => choose('list')}>
              List
            </button>
          </div>
          <Link className="button primary" to="/applications/new">
            + Add role
          </Link>
        </div>
      </div>
      <FormError message={error} />
      <DuePanel apps={apps} />
      {apps.length === 0 ? (
        <div className="empty">
          <p>No roles yet. Add the first job you're interested in, with its deadline, and we'll remind you before it closes.</p>
          <Link className="button primary" to="/applications/new">
            Add your first role
          </Link>
        </div>
      ) : view === 'board' ? (
        <Board apps={apps} onMove={moveTo} />
      ) : (
        <ListView apps={apps} />
      )}
    </div>
  )
}

function DuePanel({ apps }: { apps: Application[] }) {
  const due = useMemo(() => dueSoon(apps), [apps])
  return (
    <section className="due-panel" aria-labelledby="due-heading">
      <h2 id="due-heading">Due in the next 7 days</h2>
      {due.length === 0 ? (
        <p className="muted">Nothing due this week.</p>
      ) : (
        <ul>
          {due.map((a) => (
            <li key={a.id} className={daysUntil(a.deadline ?? '') < 0 ? 'overdue' : undefined}>
              <Link to={`/applications/${a.id}`}>
                {a.role_title} · {a.company_name}
              </Link>{' '}
              <span className="due">{dueLabel(a.deadline ?? '')}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Board({
  apps,
  onMove,
}: {
  apps: Application[]
  onMove: (id: string, stage: Stage, from: Stage) => void
}) {
  const [over, setOver] = useState<Stage | null>(null)
  const byStage = useMemo(() => {
    const groups = Object.fromEntries(STAGES.map((s) => [s, [] as Application[]])) as Record<Stage, Application[]>
    for (const a of apps) groups[a.stage].push(a)
    return groups
  }, [apps])

  function drop(stage: Stage, event: DragEvent) {
    event.preventDefault()
    setOver(null)
    const id = event.dataTransfer.getData('text/plain')
    const app = apps.find((a) => a.id === id)
    if (app && app.stage !== stage) onMove(id, stage, app.stage)
  }

  return (
    <div className="board" aria-label="Applications by stage">
      {STAGES.map((stage) => (
        <section
          key={stage}
          className={`column${over === stage ? ' drop-target' : ''}`}
          aria-labelledby={`col-${stage}`}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(stage)
          }}
          onDragLeave={() => setOver((s) => (s === stage ? null : s))}
          onDrop={(e) => drop(stage, e)}
        >
          <h2 id={`col-${stage}`}>
            {STAGE_LABELS[stage]} <span className="count">{byStage[stage].length}</span>
          </h2>
          <ul>
            {byStage[stage].map((a) => (
              <li
                key={a.id}
                className="card"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('text/plain', a.id)
                  e.dataTransfer.effectAllowed = 'move'
                }}
              >
                <Link to={`/applications/${a.id}`} className="card-title">
                  {a.role_title}
                </Link>
                <span className="card-company">{a.company_name}</span>
                {a.deadline && <span className="due">{dueLabel(a.deadline)}</span>}
                <JobLink url={a.job_url} />
                <label className="move">
                  <span className="visually-hidden">Move {a.role_title} to</span>
                  <select value={a.stage} onChange={(e) => onMove(a.id, e.target.value as Stage, a.stage)}>
                    {STAGES.map((s) => (
                      <option key={s} value={s}>
                        {STAGE_LABELS[s]}
                      </option>
                    ))}
                  </select>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function ListView({ apps }: { apps: Application[] }) {
  return (
    <ul className="list-view" aria-label="Applications sorted by deadline">
      {apps.map((a) => (
        <li key={a.id} className="row">
          <Link to={`/applications/${a.id}`} className="card-title">
            {a.role_title}
          </Link>
          <span className="card-company">{a.company_name}</span>
          <span className={`stage stage-${a.stage}`}>{STAGE_LABELS[a.stage]}</span>
          <span className="due">{a.deadline ? `${formatDate(a.deadline)} · ${dueLabel(a.deadline)}` : 'No deadline'}</span>
          <JobLink url={a.job_url} />
        </li>
      ))}
    </ul>
  )
}
