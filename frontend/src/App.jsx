import { useCallback, useEffect, useState } from 'react'
import { getAuthConfig, getMe, getToken, setToken, setUnauthorizedHandler } from './api'
import { formatCents } from './currency'
import ApprovalQueue from './components/ApprovalQueue'
import ChoreList from './components/ChoreList'
import ChoreManager from './components/ChoreManager'
import ClaimHistory from './components/ClaimHistory'
import LoginPage from './components/LoginPage'
import UserManager from './components/UserManager'
import UserSettings from './components/UserSettings'

function Centered({ children }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-page">
      <div className="rounded-xl bg-card p-8 text-ink-muted shadow">{children}</div>
    </div>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('chores')
  const [showSettings, setShowSettings] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      setSessionExpired(true)
    })
    return () => setUnauthorizedHandler(() => {})
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        const cfg = await getAuthConfig()
        setConfig(cfg)
        if (!cfg.auth_enabled || getToken()) {
          try {
            setUser(await getMe())
          } catch {
            setToken(null) // expired/invalid token — fall through to login
          }
        }
      } catch {
        setError('Backend unreachable')
      }
      setLoading(false)
    })()
  }, [])

  const signOut = () => {
    setToken(null)
    setUser(null)
    setSessionExpired(false)
  }

  const signedIn = useCallback((signedInUser) => {
    setSessionExpired(false)
    setUser(signedInUser)
  }, [])

  const refreshUser = () => getMe().then(setUser).catch(() => {})

  if (loading) return <Centered>Loading…</Centered>
  if (error) return <Centered>{error}</Centered>
  if (!user) {
    return (
      <LoginPage config={config} onSignedIn={signedIn} sessionExpired={sessionExpired} />
    )
  }

  const symbol = config.currency_symbol || '$'
  return (
    <div className="min-h-screen bg-page">
      <header className="flex flex-wrap items-center justify-between gap-y-2 bg-card px-4 py-3 shadow sm:px-6">
        <h1 className="text-lg font-bold text-ink">Pocket Money</h1>
        <div className="flex flex-wrap items-center gap-3">
          {user.avatar_url && (
            <img src={user.avatar_url} alt="" className="h-8 w-8 rounded-full" />
          )}
          <span className="text-sm text-ink-muted">
            {user.name || user.email}
            {user.role === 'admin' && (
              <span className="ml-1 rounded bg-soft px-1.5 py-0.5 text-xs">admin</span>
            )}
          </span>
          <button
            onClick={() => setShowSettings((s) => !s)}
            title="Settings"
            className="rounded border border-edge px-2 py-1 text-sm text-ink-muted hover:opacity-80"
          >
            ⚙
          </button>
          <button
            onClick={signOut}
            className="rounded border border-edge px-3 py-1 text-sm text-ink-muted hover:opacity-80"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
        <UserSettings open={showSettings} onClose={() => setShowSettings(false)} />
        <div className="rounded-xl bg-card p-6 shadow">
          <p className="text-sm text-ink-muted">Balance</p>
          <p
            className={`text-3xl font-bold ${
              user.balance < 0 ? 'text-red-600' : 'text-ink'
            }`}
          >
            {formatCents(user.balance, symbol)}
          </p>
        </div>
        <nav className="flex flex-wrap gap-2">
          {[
            ['chores', 'Chores'],
            ['history', 'History'],
            ...(user.role === 'admin'
              ? [
                  ['approvals', 'Approvals'],
                  ['users', 'Users'],
                  ['manage', 'Manage chores'],
                ]
              : []),
          ].map(([key, title]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`rounded px-3 py-1 text-sm ${
                tab === key
                  ? 'bg-ink text-page'
                  : 'bg-card text-ink-muted shadow'
              }`}
            >
              {title}
            </button>
          ))}
        </nav>
        {tab === 'chores' && <ChoreList symbol={symbol} onChanged={refreshUser} />}
        {tab === 'history' && <ClaimHistory symbol={symbol} onChanged={refreshUser} />}
        {tab === 'approvals' && user.role === 'admin' && (
          <ApprovalQueue symbol={symbol} onChanged={refreshUser} />
        )}
        {tab === 'users' && user.role === 'admin' && (
          <UserManager symbol={symbol} onChanged={refreshUser} />
        )}
        {tab === 'manage' && user.role === 'admin' && <ChoreManager symbol={symbol} />}
      </main>
    </div>
  )
}
