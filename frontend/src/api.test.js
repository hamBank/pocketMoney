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

  it('does not restore a refreshed token after sign-out mid-request', async () => {
    let release
    global.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          release = () =>
            resolve({
              ok: true,
              status: 200,
              json: async () => [],
              headers: { get: (name) => (name === 'X-Refreshed-Token' ? 'late-token' : null) },
            })
        }),
    )
    const pending = apiFetch('/auth/me')
    setToken(null) // signed out while the request was in flight
    release()
    await pending
    expect(getToken()).toBeNull()
  })

  it('ignores a 401 for a token that has since been replaced', async () => {
    let release
    global.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          release = () =>
            resolve({ ok: false, status: 401, statusText: '', json: async () => ({}), headers: { get: () => null } })
        }),
    )
    const pending = apiFetch('/claims')
    setToken('new-sign-in')
    release()
    await expect(pending).rejects.toThrow()
    expect(getToken()).toBe('new-sign-in')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('ignores a 401 when no token was sent (e.g. a failed login)', async () => {
    setToken(null)
    respond(401)
    await expect(apiFetch('/auth/google', { method: 'POST', body: {} })).rejects.toThrow()
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
