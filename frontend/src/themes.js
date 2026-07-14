export const THEMES = [
  { id: 'light', label: 'Light', swatch: '#f1f5f9' },
  { id: 'dark', label: 'Dark', swatch: '#0f172a' },
  { id: 'mint', label: 'Mint', swatch: '#a7f3d0' },
  { id: 'ocean', label: 'Ocean', swatch: '#bae6fd' },
  { id: 'sunset', label: 'Sunset', swatch: '#fed7aa' },
]

const STORAGE_KEY = 'pm_theme'

export function currentTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  return THEMES.some((t) => t.id === saved) ? saved : 'light'
}

export function applyTheme(id) {
  document.documentElement.dataset.theme = id
  localStorage.setItem(STORAGE_KEY, id)
}

export function initTheme() {
  document.documentElement.dataset.theme = currentTheme()
}
