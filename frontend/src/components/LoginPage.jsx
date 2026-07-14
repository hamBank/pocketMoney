import { useEffect, useRef, useState } from 'react'
import { loginWithGoogle, setToken } from '../api'

const GSI_SRC = 'https://accounts.google.com/gsi/client'

export default function LoginPage({ config, onSignedIn }) {
  const buttonRef = useRef(null)
  const [error, setError] = useState(
    config.google_client_id ? null : 'GOOGLE_CLIENT_ID is not configured',
  )

  useEffect(() => {
    if (!config.google_client_id) return undefined

    const script = document.createElement('script')
    script.src = GSI_SRC
    script.async = true
    script.onload = () => {
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          try {
            const { token, user } = await loginWithGoogle(credential)
            setToken(token)
            onSignedIn(user)
          } catch (e) {
            setError(e.message)
          }
        },
      })
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: 'outline',
        size: 'large',
      })
    }
    document.body.appendChild(script)
    return () => script.remove()
  }, [config, onSignedIn])

  return (
    <div className="flex min-h-screen items-center justify-center bg-page">
      <div className="flex flex-col items-center gap-4 rounded-xl bg-card p-10 shadow">
        <h1 className="text-2xl font-bold text-ink">Pocket Money</h1>
        <p className="text-sm text-ink-muted">Sign in with your family Google account</p>
        <div ref={buttonRef} />
        {error && <p className="max-w-xs text-center text-sm text-red-600">{error}</p>}
      </div>
    </div>
  )
}
