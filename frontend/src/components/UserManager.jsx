import { useEffect, useState } from 'react'
import { createTransaction, listUsers, updateUser } from '../api'
import { formatCents } from '../currency'

export default function UserManager({ symbol, onChanged }) {
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => listUsers().then(setUsers).catch((e) => setError(e.message))
  useEffect(refresh, [])

  const acted = () => {
    refresh()
    onChanged?.()
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!users) return <p className="text-sm text-ink-faint">Loading…</p>

  return (
    <ul className="space-y-3">
      {users.map((user) => (
        <UserRow key={user.id} user={user} symbol={symbol} onActed={acted} />
      ))}
    </ul>
  )
}

function UserRow({ user, symbol, onActed }) {
  const [allowanceText, setAllowanceText] = useState(
    (user.weekly_allowance / 100).toFixed(2),
  )
  const [amountText, setAmountText] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)

  const run = async (fn) => {
    setError(null)
    try {
      await fn()
      onActed()
    } catch (e) {
      setError(e.message)
    }
  }

  const saveAllowance = () =>
    run(() =>
      updateUser(user.id, {
        weekly_allowance: Math.round(parseFloat(allowanceText || '0') * 100),
      }),
    )

  const record = (type) => {
    const cents = Math.round(parseFloat(amountText || '0') * 100)
    return run(async () => {
      await createTransaction({
        user_id: user.id,
        type,
        amount: type === 'withdrawal' ? -Math.abs(cents) : cents,
        note: note.trim() || null,
      })
      setAmountText('')
      setNote('')
    })
  }

  const input = 'rounded border border-edge px-2 py-1 text-sm'
  return (
    <li className="rounded-xl bg-card p-4 shadow">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold text-ink">
            {user.name || user.email}
            {user.role === 'admin' && (
              <span className="ml-2 rounded bg-soft px-1.5 py-0.5 text-xs">admin</span>
            )}
            {!user.is_active && (
              <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-600">
                inactive
              </span>
            )}
          </p>
          <p className="text-xs text-ink-faint">{user.email}</p>
        </div>
        <span
          className={`text-xl font-bold ${
            user.balance < 0 ? 'text-red-600' : 'text-ink'
          }`}
        >
          {formatCents(user.balance, symbol)}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-edge pt-3">
        <label className="text-xs text-ink-muted">Weekly allowance</label>
        <input
          type="number"
          step="0.01"
          className={`${input} w-24`}
          value={allowanceText}
          onChange={(e) => setAllowanceText(e.target.value)}
        />
        <button
          onClick={saveAllowance}
          className="rounded border border-edge px-2 py-1 text-xs text-ink-muted"
        >
          Save
        </button>
        <span className="mx-2 text-edge">|</span>
        <input
          type="number"
          step="0.01"
          min="0"
          placeholder={symbol}
          className={`${input} w-24`}
          value={amountText}
          onChange={(e) => setAmountText(e.target.value)}
        />
        <input
          placeholder="note"
          className={`${input} w-40`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          onClick={() => record('withdrawal')}
          className="rounded bg-ink px-3 py-1 text-xs font-semibold text-page"
        >
          Pay out
        </button>
        <button
          onClick={() => record('adjustment')}
          className="rounded border border-edge px-3 py-1 text-xs text-ink-muted"
          title="Signed adjustment — note required"
        >
          Adjust
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </li>
  )
}
