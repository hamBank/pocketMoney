import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import UpdateBanner, { isStale } from './UpdateBanner'

function deployed(frontendSha) {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ status: 'ok', frontend_sha: frontendSha }),
    headers: { get: () => null },
  }))
}

afterEach(cleanup)

describe('isStale', () => {
  it('is stale only when both SHAs are known and differ', () => {
    expect(isStale('aaa1111', 'bbb2222')).toBe(true)
    expect(isStale('aaa1111', 'aaa1111')).toBe(false)
    expect(isStale(null, 'bbb2222')).toBe(false)
    expect(isStale('aaa1111', null)).toBe(false)
  })
})

describe('UpdateBanner', () => {
  it('offers a reload when the deployed frontend differs', async () => {
    deployed('bbb2222')
    render(<UpdateBanner bakedSha="aaa1111" />)
    expect(await screen.findByText(/new version/)).toBeTruthy()
  })

  it('stays hidden when the frontend is current', async () => {
    deployed('aaa1111')
    render(<UpdateBanner bakedSha="aaa1111" />)
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled())
    expect(screen.queryByText(/new version/)).toBeNull()
  })

  it('does not poll at all when nothing was baked in (dev, tests)', () => {
    deployed('bbb2222')
    render(<UpdateBanner bakedSha={null} />)
    expect(global.fetch).not.toHaveBeenCalled()
  })
})
