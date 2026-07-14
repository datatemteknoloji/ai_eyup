import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useBranding } from '../branding/BrandingContext'

const Login: React.FC = () => {
  const { login } = useAuth()
  const { appName, logoUrl, version } = useBranding()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
    } catch (err: any) {
      setError(err?.message || 'Giriş başarısız')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-cyber-deep flex flex-col items-center justify-start px-4 pt-[20vh] pb-8">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          {logoUrl ? (
            <img src={logoUrl} alt={appName} className="w-12 h-12 rounded-xl object-contain" />
          ) : (
            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center">
              <span className="text-white font-bold text-lg">DT</span>
            </div>
          )}
          <span className="text-white font-semibold text-xl">{appName}</span>
        </div>

        <form onSubmit={submit}
          className="bg-slate-800 border border-white/[0.06] rounded-2xl p-6 space-y-4 shadow-2xl">
          <h1 className="text-lg font-semibold text-white text-center">Giriş Yap</h1>

          {error && (
            <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-400 mb-1">Kullanıcı Adı</label>
            <input
              autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 outline-none"
              placeholder="admin"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">Parola</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:border-blue-500 outline-none"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-500 hover:to-blue-600 disabled:opacity-50 text-white font-medium rounded-lg py-2.5 text-sm transition-colors flex items-center justify-center gap-2"
          >
            {busy ? <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" /> Giriş yapılıyor...</> : 'Giriş Yap'}
          </button>
        </form>

        <p className="text-center text-xs text-slate-600 mt-4">
          {appName}{version ? ` v${version}` : ''} · © 2026
        </p>
      </div>
    </div>
  )
}

export default Login
