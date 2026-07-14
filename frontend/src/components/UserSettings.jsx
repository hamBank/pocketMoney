import ThemePicker from './ThemePicker'

export default function UserSettings({ open, onClose }) {
  if (!open) return null
  return (
    <div className="rounded-xl bg-card p-4 shadow">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold text-ink">Settings</h2>
        <button
          onClick={onClose}
          className="rounded border border-edge px-2 py-0.5 text-xs text-ink-muted"
        >
          Close
        </button>
      </div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        Theme
      </p>
      <ThemePicker />
    </div>
  )
}
