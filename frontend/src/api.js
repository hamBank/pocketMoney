const TOKEN_KEY = 'pm_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
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

// Users (admin)
export const listUsers = () => apiFetch('/users')
export const inviteUser = (data) =>
  apiFetch('/users/invite', { method: 'POST', body: data })
export const updateUser = (id, data) =>
  apiFetch(`/users/${id}`, { method: 'PATCH', body: data })
