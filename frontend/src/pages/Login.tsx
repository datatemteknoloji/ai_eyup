import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Check, Lock, Moon, Share2, ShieldCheck, Sun } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useBranding } from '../branding/BrandingContext'
import { API_BASE_URL } from '../config/api'
import { useLocale } from '../i18n/LocaleProvider'
import { useTheme } from '../theme/ThemeProvider'
import type { Locale } from '../i18n/messages'
import LoginHub from '../components/login/LoginHub'
import './login.css'

type Step = 'credentials' | 'mfa' | 'enroll'
type Tab = 'ad' | 'local'
type LoginOptions = { ad_enabled: boolean; sso_enabled: boolean }

const OPTS_KEY = 'ainew_login_options'
const TAB_KEY = 'ainew_login_tab'
const NO_OPTIONS: LoginOptions = { ad_enabled: false, sso_enabled: false }

// SSO kodu tek kullanımlıktır; React StrictMode çift efektinde ikinci kez tüketilmesin.
const handledSsoCodes = new Set<string>()

function readOptions(): LoginOptions {
  try {
    const raw = JSON.parse(localStorage.getItem(OPTS_KEY) || 'null')
    if (raw && typeof raw === 'object') {
      return { ad_enabled: !!raw.ad_enabled, sso_enabled: !!raw.sso_enabled }
    }
  } catch {
    /* yok say */
  }
  return NO_OPTIONS
}

function readTab(): Tab {
  return localStorage.getItem(TAB_KEY) === 'local' ? 'local' : 'ad'
}

