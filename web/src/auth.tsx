import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, setCsrfToken, type Me } from './api'
import { AuthContext } from './auth-context'

async function fetchMe(): Promise<Me | null> {
  try {
    const current = await api.me()
    setCsrfToken(current.csrf_token)
    return current
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) console.error(error)
    setCsrfToken('')
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const current = await fetchMe()
    setMe(current)
    setLoading(false)
    return current
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setCsrfToken('')
      setMe(null)
    }
  }, [])

  useEffect(() => {
    let active = true
    fetchMe().then((current) => {
      if (!active) return
      setMe(current)
      setLoading(false)
    })
    return () => {
      active = false
    }
  }, [])

  const value = useMemo(() => ({ me, loading, refresh, logout }), [me, loading, refresh, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
