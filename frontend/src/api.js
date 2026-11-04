const TOKEN_KEY = 'pm_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// Called when a request carrying our token comes back 401 (expired, or the
// account was deactivated) so the app can drop back to the login page.
let onUnauthorized = () => {}
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

// The backend swaps a token past half its life for a fresh one in this
// header; a 401 on a request we sent a token with means the session is over.
function trackSession(response, sentToken) {
  const refreshed = response.headers.get('X-Refreshed-Token')
  if (refreshed) setToken(refreshed)
  if (response.status === 401 && sentToken) {
    setToken(null)
    onUnauthorized()
  }
}

export async function apiFetch(path, { method = 'GET', body } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  trackSession(response, token)
  if (!response.ok) {
    let detail
    try {
      detail = (await response.json()).detail
    } catch {
      // non-JSON error body
    }
    const error = new Error(detail || `${response.status} ${response.statusText}`)
    error.status = response.status
    throw error
  }
  return response.status === 204 ? null : response.json()
}

// Auth
export const getAuthConfig = () => apiFetch('/auth/config')
export const loginWithGoogle = (credential) =>
  apiFetch('/auth/google', { method: 'POST', body: { credential } })
export const getMe = () => apiFetch('/auth/me')

// Chores
export const listChores = (all = false) =>
  apiFetch(all ? '/chores?all=true' : '/chores')
export const createChore = (data) =>
  apiFetch('/chores', { method: 'POST', body: data })
export const updateChore = (id, data) =>
  apiFetch(`/chores/${id}`, { method: 'PATCH', body: data })
export const deactivateChore = (id) =>
  apiFetch(`/chores/${id}`, { method: 'DELETE' })

// Paged GET: resolves to { items, total } using the X-Total-Count header.
export async function apiFetchPaged(path) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const response = await fetch(path, { headers })
  trackSession(response, token)
  if (!response.ok) {
    let detail
    try {
      detail = (await response.json()).detail
    } catch {
      // non-JSON error body
    }
    throw new Error(detail || `${response.status} ${response.statusText}`)
  }
  return {
    items: await response.json(),
    total: Number(response.headers.get('X-Total-Count') || 0),
  }
}

// Claims
export const listClaims = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return apiFetch(qs ? `/claims?${qs}` : '/claims')
}
export const listClaimsPaged = (params = {}) =>
  apiFetchPaged(`/claims?${new URLSearchParams(params)}`)
export const createClaim = (data) =>
  apiFetch('/claims', { method: 'POST', body: data })
export const approveClaim = (id, data = {}) =>
  apiFetch(`/claims/${id}/approve`, { method: 'POST', body: data })
export const rejectClaim = (id, data = {}) =>
  apiFetch(`/claims/${id}/reject`, { method: 'POST', body: data })
export const cancelClaim = (id) =>
  apiFetch(`/claims/${id}/cancel`, { method: 'POST', body: {} })

// Transactions
export const listTransactions = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return apiFetch(qs ? `/transactions?${qs}` : '/transactions')
}
export const listTransactionsPaged = (params = {}) =>
  apiFetchPaged(`/transactions?${new URLSearchParams(params)}`)
export const createTransaction = (data) =>
  apiFetch('/transactions', { method: 'POST', body: data })

// Users (admin)
export const listUsers = () => apiFetch('/users')
export const inviteUser = (data) =>
  apiFetch('/users/invite', { method: 'POST', body: data })
export const updateUser = (id, data) =>
  apiFetch(`/users/${id}`, { method: 'PATCH', body: data })
