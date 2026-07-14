import { useEffect, useState } from 'react'
import { listChores } from '../api'
import { formatCents } from '../currency'

const SCHEDULE_LABELS = {
  none: 'Anytime',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
}

export default function ChoreList({ symbol }) {
  const [chores, setChores] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    listChores().then(setChores).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!chores) return <p className="text-sm text-slate-400">Loading chores…</p>
  if (chores.length === 0)
    return <p className="text-sm text-slate-400">No chores yet.</p>

  const due = chores.filter((c) => c.claimable)
  const rest = chores.filter((c) => !c.claimable)

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Chores due
        </h2>
        {due.length === 0 ? (
          <p className="text-sm text-slate-400">All caught up! 🎉</p>
        ) : (
          <ul className="space-y-2">
            {due.map((chore) => (
              <ChoreCard key={chore.id} chore={chore} symbol={symbol} due />
            ))}
          </ul>
        )}
      </section>
      {rest.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Not available right now
          </h2>
          <ul className="space-y-2">
            {rest.map((chore) => (
              <ChoreCard key={chore.id} chore={chore} symbol={symbol} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function ChoreCard({ chore, symbol, due = false }) {
  return (
    <li
      className={`flex items-center justify-between rounded-xl bg-white p-4 shadow ${
        due ? '' : 'opacity-60'
      }`}
    >
      <div>
        <p className="font-semibold text-slate-800">{chore.name}</p>
        {chore.description && (
          <p className="text-sm text-slate-500">{chore.description}</p>
        )}
        <p className="text-xs text-slate-400">
          {SCHEDULE_LABELS[chore.schedule]}
          {chore.claim_mode === 'shared' && ' · first come, first served'}
          {chore.claim_mode === 'open' && ' · repeatable'}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-bold text-emerald-600">
          {formatCents(chore.value, symbol)}
        </span>
        <button
          disabled
          title="Claiming arrives in Phase 3"
          className="cursor-not-allowed rounded bg-slate-200 px-3 py-1 text-sm text-slate-400"
        >
          Claim
        </button>
      </div>
    </li>
  )
}
