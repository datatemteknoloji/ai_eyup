import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useBranding } from '../branding/BrandingContext'
import { API_BASE_URL } from '../config/api'

type Step = 'credentials' | 'mfa' | 'enroll'

const Login: React.FC = () => {
  const { login, completeMfaLogin } = useAuth()
  const { appName, logoUrl, version } = useBranding()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<Step>('credentials')
  const [mfaToken, setMfaToken] = useState('')
  const [otpauthUrl, setOtpauthUrl] = useState('')
  const [secret, setSecret] = useState('')

  const finish = async () => {
    navigate('/', { replace: true })
  }

  const submitCreds = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const result = await login(username.trim(), password)
      if (result?.mfa_required) {
        setMfaToken(result.mfa_token)
        if (result.mfa_enrollment_required) {
          const r = await fetch(`${API_BASE_URL}/auth/mfa/enroll/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mfa_token: result.mfa_token }),
          })
          if (!r.ok) {
            const err = await r.json().catch(() => ({}))
            throw new Error(err.detail || 'MFA kayıt başlatılamadı')
          }
          const data = await r.json()
          setMfaToken(data.mfa_token || result.mfa_token)
          setOtpauthUrl(data.otpauth_url || '')
          setSecret(data.secret || '')
          setStep('enroll')
        } else {
          setStep('mfa')
        }
      } else {
        await finish()
      }
    } catch (err: any) {
      setError(err?.message || 'Giriş başarısız')
    } finally {
      setBusy(false)
    }
  }

  const submitMfa = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await completeMfaLogin(mfaToken, code.trim(), step === 'enroll')
      await finish()
    } catch (err: any) {
      setError(err?.message || 'MFA doğrulama başarısız')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-cyber-deep flex flex-col items-center justify-start px-4 pt-[20vh] pb-8">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-3 mb-8">
          {logoUrl ? (
            <img
              src={logoUrl}
              alt={appName}
              className="h-24 w-auto max-w-[280px] object-contain"
            />
          ) : (
            <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl flex items-center justify-center">
              <span className="text-white font-bold text-2xl">DT</span>
            </div>
          )}
          <span className="text-white font-semibold text-xl text-center leading-snug">{appName}</span>
        </div>

        {step === 'credentials' ? (
          <form onSubmit={submitCreds}
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
        ) : (
          <form onSubmit={submitMfa}
            className="bg-slate-800 border border-white/[0.06] rounded-2xl p-6 space-y-4 shadow-2xl">
            <h1 className="text-lg font-semibold text-white text-center">
              {step === 'enroll' ? 'MFA Kaydı' : 'MFA Doğrulama'}
            </h1>
            {step === 'enroll' && (
              <div className="text-xs text-slate-400 space-y-2">
                <p>Authenticator uygulamanıza şu secret’ı ekleyin:</p>
                <p className="font-mono text-amber-200 break-all bg-cyber-deep rounded-lg px-2 py-2">{secret}</p>
                {otpauthUrl && (
                  <p className="break-all text-slate-500">otpauth: {otpauthUrl}</p>
                )}
              </div>
            )}
            {error && (
              <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                {error}
              </div>
            )}
            <div>
              <label className="block text-xs text-slate-400 mb-1">6 haneli kod</label>
              <input
                autoFocus
                value={code}
                onChange={e => setCode(e.target.value)}
                className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm tracking-widest focus:border-blue-500 outline-none"
                placeholder="000000"
                inputMode="numeric"
              />
            </div>
            <button
              type="submit"
              disabled={busy || code.trim().length < 6}
              className="w-full bg-gradient-to-r from-blue-600 to-blue-700 disabled:opacity-50 text-white font-medium rounded-lg py-2.5 text-sm"
            >
              {busy ? 'Doğrulanıyor…' : 'Doğrula'}
            </button>
            <button
              type="button"
              onClick={() => { setStep('credentials'); setCode(''); setError('') }}
              className="w-full text-xs text-slate-400 hover:text-white"
            >
              Geri
            </button>
          </form>
        )}

        <p className="text-center text-xs text-slate-600 mt-4">
          {appName}{version ? ` v${version}` : ''} · © 2026
        </p>
      </div>
    </div>
  )
}

export default Login
