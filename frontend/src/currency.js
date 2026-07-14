// All amounts are integer cents (see SPEC.md). Formatting is the frontend's
// job; the symbol will come from /auth/config once auth lands.
const DEFAULT_SYMBOL = '$'

export function formatCents(cents, symbol = DEFAULT_SYMBOL) {
  const sign = cents < 0 ? '-' : ''
  const abs = Math.abs(cents)
  const units = Math.floor(abs / 100)
  const remainder = String(abs % 100).padStart(2, '0')
  return `${sign}${symbol}${units}.${remainder}`
}
