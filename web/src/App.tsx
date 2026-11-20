import { useEffect, useState } from 'react'
import { getJson, type Meta } from './api'

const FALLBACK: Meta = { name: 'Kazi Hakika', tagline: 'verified roles, tracked your way.' }

export default function App() {
  const [meta, setMeta] = useState<Meta>(FALLBACK)

  useEffect(() => {
    let active = true
    getJson<Meta>('/api/meta')
      .then((m) => {
        if (active) setMeta(m)
      })
      .catch(() => {
        // Keep the fallback name; the page still works.
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="shell">
      <header className="site-header">
        <p className="brand">{meta.name}</p>
        <p className="tagline">{meta.tagline}</p>
      </header>
      <main>
        <p>Your private job-application tracker is on its way.</p>
      </main>
    </div>
  )
}
