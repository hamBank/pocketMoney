import { useEffect, useState } from 'react'
import { cancelClaim, listClaims, listTransactions } from '../api'
import { formatCents } from '../currency'

const STATUS_STYLES = {
  pending: 'bg-amber-100 text-amber-700',
  approved: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-red-100 text-red-700',
  cancelled: 'bg-slate-200 text-slate-500',
}

const TYPE_LABELS = {
  claim_payout: 'Chore payout',
  penalty: 'Penalty',
  withdrawal: 'Withdrawal',
  adjustment: 'Adjustment',
  allowance: 'Allowance',
}

export default function ClaimHistory({ symbol, onChanged }) {
  const [claims, setClaims] = useState(null)
  const [transactions, setTransactions] = useState(null)

  const refresh = () => {
    listClaims().then(setClaims).catch(() => setClaims([]))
    listTransactions().then(setTransactions).catch(() => setTransactions([]))
  }

  useEffect(refresh, [])

  const cancel = async (id) => {
    await cancelClaim(id)
    refresh()
    onChanged?.()
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          My claims
        </h2>
        {!claims ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : claims.length === 0 ? (
          <p className="text-sm text-slate-400">No claims yet.</p>
        ) : (
          <ul className="space-y-2">
            {claims.map((claim) => (
              <li
                key={claim.id}
                className="flex items-center justify-between rounded-xl bg-white p-3 shadow"
              >
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    {claim.chore_name}
                    <span
                      className={`ml-2 rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[claim.status]}`}
                    >
                      {claim.status}
                    </span>
                  </p>
                  <p className="text-xs text-slate-400">
                    {new Date(claim.submitted_at).toLocaleString()}
                    {claim.resolution_note && ` · “${claim.resolution_note}”`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-700">
                    {formatCents(
                      claim.approved_value ?? claim.original_value,
                      symbol,
                    )}
                  </span>
                  {claim.status === 'pending' && (
                    <button
                      onClick={() => cancel(claim.id)}
                      className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-500"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Money history
        </h2>
        {!transactions ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : transactions.length === 0 ? (
          <p className="text-sm text-slate-400">Nothing yet.</p>
        ) : (
          <ul className="space-y-1">
            {transactions.map((tx) => (
              <li
                key={tx.id}
                className="flex items-center justify-between rounded-lg bg-white px-3 py-2 shadow-sm"
              >
                <span className="text-sm text-slate-600">
                  {TYPE_LABELS[tx.type]}
                  {tx.note && <span className="text-slate-400"> · {tx.note}</span>}
                </span>
                <span
                  className={`text-sm font-bold ${
                    tx.amount < 0 ? 'text-red-600' : 'text-emerald-600'
                  }`}
                >
                  {formatCents(tx.amount, symbol)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
