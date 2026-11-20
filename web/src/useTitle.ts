import { useEffect } from 'react'

const APP = 'Kazi Hakika'

/** "Page · Kazi Hakika", so tabs and screen readers say where you are. */
export function useTitle(page: string) {
  useEffect(() => {
    document.title = page ? `${page} · ${APP}` : APP
  }, [page])
}
