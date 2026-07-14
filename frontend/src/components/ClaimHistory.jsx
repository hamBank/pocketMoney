import { useEffect, useState } from 'react'
import { cancelClaim, listClaimsPaged, listTransactionsPaged } from '../api'
import { formatCents } from '../currency'

const PAGE = 20

// Paged list state: load(reset) fetches page 1, loadMore appends.
function usePaged(fetchPage) {
  const [items, setItems] = useState(null)
  const [total, setTotal] = useState(0)

  const load = (offset = 0) =>
    fetchPage(offset)
      .then(({ items: page, total: t }) => {
        setItems((prev) => (offset === 0 ? page : [...(prev || []), ...page]))
        setTotal(t)
      })
      .catch(() => setItems((prev) => prev || []))

  const refresh = () => load(0)
  const loadMore = () => load(items?.length || 0)
  const hasMore = items !== null && items.length < total
  return { items, refresh, loadMore, hasMore }
}

function LoadMore({ paged }) {
  if (!paged.hasMore) return null
  return (
    <button
      onClick={paged.loadMore}
      className="mt-2 rounded border border-edge px-3 py-1 text-xs text-ink-muted"
    >
      Load more
    </button>
  )
}

const STATUS_STYLES = {
  pending: 'bg-amber-100 text-amber-700',
  approved: 'bg-accent-soft text-accent',
  rejected: 'bg-red-100 text-red-700',
  cancelled: 'bg-soft text-ink-muted',
}

const TYPE_LABELS = {
  claim_payout: 'Chore payout',
  penalty: 'Penalty',
  withdrawal: 'Withdrawal',
  adjustment: 'Adjustment',
  allowance: 'Allowance',
}

export default function ClaimHistory({ symbol, onChanged }) {
  const claimsPaged = usePaged((offset) =>
    listClaimsPaged({ limit: PAGE, offset }),
  )
  const txPaged = usePaged((offset) =>
    listTransactionsPaged({ limit: PAGE, offset }),
  )
  const claims = claimsPaged.items
  const transactions = txPaged.items

  useEffect(() => {
    claimsPaged.refresh()
    txPaged.refresh()
  }, [])

  const cancel = async (id) => {
    await cancelClaim(id)
    claimsPaged.refresh()
    txPaged.refresh()
    onChanged?.()
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          My claims
        </h2>
        {!claims ? (
          <p className="text-sm text-ink-faint">Loading…</p>
        ) : claims.length === 0 ? (
          <p className="text-sm text-ink-faint">No claims yet.</p>
        ) : (
          <ul className="space-y-2">
            {claims.map((claim) => (
              <li
                key={claim.id}
                className="flex items-center justify-between rounded-xl bg-card p-3 shadow"
              >
                <div>
                  <p className="text-sm font-semibold text-ink">
                    {claim.chore_name}
                    <span
                      className={`ml-2 rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[claim.status]}`}
                    >
                      {claim.status}
                    </span>
                  </p>
                  <p className="text-xs text-ink-faint">
                    {new Date(claim.submitted_at).toLocaleString()}
                    {claim.resolution_note && ` · “${claim.resolution_note}”`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-ink">
                    {formatCents(
                      claim.approved_value ?? claim.original_value,
                      symbol,
                    )}
                  </span>
                  {claim.status === 'pending' && (
                    <button
                      onClick={() => cancel(claim.id)}
                      className="rounded border border-edge px-2 py-0.5 text-xs text-ink-muted"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <LoadMore paged={claimsPaged} />
      </section>
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Money history
        </h2>
        {!transactions ? (
          <p className="text-sm text-ink-faint">Loading…</p>
        ) : transactions.length === 0 ? (
          <p className="text-sm text-ink-faint">Nothing yet.</p>
        ) : (
          <ul className="space-y-1">
            {transactions.map((tx) => (
              <li
                key={tx.id}
                className="flex items-center justify-between rounded-lg bg-card px-3 py-2 shadow-sm"
              >
                <span className="text-sm text-ink-muted">
                  {TYPE_LABELS[tx.type]}
                  {tx.note && <span className="text-ink-faint"> · {tx.note}</span>}
                </span>
                <span
                  className={`text-sm font-bold ${
                    tx.amount < 0 ? 'text-red-600' : 'text-accent'
                  }`}
                >
                  {formatCents(tx.amount, symbol)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <LoadMore paged={txPaged} />
      </section>
    </div>
  )
}
