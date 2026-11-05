import { useEffect, useState } from 'react'
import { getHealth } from '../api'

// Fleet spec BLD-5: the bundle knows which frontend commit it was built from
// (baked in by vite.config.js); /health says which one is deployed. When they
// differ, this tab is running an old bundle, so offer a reload. Backend-only
// deploys don't change frontend_sha, so they never trigger it. Off in dev and
// tests, where nothing is baked in.
const CHECK_EVERY_MS = 15 * 60 * 1000

export function isStale(bakedSha, deployedSha) {
  return Boolean(bakedSha && deployedSha && bakedSha !== deployedSha)
}

export default function UpdateBanner({ bakedSha = __FRONTEND_SHA__ }) {
  const [stale, setStale] = useState(false)

  useEffect(() => {
    if (!bakedSha) return undefined
    const check = () =>
      getHealth()
        .then((health) => setStale(isStale(bakedSha, health.frontend_sha)))
        .catch(() => {}) // offline or mid-deploy: try again later
    const onVisible = () => {
      if (document.visibilityState === 'visible') check()
    }
    check()
    const timer = setInterval(check, CHECK_EVERY_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [bakedSha])

  if (!stale) return null
  return (
    <div className="flex items-center justify-center gap-3 bg-ink px-4 py-2 text-sm text-page">
      A new version of Pocket Money is available.
      <button
        onClick={() => window.location.reload()}
        className="rounded border border-page px-2 py-0.5 hover:opacity-80"
      >
        Reload
      </button>
    </div>
  )
}