const Login: React.FC = () => {
  const { login, completeMfaLogin, completeSsoLogin } = useAuth()
  const { appName, logoUrl, version, companyName, tagline, footerText, heroTitle, heroText } = useBranding()
  const { t, locale, setLocale } = useLocale()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const [params] = useSearchParams()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState<Step>('credentials')
  const [mfaToken, setMfaToken] = useState('')
  const [otpauthUrl, setOtpauthUrl] = useState('')
  const [secret, setSecret] = useState('')
  const [options, setOptions] = useState<LoginOptions>(readOptions)
  const [tab, setTab] = useState<Tab>(readTab)
  const [ssoState, setSsoState] = useState<null | 'redirecting' | 'completing'>(null)

  // AD kapalıysa sekme yok: tek form (arka uç hesabın türüne göre kendisi karar verir).
  const activeTab: Tab = options.ad_enabled ? tab : 'local'

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE_URL}/public/login-options`)
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (cancelled || !data) return
        const next = { ad_enabled: !!data.ad_enabled, sso_enabled: !!data.sso_enabled }
        setOptions(next)
        localStorage.setItem(OPTS_KEY, JSON.stringify(next))
      })
      .catch(() => {
        /* son bilinen seçeneklerle devam */
      })
    return () => {
      cancelled = true
    }
  }, [])

  // IdP dönüşü: ?sso_code=… (tek kullanımlık) veya ?sso_error=…
  useEffect(() => {
    const ssoCode = params.get('sso_code')
    const ssoError = params.get('sso_error')
    if (!ssoCode && !ssoError) return
    window.history.replaceState(null, '', window.location.pathname)
    if (ssoError) {
      setError(`${t('login_sso_failed')}: ${ssoError.slice(0, 200)}`)
      return
    }
    if (!ssoCode || handledSsoCodes.has(ssoCode)) return
    handledSsoCodes.add(ssoCode)
    setSsoState('completing')
    completeSsoLogin(ssoCode)
      .then(() => navigate('/', { replace: true }))
      .catch((err: any) => {
        setError(err?.message || t('login_sso_failed'))
        setSsoState(null)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- yalnızca ilk yüklemede
  }, [])

  // Tarayıcı "geri" ile döndüğünde (bfcache) yönlendirme durumu takılı kalmasın.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) setSsoState(null)
    }
    window.addEventListener('pageshow', onShow)
    return () => window.removeEventListener('pageshow', onShow)
  }, [])

  const chooseTab = (next: Tab) => {
    setTab(next)
    localStorage.setItem(TAB_KEY, next)
    setError('')
  }

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
            throw new Error(err.detail || t('login_mfa_start_failed'))
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
      setError(err?.message || t('login_failed'))
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
      setError(err?.message || t('login_mfa_failed'))
    } finally {
      setBusy(false)
    }
  }

  const startSso = () => {
    setError('')
    setSsoState('redirecting')
    window.location.assign(`${API_BASE_URL}/auth/sso/start`)
  }

  const onTabKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      chooseTab(activeTab === 'ad' ? 'local' : 'ad')
    }
  }

  const company = companyName || t('login_default_company')
  const footer = footerText || t('login_default_footer', { year: new Date().getFullYear() })
  const secure = typeof window !== 'undefined' && window.location.protocol === 'https:'

  const brand = (
    <div className="lg-brand">
      {logoUrl ? (
        <img className="lg-brand-logo" src={logoUrl} alt={appName} />
      ) : (
        <span className="lg-brand-mark" aria-hidden="true">
          <Share2 size={18} strokeWidth={2.2} />
        </span>
      )}
      <span className="lg-brand-text">
        <span className="lg-brand-name">{appName}</span>
        <span className="lg-brand-company">{company}</span>
      </span>
    </div>
  )

  const errorBox = error ? (
    <div className="lg-error" role="alert">
      {error}
    </div>
  ) : null

  return (
    <div className="lg-root">
      <aside className="lg-hero">
        {brand}
        <div className="lg-hero-body">
          <p className="lg-eyebrow">{tagline || t('login_eyebrow')}</p>
          <h2 className="lg-title">{heroTitle || t('login_hero_title')}</h2>
          <p className="lg-lead">{heroText || t('login_hero_text')}</p>
        </div>
        <LoginHub appName={appName} logoUrl={logoUrl} ariaLabel={t('login_hub_aria')} />
        <ul className="lg-features">
          {(['login_feat_capacity', 'login_feat_health', 'login_feat_ai'] as const).map(k => (
            <li key={k}>
              <Check size={14} strokeWidth={2.5} aria-hidden="true" />
              {t(k)}
            </li>
          ))}
        </ul>
      </aside>

      <main className="lg-main">
        <div className="lg-toolbar">
          <select
            className="lg-ctl lg-select"
            value={locale}
            onChange={e => setLocale(e.target.value as Locale)}
            aria-label={t('language')}
          >
            <option value="tr">{t('language_tr')}</option>
            <option value="en">{t('language_en')}</option>
          </select>
          <button
            type="button"
            className="lg-ctl lg-icon-btn"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? t('login_theme_to_light') : t('login_theme_to_dark')}
            title={theme === 'dark' ? t('login_theme_to_light') : t('login_theme_to_dark')}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>

        <div className="lg-center">
          <div className="lg-card">
            <div className="lg-mobile-brand">{brand}</div>

            {ssoState ? (
              <div className="lg-fullstate" role="status">
                <span className="lg-spin" />
                {ssoState === 'completing' ? t('login_sso_completing') : t('login_sso_redirecting')}
              </div>
            ) : step === 'credentials' ? (
              <form onSubmit={submitCreds} noValidate>
                <h1>{t('login_form_title')}</h1>
                <p className="lg-sub">
                  {options.ad_enabled ? t('login_form_sub') : t('login_form_sub_local')}
                </p>

                {options.ad_enabled && (
                  <div className="lg-seg" role="tablist" onKeyDown={onTabKey}>
                    {(['ad', 'local'] as const).map(k => (
                      <button
                        key={k}
                        type="button"
                        role="tab"
                        className="lg-tab"
                        aria-selected={activeTab === k}
                        tabIndex={activeTab === k ? 0 : -1}
                        onClick={() => chooseTab(k)}
                      >
                        {k === 'ad' ? t('login_tab_ad') : t('login_tab_local')}
                      </button>
                    ))}
                  </div>
                )}

                {errorBox}

                <div className="lg-field">
                  <label className="lg-label" htmlFor="lg-user">
                    {t('login_username')}
                  </label>
                  <input
                    id="lg-user"
                    className="lg-input"
                    autoFocus
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder={activeTab === 'ad' && options.ad_enabled ? t('login_username_ph_ad') : t('login_username_ph_local')}
                  />
                </div>

                <div className="lg-field">
                  <label className="lg-label" htmlFor="lg-pass">
                    {t('login_password')}
                  </label>
                  <div className="lg-input-wrap">
                    <input
                      id="lg-pass"
                      className="lg-input has-reveal"
                      type={showPw ? 'text' : 'password'}
                      autoComplete="current-password"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                    />
                    <button
                      type="button"
                      className="lg-reveal"
                      onClick={() => setShowPw(v => !v)}
                      aria-pressed={showPw}
                    >
                      {showPw ? t('login_password_hide') : t('login_password_show')}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  className="lg-btn lg-btn-primary"
                  disabled={busy || !username || !password}
                >
                  {busy ? (
                    <>
                      <span className="lg-spin" /> {t('login_submitting')}
                    </>
                  ) : (
                    t('login_submit_cta')
                  )}
                </button>

                {options.sso_enabled && (
                  <>
                    <div className="lg-divider" aria-hidden="true">
                      {t('login_or')}
                    </div>
                    <button type="button" className="lg-btn lg-btn-outline" onClick={startSso}>
                      <Lock size={15} aria-hidden="true" />
                      {t('login_sso')}
                    </button>
                  </>
                )}

                <p className="lg-note">
                  <ShieldCheck size={15} aria-hidden="true" />
                  <span>{secure ? t('login_note_secure') : t('login_note_audit')}</span>
                </p>
              </form>
            ) : (
              <form onSubmit={submitMfa} noValidate>
                <h1>{step === 'enroll' ? t('login_mfa_enroll') : t('login_mfa_verify')}</h1>
                <p className="lg-sub">
                  {step === 'enroll' ? t('login_mfa_enroll_sub') : t('login_mfa_sub')}
                </p>
                {step === 'enroll' && (
                  <div>
                    <p className="lg-hint">{t('login_mfa_secret_hint')}</p>
                    <p className="lg-secret">{secret}</p>
                    {otpauthUrl && (
                      <p className="lg-hint lg-mono" style={{ wordBreak: 'break-all' }}>
                        otpauth: {otpauthUrl}
                      </p>
                    )}
                  </div>
                )}
                {errorBox}
                <div className="lg-field">
                  <label className="lg-label" htmlFor="lg-code">
                    {t('login_mfa_code')}
                  </label>
                  <input
                    id="lg-code"
                    className="lg-input is-code"
                    autoFocus
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    maxLength={8}
                    value={code}
                    onChange={e => setCode(e.target.value)}
                    placeholder="000000"
                  />
                </div>
                <button
                  type="submit"
                  className="lg-btn lg-btn-primary"
                  disabled={busy || code.trim().length < 6}
                >
                  {busy ? t('login_mfa_verifying') : t('login_mfa_confirm')}
                </button>
                <button
                  type="button"
                  className="lg-link"
                  onClick={() => {
                    setStep('credentials')
                    setCode('')
                    setError('')
                  }}
                >
                  {t('login_back')}
                </button>
              </form>
            )}
          </div>
        </div>

        <footer className="lg-footer">
          <span className="lg-mono">
            {appName}
            {version ? ` v${version}` : ''}
          </span>
          <span>{footer}</span>
        </footer>
      </main>
    </div>
  )
}

export default Login
