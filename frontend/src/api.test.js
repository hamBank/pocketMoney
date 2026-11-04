import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, apiFetchPaged, getToken, setToken, setUnauthorizedHandler } from './api'

function respond(status, headers = {}) {
  global.fetch = vi.fn(async () => ({
    ok: status < 400,
    status,
    statusText: '',
    json: async () => (status < 400 ? [] : { detail: 'Invalid or expired token' }),
    headers: { get: (name) => headers[name] ?? null },
  }))
}

describe('session handling', () => {
  let unauthorized

  beforeEach(() => {
    unauthorized = vi.fn()
    setUnauthorizedHandler(unauthorized)
    setToken('old-token')
  })

  afterEach(() => {
    setUnauthorizedHandler(() => {})
    setToken(null)
  })

  it('stores a refreshed token from the response header', async () => {
    respond(200, { 'X-Refreshed-Token': 'new-token' })
    await apiFetch('/auth/me')
    expect(getToken()).toBe('new-token')
  })

  it('keeps the token when no refresh is sent', async () => {
    respond(200, { 'X-Total-Count': '0' })
    await apiFetchPaged('/claims')
    expect(getToken()).toBe('old-token')
  })

  it('signs out on a 401 for a request that carried a token', async () => {
    respond(401)
    await expect(apiFetch('/claims')).rejects.toThrow('Invalid or expired token')
    expect(getToken()).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('signs out on a 401 from a paged request', async () => {
    respond(401)
    await expect(apiFetchPaged('/claims')).rejects.toThrow()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('ignores a 401 when no token was sent (e.g. a failed login)', async () => {
    setToken(null)
    respond(401)
    await expect(apiFetch('/auth/google', { method: 'POST', body: {} })).rejects.toThrow()
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
