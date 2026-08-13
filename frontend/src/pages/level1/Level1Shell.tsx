/**
 * Level 1 shell — Dropt Ops under ainew design tokens.
 *
 * Wave 1 (latency): Dropt token cache + soft open (UI block yok) +
 * asistan sync fire-and-forget.
 */
import { useEffect, useState, ReactNode } from 'react'
import { API_BASE_URL } from '../../config/api'
import { getToken as getAinewToken } from '../../auth/authStore'
import { getToken as getDroptToken, saveSession } from '@dropt/session'
import { TooltipProvider } from '@dropt/components/ui/tooltip'
import { I18nProvider } from '@dropt/i18n/I18nProvider'
import { AssistantFab } from '@dropt/components/AssistantFab'
import './level1-theme.css'

const DROPT_EXPIRES_KEY = 'dtt_token_expires_at'
/** Yenilemeyi JWT bitişinden bu kadar önce yap */
const CACHE_SKEW_MS = 60_000

let inflightSession: Promise<string> | null = null

function authHeaders(): HeadersInit {
  const token = getAinewToken() || ''
  return {
    Authorization: token ? `Bearer ${token}` : '',
    'Content-Type': 'application/json',
  }
}

function jwtExpMs(token: string): number | null {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = JSON.parse(atob(b64)) as { exp?: number }
    return typeof json.exp === 'number' ? json.exp * 1000 : null
  } catch {
    return null
  }
}

function cachedDroptTokenValid(): string | null {
  const token = getDroptToken()
  if (!token) return null
  const jwtExp = jwtExpMs(token)
  const storedExp = Number(localStorage.getItem(DROPT_EXPIRES_KEY) || 0)
  const exp = jwtExp || (storedExp > 0 ? storedExp : 0)
  if (!exp) return null
  if (exp - Date.now() > CACHE_SKEW_MS) return token
  return null
}

/**
 * Dropt portal token — cache + in-flight dedupe.
 * `force: true` ile bridge'i yeniden çağırır.
 */
export async function ensureDroptSession(opts?: { force?: boolean }): Promise<string> {
  if (!opts?.force) {
    const cached = cachedDroptTokenValid()
    if (cached) return cached
  }
  if (inflightSession) return inflightSession

  inflightSession = (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/level1/dropt-session`, {
        method: 'POST',
        headers: authHeaders(),
      })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || 'Dropt oturumu açılamadı')
      }
      const data = await res.json()
      const access = data.access_token as string
      const mins = Number(data.expires_in_minutes) || 480
      localStorage.setItem(DROPT_EXPIRES_KEY, String(Date.now() + mins * 60_000))
      saveSession(
        access,
        JSON.stringify({
          username: data.dropt_username,
          role: data.dropt_role,
        }),
      )
      return access
    } finally {
      inflightSession = null
    }
  })()

  return inflightSession
}

/** Sync ainew AI Ayarları → Dropt assistant (model/gateway). Best-effort. */
export async function syncAssistantFromAinew(droptToken: string): Promise<void> {
  await fetch(`${API_BASE_URL}/level1/sync-assistant-llm`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ dropt_token: droptToken }),
  })
}

export function Level1Shell({
  children,
  title,
  subtitle,
}: {
  children: ReactNode
  title?: string
  subtitle?: string
}) {
  const [sessionError, setSessionError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const tok = await ensureDroptSession()
        if (cancelled) return
        setSessionError(null)
        // Fire-and-forget — UI'yi bekletme
        void syncAssistantFromAinew(tok).catch(() => {
          /* asistan sync opsiyonel */
        })
      } catch (e) {
        if (!cancelled) setSessionError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="level1-dropt-root level1-fill -m-4 md:-m-6 p-4 md:p-6 min-h-0">
      {sessionError ? (
        <div className="mb-4 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-amber-100 shrink-0">
          <p className="text-sm font-medium text-white">Dropt oturumu henüz hazır değil</p>
          <p className="mt-1 text-xs text-slate-400 whitespace-pre-wrap">{sessionError}</p>
          <button
            type="button"
            className="mt-2 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
            onClick={() => {
              setSessionError(null)
              void ensureDroptSession({ force: true })
                .then((tok) => {
                  void syncAssistantFromAinew(tok).catch(() => {})
                })
                .catch((e) => {
                  setSessionError(e instanceof Error ? e.message : String(e))
                })
            }}
          >
            Yeniden dene
          </button>
        </div>
      ) : null}
      <TooltipProvider>
        {(title || subtitle) ? (
          <header className="mb-4 shrink-0 level1-page-header">
            {title ? (
              <h1 className="text-xl font-semibold tracking-tight" style={{ color: 'var(--text-primary)' }}>{title}</h1>
            ) : null}
            {subtitle ? (
              <p className="mt-1 text-sm leading-relaxed max-w-3xl" style={{ color: 'var(--text-secondary)' }}>{subtitle}</p>
            ) : null}
          </header>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col level1-page-body">{children}</div>
        <I18nProvider>
          <AssistantFab />
        </I18nProvider>
      </TooltipProvider>
    </div>
  )
}
