import { useEffect, useState } from 'react'
import { getAuthConfig, getMe, getToken, setToken } from './api'
import { formatCents } from './currency'
import LoginPage from './components/LoginPage'

function Centered({ children }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100">
      <div className="rounded-xl bg-white p-8 text-slate-600 shadow">{children}</div>
    </div>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

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
  }

  if (loading) return <Centered>Loading…</Centered>
  if (error) return <Centered>{error}</Centered>
  if (!user) return <LoginPage config={config} onSignedIn={setUser} />

  const symbol = config.currency_symbol || '$'
  return (
    <div className="min-h-screen bg-slate-100">
      <header className="flex items-center justify-between bg-white px-6 py-3 shadow">
        <h1 className="text-lg font-bold text-slate-800">Pocket Money</h1>
        <div className="flex items-center gap-3">
          {user.avatar_url && (
            <img src={user.avatar_url} alt="" className="h-8 w-8 rounded-full" />
          )}
          <span className="text-sm text-slate-600">
            {user.name || user.email}
            {user.role === 'admin' && (
              <span className="ml-1 rounded bg-slate-200 px-1.5 py-0.5 text-xs">admin</span>
            )}
          </span>
          <button
            onClick={signOut}
            className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl p-6">
        <div className="rounded-xl bg-white p-6 shadow">
          <p className="text-sm text-slate-500">Balance</p>
          <p className="text-3xl font-bold text-slate-800">
            {formatCents(user.balance, symbol)}
          </p>
          <p className="mt-4 text-sm text-slate-400">
            Chores arrive in Phase 2 — see IMPLEMENTATION_PLAN.md.
          </p>
        </div>
      </main>
    </div>
  )
}
