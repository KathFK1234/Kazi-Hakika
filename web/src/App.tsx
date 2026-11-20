import { useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useNavigate } from 'react-router'
import { api, type Meta } from './api'
import { AuthProvider } from './auth'
import { useAuth } from './auth-context'
import { ApplicationPage } from './pages/ApplicationPage'
import { ForgotPasswordPage, LoginPage, ResetPasswordPage, SignupPage, VerifyEmailPage } from './pages/AuthPages'
import { GoodbyePage, SettingsPage } from './pages/SettingsPage'
import { TrackerPage } from './pages/TrackerPage'

const FALLBACK: Meta = { name: 'Kazi Hakika', tagline: 'verified roles, tracked your way.' }

function useMeta(): Meta {
  const [meta, setMeta] = useState<Meta>(FALLBACK)
  useEffect(() => {
    let active = true
    api.meta().then(
      (m) => {
        if (active) setMeta(m)
      },
      () => {
        // Keep the fallback name; the page still works.
      },
    )
    return () => {
      active = false
    }
  }, [])
  return meta
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <p aria-busy="true">Loading…</p>
  if (!me) return <Navigate to="/login" replace />
  return children
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <p aria-busy="true">Loading…</p>
  if (me) return <Navigate to="/" replace />
  return children
}

function Header({ meta }: { meta: Meta }) {
  const { me, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <header className="site-header">
      <div className="brand-block">
        <Link to="/" className="brand">
          {meta.name}
        </Link>
        <span className="tagline">{meta.tagline}</span>
      </div>
      {me && (
        <nav aria-label="Main">
          <NavLink to="/" end>
            Applications
          </NavLink>
          <NavLink to="/settings">Settings</NavLink>
          <button
            type="button"
            className="link"
            onClick={() => {
              void logout().then(() => navigate('/login'))
            }}
          >
            Sign out
          </button>
        </nav>
      )}
    </header>
  )
}

function UnverifiedBanner() {
  const { me } = useAuth()
  if (!me || me.email_verified) return null
  return (
    <p className="banner" role="status">
      Confirm your email to get deadline reminders. Check your inbox, or <Link to="/settings">send a new link</Link>.
    </p>
  )
}

function NotFound() {
  return (
    <section>
      <h1>Page not found</h1>
      <Link to="/">Go to your applications</Link>
    </section>
  )
}

export function AppRoutes() {
  const meta = useMeta()
  return (
    <div className="shell">
      <Header meta={meta} />
      <UnverifiedBanner />
      <main>
        <Routes>
          <Route path="/" element={<RequireAuth><TrackerPage /></RequireAuth>} />
          <Route path="/applications/new" element={<RequireAuth><ApplicationPage /></RequireAuth>} />
          <Route path="/applications/:id" element={<RequireAuth><ApplicationPage /></RequireAuth>} />
          <Route path="/settings" element={<RequireAuth><SettingsPage /></RequireAuth>} />
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="/signup" element={<GuestOnly><SignupPage /></GuestOnly>} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/goodbye" element={<GoodbyePage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <p>
          {meta.name}: {meta.tagline} We never apply for you and never promise a job.
        </p>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
