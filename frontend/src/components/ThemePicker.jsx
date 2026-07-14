import { useState } from 'react'
import { applyTheme, currentTheme, THEMES } from '../themes'

export default function ThemePicker() {
  const [selected, setSelected] = useState(currentTheme())

  const pick = (id) => {
    applyTheme(id)
    setSelected(id)
  }

  return (
    <div className="flex flex-wrap gap-2">
      {THEMES.map((theme) => (
        <button
          key={theme.id}
          onClick={() => pick(theme.id)}
          className={`flex items-center gap-2 rounded border px-3 py-1.5 text-sm ${
            selected === theme.id
              ? 'border-accent text-ink'
              : 'border-edge text-ink-muted'
          }`}
        >
          <span
            className="h-4 w-4 rounded-full border border-edge"
            style={{ backgroundColor: theme.swatch }}
          />
          {theme.label}
        </button>
      ))}
    </div>
  )
}
