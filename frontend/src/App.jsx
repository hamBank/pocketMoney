import { useEffect, useState } from 'react'

export default function App() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100">
      <div className="rounded-xl bg-white p-8 shadow">
        <h1 className="text-2xl font-bold text-slate-800">Pocket Money</h1>
        <p className="mt-2 text-sm text-slate-500">
          Backend: {health ? health.status : 'checking…'}
        </p>
      </div>
    </div>
  )
}
