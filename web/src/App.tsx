import { useEffect, useRef, useState, type ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router'
import { api, type Meta } from './api'
import { AuthProvider } from './auth'
import { ThemeSwitch } from './components/ThemeSwitch'
import { useAuth } from './auth-context'
import { ApplicationPage } from './pages/ApplicationPage'
import { ForgotPasswordPage, LoginPage, ResetPasswordPage, SignupPage, VerifyEmailPage } from './pages/AuthPages'
import { PrivacyPage } from './pages/PrivacyPage'
import { GoodbyePage, SettingsPage } from './pages/SettingsPage'
import { TrackerPage } from './pages/TrackerPage'
import { useTitle } from './useTitle'

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
      <div className="header-tools">
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
        <ThemeSwitch />
      </div>
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
  useTitle('Page not found')
  return (
    <section>
      <h1>Page not found</h1>
      <Link to="/">Go to your applications</Link>
    </section>
  )
}

/** After in-app navigation, move focus to the new page so it's announced. */
function useFocusMainOnNavigate() {
  const { pathname } = useLocation()
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    document.getElementById('main')?.focus()
  }, [pathname])
}

export function AppRoutes() {
  const meta = useMeta()
  useFocusMainOnNavigate()
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Header meta={meta} />
      <UnverifiedBanner />
      <main id="main" tabIndex={-1}>
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
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <p>
          {meta.name}: {meta.tagline} We never apply for you and never promise a job.{' '}
          <Link to="/privacy">Your data</Link>
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
