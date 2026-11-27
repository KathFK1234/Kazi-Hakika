import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, STAGE_LABELS, type PatternGroup, type Patterns } from '../api'
import { FormError } from '../components/Field'
import { errorMessage } from '../errors'
import { useTitle } from '../useTitle'

const SOURCE_LABELS: Record<string, string> = { own: 'Roles you found', board: 'Roles from the board' }

export function PatternsPage() {
  useTitle('Patterns')
  const [data, setData] = useState<Patterns | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.patterns().then(setData, (e: unknown) => setError(errorMessage(e)))
  }, [])
  if (data === null) return error ? <FormError message={error} /> : <p aria-busy="true">Loading…</p>
  const min = data.min_group

  return (
    <div className="dira prose">
      <p>
        <Link to="/dira">← Dira</Link>
      </p>
      <h1>Patterns so far</h1>
      <p className="lead-small">
        Simple counts from your own tracker, nothing more. They describe what has happened so far; they don&apos;t
        predict anything. A group shows once it has {min} applications or more.
      </p>

      <section aria-labelledby="tags-h">
        <h2 id="tags-h">Which kinds of role move forward</h2>
        <p className="hint">
          Of the roles you applied for, how many reached screening or later. Add tags (like backend or ai-infra) to your
          roles to see this by kind of role.
        </p>
        <GroupTable caption="By tag" groups={data.by_tag} label={(n) => n} min={min} />
        <GroupTable caption="By where you found the role" groups={data.by_source} label={(n) => SOURCE_LABELS[n] ?? n} min={min} />
      </section>

      <section aria-labelledby="stops-h">
        <h2 id="stops-h">Where applications stop</h2>
        {data.stops ? (
          <p>
            So far, of {data.stops.ended} roles that ended (rejected or withdrawn), {data.stops.count} ended at{' '}
            <strong>{STAGE_LABELS[data.stops.stage]}</strong>, more than any other stage.
          </p>
        ) : (
          <p className="muted">This shows once {min} or more of your applications have ended.</p>
        )}
      </section>

      <section aria-labelledby="dir-h">
        <h2 id="dir-h">How recent roles fit your direction</h2>
        {data.direction ? (
          <p>
            So far, {data.direction.matching} of your {data.direction.recent} roles from the last 60 days have a tag that
            appears in your latest ideal role
            {data.direction.tags.length > 0 && <> ({data.direction.tags.join(', ')})</>}.
          </p>
        ) : (
          <p className="muted">
            {data.ideal_role
              ? `This shows once you've added ${min} or more roles in the last 60 days.`
              : 'This shows after your first check-in.'}
          </p>
        )}
        <p className="hint">
          A role counts when one of its tags appears word for word in your ideal-role sentence. We never guess from your
          writing.
        </p>
      </section>
    </div>
  )
}

function GroupTable({
  caption,
  groups,
  label,
  min,
}: {
  caption: string
  groups: PatternGroup[]
  label: (name: string) => string
  min: number
}) {
  if (groups.length === 0) {
    return (
      <p className="muted">
        {caption}: nothing yet. A group shows once it has {min} applied roles.
      </p>
    )
  }
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Applied</th>
            <th scope="col">Reached screening or later, so far</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.name}>
              <th scope="row">{label(g.name)}</th>
              <td>{g.total}</td>
              <td>
                {g.reached_screening} ({Math.round((100 * g.reached_screening) / g.total)}%)
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
