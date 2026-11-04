import { cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ApprovalQueue from './components/ApprovalQueue'
import ChoreList from './components/ChoreList'
import ChoreManager from './components/ChoreManager'
import ClaimHistory from './components/ClaimHistory'
import UserManager from './components/UserManager'

// Regression test for the "Manage chores" blank-page bug: a component whose
// mount effect is `useEffect(refresh, [])` where refresh returns a Promise
// has that Promise called as a cleanup function on unmount. React throws
// (it's not a function), and since nothing catches it, the whole tree
// unmounts blank. Switching tabs is exactly what unmounts these components,
// so every one of them must survive a mount + unmount cycle.
const TAB_COMPONENTS = [
  ['ChoreList', ChoreList],
  ['ChoreManager', ChoreManager],
  ['UserManager', UserManager],
  ['ApprovalQueue', ApprovalQueue],
  ['ClaimHistory', ClaimHistory],
]

beforeEach(() => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => [],
    headers: { get: (name) => (name === 'X-Total-Count' ? '0' : null) },
  }))
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe.each(TAB_COMPONENTS)('%s', (name, Component) => {
  it('mounts and unmounts without throwing', async () => {
    const { unmount } = render(<Component symbol="$" onChanged={() => {}} />)
    // Let the mount-time fetch (and its .then) resolve before we unmount,
    // same as a user switching tabs after data has loaded.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(() => unmount()).not.toThrow()
  })
})
