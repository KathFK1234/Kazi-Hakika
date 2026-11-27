import { useId, useState } from 'react'
import { CONFIDENCE, type Checkin } from '../api'
import { formatDate } from '../dates'
import { CONFIDENCE_LABELS } from '../dira'

// Small multiples: one line per measure, all on the same 1-5 scale. Four
// lines on one plot would sit on top of each other.
const W = 260
const H = 96
const PAD = { left: 22, right: 10, top: 10, bottom: 18 }

/** Confidence over time; shown only when 2+ check-ins have ratings. */
export function ConfidenceChart({ checkins }: { checkins: Checkin[] }) {
  const tableId = useId()
  const [asTable, setAsTable] = useState(false)
  const rated = [...checkins]
    .filter((c) => CONFIDENCE.some((k) => c[`confidence_${k}`] != null))
    .sort((a, b) => a.on_date.localeCompare(b.on_date))
  if (rated.length < 2) return null

  return (
    <section className="confidence-chart" aria-labelledby={`${tableId}-h`}>
      <h2 id={`${tableId}-h`}>How confident you felt, over time</h2>
      <p className="hint">1 is “not at all”, 5 is “very”. From your own answers, nothing else.</p>
      <button type="button" className="link" aria-expanded={asTable} aria-controls={tableId} onClick={() => setAsTable((v) => !v)}>
        {asTable ? 'Show as charts' : 'Show as a table'}
      </button>
      {asTable ? (
        <table id={tableId} className="data-table">
          <thead>
            <tr>
              <th scope="col">Check-in</th>
              {CONFIDENCE.map((k) => (
                <th key={k} scope="col">
                  {CONFIDENCE_LABELS[k].label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rated.map((c) => (
              <tr key={c.id}>
                <th scope="row">{formatDate(c.on_date)}</th>
                {CONFIDENCE.map((k) => (
                  <td key={k}>{c[`confidence_${k}`] ?? '–'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div id={tableId} className="multiples">
          {CONFIDENCE.map((k) => (
            <Spark key={k} title={CONFIDENCE_LABELS[k].label} points={rated.map((c) => ({ date: c.on_date, value: c[`confidence_${k}`] ?? null }))} />
          ))}
        </div>
      )}
    </section>
  )
}

function Spark({ title, points }: { title: string; points: { date: string; value: number | null }[] }) {
  const n = points.length
  const x = (i: number) => PAD.left + (n === 1 ? 0 : (i * (W - PAD.left - PAD.right)) / (n - 1))
  const y = (v: number) => PAD.top + ((5 - v) * (H - PAD.top - PAD.bottom)) / 4
  const known = points.map((p, i) => ({ ...p, i })).filter((p): p is { date: string; value: number; i: number } => p.value !== null)
  const path = known.map((p, j) => `${j ? 'L' : 'M'}${x(p.i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  const last = known[known.length - 1]
  const summary = known.length
    ? `${title}: ${known.map((p) => `${formatDate(p.date)} ${p.value}`).join(', ')}.`
    : `${title}: no answers yet.`
  return (
    <figure className="spark">
      <figcaption>
        {title}
        {last && <span className="spark-last"> · latest {last.value} of 5</span>}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
        {[1, 3, 5].map((v) => (
          <g key={v}>
            <line className="spark-grid" x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
            <text className="spark-axis" x={PAD.left - 6} y={y(v) + 3} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {known.length > 1 && <path className="spark-line" d={path} />}
        {known.map((p) => (
          <circle key={p.date} className="spark-dot" cx={x(p.i)} cy={y(p.value)} r={4}>
            <title>{`${formatDate(p.date)}: ${p.value} of 5`}</title>
          </circle>
        ))}
        <text className="spark-axis" x={PAD.left} y={H - 4}>
          {formatDate(points[0].date)}
        </text>
        <text className="spark-axis" x={W - PAD.right} y={H - 4} textAnchor="end">
          {formatDate(points[n - 1].date)}
        </text>
      </svg>
    </figure>
  )
}
