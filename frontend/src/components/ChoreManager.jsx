import { useEffect, useState } from 'react'
import {
  createChore,
  deactivateChore,
  listChores,
  listUsers,
  updateChore,
} from '../api'
import { formatCents } from '../currency'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const EMPTY_FORM = {
  name: '',
  description: '',
  valueText: '',
  schedule: 'none',
  weekdays: [],
  dayOfMonth: 1,
  claim_mode: 'per_user',
  cooldown_minutes: 5,
  assignee_ids: [],
}

function toPayload(form) {
  const payload = {
    name: form.name.trim(),
    description: form.description.trim() || null,
    value: Math.round(parseFloat(form.valueText || '0') * 100),
    schedule: form.schedule,
    schedule_config: null,
    claim_mode: form.claim_mode,
    cooldown_minutes: Number(form.cooldown_minutes) || 0,
    assignee_ids: form.assignee_ids.length ? form.assignee_ids : null,
  }
  if (form.schedule === 'weekly') payload.schedule_config = { weekdays: form.weekdays }
  if (form.schedule === 'monthly')
    payload.schedule_config = { day_of_month: Number(form.dayOfMonth) }
  return payload
}

function toForm(chore) {
  return {
    name: chore.name,
    description: chore.description || '',
    valueText: (chore.value / 100).toFixed(2),
    schedule: chore.schedule,
    weekdays: chore.schedule_config?.weekdays || [],
    dayOfMonth: chore.schedule_config?.day_of_month || 1,
    claim_mode: chore.claim_mode,
    cooldown_minutes: chore.cooldown_minutes,
    assignee_ids: chore.assignee_ids || [],
  }
}

export default function ChoreManager({ symbol }) {
  const [chores, setChores] = useState([])
  const [users, setUsers] = useState([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => listChores(true).then(setChores).catch((e) => setError(e.message))

  useEffect(() => {
    refresh()
    listUsers().then(setUsers).catch(() => setUsers([]))
  }, [])

  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value })

  const toggleInList = (field, id) => {
    const current = form[field]
    setForm({
      ...form,
      [field]: current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    })
  }

  const submit = async (event) => {
    event.preventDefault()
    setError(null)
    try {
      if (editingId) await updateChore(editingId, toPayload(form))
      else await createChore(toPayload(form))
      setForm(EMPTY_FORM)
      setEditingId(null)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  const startEdit = (chore) => {
    setEditingId(chore.id)
    setForm(toForm(chore))
  }

  const setActive = async (chore, active) => {
    if (active) await updateChore(chore.id, { is_active: true })
    else await deactivateChore(chore.id)
    refresh()
  }

  const input = 'w-full rounded border border-edge px-2 py-1 text-sm'
  const label = 'block text-xs font-semibold uppercase tracking-wide text-ink-muted'

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="space-y-3 rounded-xl bg-card p-4 shadow">
        <h2 className="font-semibold text-ink">
          {editingId ? 'Edit chore' : 'New chore'}
        </h2>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Name</label>
            <input className={input} value={form.name} onChange={set('name')} required />
          </div>
          <div>
            <label className={label}>Value ({symbol})</label>
            <input
              className={input}
              value={form.valueText}
              onChange={set('valueText')}
              type="number"
              step="0.01"
              min="0"
              required
            />
          </div>
        </div>
        <div>
          <label className={label}>Description</label>
          <input className={input} value={form.description} onChange={set('description')} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Schedule</label>
            <select className={input} value={form.schedule} onChange={set('schedule')}>
              <option value="none">Anytime (no schedule)</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
          <div>
            <label className={label}>Claim mode</label>
            <select className={input} value={form.claim_mode} onChange={set('claim_mode')}>
              <option value="per_user">Per user (everyone gets their own)</option>
              <option value="shared">Shared (first come, first served)</option>
              <option value="open">Open (repeatable after cooldown)</option>
            </select>
          </div>
        </div>
        {form.schedule === 'weekly' && (
          <div>
            <label className={label}>Weekdays</label>
            <div className="mt-1 flex gap-2">
              {WEEKDAYS.map((day, index) => (
                <button
                  type="button"
                  key={day}
                  onClick={() => toggleInList('weekdays', index)}
                  className={`rounded px-2 py-1 text-xs ${
                    form.weekdays.includes(index)
                      ? 'bg-accent text-white'
                      : 'bg-soft text-ink-muted'
                  }`}
                >
                  {day}
                </button>
              ))}
            </div>
          </div>
        )}
        {form.schedule === 'monthly' && (
          <div>
            <label className={label}>Day of month</label>
            <input
              className={input}
              type="number"
              min="1"
              max="31"
              value={form.dayOfMonth}
              onChange={set('dayOfMonth')}
            />
          </div>
        )}
        {form.claim_mode === 'open' && (
          <div>
            <label className={label}>Cooldown (minutes)</label>
            <input
              className={input}
              type="number"
              min="0"
              value={form.cooldown_minutes}
              onChange={set('cooldown_minutes')}
            />
          </div>
        )}
        {users.length > 0 && (
          <div>
            <label className={label}>Limit to (default: everyone)</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {users.map((user) => (
                <button
                  type="button"
                  key={user.id}
                  onClick={() => toggleInList('assignee_ids', user.id)}
                  className={`rounded px-2 py-1 text-xs ${
                    form.assignee_ids.includes(user.id)
                      ? 'bg-accent text-white'
                      : 'bg-soft text-ink-muted'
                  }`}
                >
                  {user.name || user.email}
                </button>
              ))}
            </div>
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          <button
            type="submit"
            className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90"
          >
            {editingId ? 'Save changes' : 'Create chore'}
          </button>
          {editingId && (
            <button
              type="button"
              onClick={() => {
                setEditingId(null)
                setForm(EMPTY_FORM)
              }}
              className="rounded border border-edge px-4 py-1.5 text-sm text-ink-muted"
            >
              Cancel
            </button>
          )}
        </div>
      </form>

      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Existing chores
      </h2>
      {chores.length === 0 ? (
        <p className="text-sm text-ink-faint">
          No chores yet — create one above and it will show up here for editing.
        </p>
      ) : (
        <ul className="space-y-2">
          {chores.map((chore) => (
            <li
              key={chore.id}
              className={`flex items-center justify-between rounded-xl bg-card p-4 shadow ${
                chore.is_active ? '' : 'opacity-60'
              }`}
            >
              <div>
                <p className="font-semibold text-ink">
                  {chore.name}
                  {!chore.is_active && (
                    <span className="ml-2 rounded bg-soft px-1.5 py-0.5 text-xs">
                      inactive
                    </span>
                  )}
                </p>
                <p className="text-xs text-ink-faint">
                  {chore.schedule} · {chore.claim_mode} ·{' '}
                  {formatCents(chore.value, symbol)}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => startEdit(chore)}
                  className="rounded border border-edge px-3 py-1 text-sm text-ink-muted"
                >
                  Edit
                </button>
                <button
                  onClick={() => setActive(chore, !chore.is_active)}
                  className="rounded border border-edge px-3 py-1 text-sm text-ink-muted"
                >
                  {chore.is_active ? 'Deactivate' : 'Reactivate'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
