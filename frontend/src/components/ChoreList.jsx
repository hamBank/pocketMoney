import { useEffect, useState } from 'react'
import { createClaim, listChores } from '../api'
import { formatCents } from '../currency'

const SCHEDULE_LABELS = {
  none: 'Anytime',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
}

export default function ChoreList({ symbol, onChanged }) {
  const [chores, setChores] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => listChores().then(setChores).catch((e) => setError(e.message))
  // Block body so the effect returns undefined — refresh returns a Promise,
  // and React would call it as a cleanup function on unmount and crash.
  useEffect(() => {
    refresh()
  }, [])

  const claim = async (chore) => {
    setError(null)
    try {
      await createClaim({ chore_id: chore.id })
      refresh()
      onChanged?.()
    } catch (e) {
      setError(e.message)
    }
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!chores) return <p className="text-sm text-ink-faint">Loading chores…</p>
  if (chores.length === 0)
    return <p className="text-sm text-ink-faint">No chores yet.</p>

  const due = chores.filter((c) => c.claimable)
  const rest = chores.filter((c) => !c.claimable)

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Chores due
        </h2>
        {due.length === 0 ? (
          <p className="text-sm text-ink-faint">All caught up! 🎉</p>
        ) : (
          <ul className="space-y-2">
            {due.map((chore) => (
              <ChoreCard key={chore.id} chore={chore} symbol={symbol} onClaim={claim} due />
            ))}
          </ul>
        )}
      </section>
      {rest.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-faint">
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

function ChoreCard({ chore, symbol, onClaim, due = false }) {
  return (
    <li
      className={`flex items-center justify-between rounded-xl bg-card p-4 shadow ${
        due ? '' : 'opacity-60'
      }`}
    >
      <div>
        <p className="font-semibold text-ink">{chore.name}</p>
        {chore.description && (
          <p className="text-sm text-ink-muted">{chore.description}</p>
        )}
        <p className="text-xs text-ink-faint">
          {SCHEDULE_LABELS[chore.schedule]}
          {chore.claim_mode === 'shared' && ' · first come, first served'}
          {chore.claim_mode === 'open' && ' · repeatable'}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-bold text-accent">
          {formatCents(chore.value, symbol)}
        </span>
        {due ? (
          <button
            onClick={() => onClaim(chore)}
            className="rounded bg-accent px-3 py-1 text-sm font-semibold text-white hover:opacity-90"
          >
            Claim
          </button>
        ) : (
          <button
            disabled
            className="cursor-not-allowed rounded bg-soft px-3 py-1 text-sm text-ink-faint"
          >
            Claim
          </button>
        )}
      </div>
    </li>
  )
}
