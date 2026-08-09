import { useEffect } from 'react'
import { API_BASE_URL } from '../../config/api'
import { getToken as getAinewToken } from '../../auth/authStore'
import { Level1Shell, ensureDroptSession } from './Level1Shell'
import { ServersPage } from '@dropt/pages/ServersPage'
import { I18nProvider } from '@dropt/i18n/I18nProvider'

function ainewAuthHeaders(): HeadersInit {
  const token = getAinewToken() || ''
  return { Authorization: token ? `Bearer ${token}` : '', 'Content-Type': 'application/json' }
}

const SYNC_STALE_MS = 5 * 60 * 1000
const SYNC_AT_KEY = 'level1_dropt_sync_at'

/**
 * Operasyon Merkezi — Dropt ServersPage + stale envanter senkronu (async, remount yok).
 */
export default function Level1OpsCenter() {
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const last = Number(localStorage.getItem(SYNC_AT_KEY) || 0)
        if (Date.now() - last < SYNC_STALE_MS) return
        const droptToken = await ensureDroptSession()
        if (cancelled) return
        const res = await fetch(`${API_BASE_URL}/level1/servers/sync-all?background=true`, {
          method: 'POST',
          headers: ainewAuthHeaders(),
          body: JSON.stringify({ dropt_token: droptToken }),
        })
        if (!res.ok) throw new Error(await res.text())
        if (!cancelled) localStorage.setItem(SYNC_AT_KEY, String(Date.now()))
      } catch {
        /* senkron arka planda; liste yine Dropt’tan yüklenir */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Level1Shell>
      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
        <div className="flex-1 min-h-0 overflow-auto p-4 md:p-5">
          <I18nProvider>
            <ServersPage level1Mode />
          </I18nProvider>
        </div>
      </div>
    </Level1Shell>
  )
}
