/**
 * Level 1 shell — Dropt Ops under ainew design tokens.
 */
import { useEffect, useState, ReactNode } from 'react'
import { API_BASE_URL } from '../../config/api'
import { getToken as getAinewToken } from '../../auth/authStore'
import { saveSession } from '@dropt/session'
import { TooltipProvider } from '@dropt/components/ui/tooltip'
import { I18nProvider } from '@dropt/i18n/I18nProvider'
import { AssistantFab } from '@dropt/components/AssistantFab'
import './level1-theme.css'

function authHeaders(): HeadersInit {
  const token = getAinewToken() || ''
  return {
    Authorization: token ? `Bearer ${token}` : '',
    'Content-Type': 'application/json',
  }
}

export async function ensureDroptSession(): Promise<string> {
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
  saveSession(access, JSON.stringify({
    username: data.dropt_username,
    role: data.dropt_role,
  }))
  return access
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
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const tok = await ensureDroptSession()
        try {
          await syncAssistantFromAinew(tok)
        } catch {
          /* asistan sync opsiyonel — FAB yine görünür */
        }
        if (!cancelled) setReady(true)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => { cancelled = true }
  }, [])

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-6 text-red-300">
        <p className="font-semibold mb-2 text-white">Level 1 / Dropt bağlantı hatası</p>
        <p className="text-sm text-slate-400 whitespace-pre-wrap">{error}</p>
        <button
          type="button"
          className="mt-4 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
          onClick={() => window.location.reload()}
        >
          Yeniden dene
        </button>
      </div>
    )
  }
  if (!ready) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-slate-400 text-sm gap-3">
        <span className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
        Dropt oturumu hazırlanıyor…
      </div>
    )
  }

  return (
    <div className="level1-dropt-root level1-fill -m-4 md:-m-6 p-4 md:p-6 min-h-0">
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
