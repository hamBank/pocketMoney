import { useEffect, useState } from 'react'
import { approveClaim, createClaim, listClaims, listUsers, rejectClaim } from '../api'
import { formatCents } from '../currency'

export default function ApprovalQueue({ symbol, onChanged }) {
  const [claims, setClaims] = useState(null)
  const [users, setUsers] = useState([])
  const [error, setError] = useState(null)

  const refresh = () => {
    listClaims({ status_filter: 'pending' }).then(setClaims).catch((e) => setError(e.message))
    listUsers().then(setUsers).catch(() => setUsers([]))
  }

  useEffect(() => {
    refresh()
  }, [])

  const acted = () => {
    refresh()
    onChanged?.()
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Awaiting approval
        </h2>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!claims ? (
          <p className="text-sm text-ink-faint">Loading…</p>
        ) : claims.length === 0 ? (
          <p className="text-sm text-ink-faint">Nothing to review. 🎉</p>
        ) : (
          <ul className="space-y-2">
            {claims.map((claim) => (
              <PendingClaim key={claim.id} claim={claim} symbol={symbol} onActed={acted} />
            ))}
          </ul>
        )}
      </section>
      <LodgeClaimForm users={users} symbol={symbol} onLodged={acted} />
    </div>
  )
}

function PendingClaim({ claim, symbol, onActed }) {
  const [valueText, setValueText] = useState(
    (claim.original_value / 100).toFixed(2),
  )
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)

  const act = async (fn) => {
    try {
      const value = Math.round(parseFloat(valueText) * 100)
      await fn(value)
      onActed()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <li className="rounded-xl bg-card p-4 shadow">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold text-ink">
            {claim.user_name}: {claim.chore_name}
          </p>
          <p className="text-xs text-ink-faint">
            {new Date(claim.submitted_at).toLocaleString()}
            {claim.submitted_by !== claim.user_id &&
              ` · lodged by ${claim.submitted_by_name}`}
            {claim.original_note && ` · “${claim.original_note}”`}
          </p>
        </div>
        <span className="font-bold text-ink">
          {formatCents(claim.original_value, symbol)}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="number"
          step="0.01"
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className="w-24 rounded border border-edge px-2 py-1 text-sm"
          title="Approved value — edit to pay a different amount"
        />
        <input
          placeholder="note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="flex-1 rounded border border-edge px-2 py-1 text-sm"
        />
        <button
          onClick={() =>
            act((value) => approveClaim(claim.id, { approved_value: value, note: note || null }))
          }
          className="rounded bg-accent px-3 py-1 text-sm font-semibold text-white hover:opacity-90"
        >
          Approve
        </button>
        <button
          onClick={() => act(() => rejectClaim(claim.id, { note: note || null }))}
          className="rounded border border-red-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50"
        >
          Reject
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </li>
  )
}

function LodgeClaimForm({ users, symbol, onLodged }) {
  const [form, setForm] = useState({
    user_id: '',
    name: '',
    valueText: '',
    penalty: false,
    auto_approve: true,
    create_chore: false,
  })
  const [error, setError] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    const cents = Math.round(parseFloat(form.valueText || '0') * 100)
    try {
      await createClaim({
        kind: form.penalty ? 'penalty' : 'adhoc',
        user_id: Number(form.user_id),
        name: form.name.trim(),
        value: form.penalty ? -Math.abs(cents) : Math.abs(cents),
        auto_approve: form.auto_approve,
        create_chore: form.create_chore && !form.penalty,
      })
      setForm({ ...form, name: '', valueText: '' })
      onLodged()
    } catch (e) {
      setError(e.message)
    }
  }

  const input = 'rounded border border-edge px-2 py-1 text-sm'
  return (
    <form onSubmit={submit} className="space-y-3 rounded-xl bg-card p-4 shadow">
      <h2 className="font-semibold text-ink">Lodge a one-off</h2>
      <div className="flex flex-wrap items-center gap-2">
        <select
          required
          className={input}
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
        >
          <option value="">Who?</option>
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name || user.email}
            </option>
          ))}
        </select>
        <input
          required
          placeholder="What for?"
          className={`${input} flex-1`}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          required
          type="number"
          step="0.01"
          min="0.01"
          placeholder={symbol}
          className={`${input} w-24`}
          value={form.valueText}
          onChange={(e) => setForm({ ...form, valueText: e.target.value })}
        />
      </div>
      <div className="flex flex-wrap gap-4 text-sm text-ink-muted">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={form.penalty}
            onChange={(e) => setForm({ ...form, penalty: e.target.checked })}
          />
          Penalty (deducts)
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={form.auto_approve}
            onChange={(e) => setForm({ ...form, auto_approve: e.target.checked })}
          />
          Approve immediately
        </label>
        {!form.penalty && (
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={form.create_chore}
              onChange={(e) => setForm({ ...form, create_chore: e.target.checked })}
            />
            Also create as an ongoing chore
          </label>
        )}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        className="rounded bg-ink px-4 py-1.5 text-sm font-semibold text-page hover:opacity-90"
      >
        Lodge
      </button>
    </form>
  )
}
