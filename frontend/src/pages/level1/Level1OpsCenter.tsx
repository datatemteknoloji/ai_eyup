import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { getToken as getAinewToken } from '../../auth/authStore'
import { Level1Shell, withDroptToken } from './Level1Shell'
import { ServersPage } from '@dropt/pages/ServersPage'
import { I18nProvider } from '@dropt/i18n/I18nProvider'
import BulkJobOverlay, { beginBulkJobModal } from '../../components/BulkJobOverlay'

function ainewAuthHeaders(): HeadersInit {
  const token = getAinewToken() || ''
  return { Authorization: token ? `Bearer ${token}` : '', 'Content-Type': 'application/json' }
}

const SYNC_STALE_MS = 5 * 60 * 1000
const SYNC_AT_KEY = 'level1_dropt_sync_at'

function syncErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && typeof (detail as { message?: string }).message === 'string') {
    return (detail as { message: string }).message
  }
  return fallback
}

/**
 * Operasyon Merkezi — Dropt ServersPage + ainew envanter senkronu (buton + stale auto).
 */
export default function Level1OpsCenter() {
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)
  const [listKey, setListKey] = useState(0)

  const runSync = useCallback(async (opts?: { silent?: boolean; background?: boolean }) => {
    const silent = Boolean(opts?.silent)
    const background = opts?.background !== false
    if (!silent) {
      setSyncing(true)
      setSyncError(null)
      setSyncMsg(null)
    }
    try {
      const data = await withDroptToken(async (droptToken) => {
        const res = await fetch(
          `${API_BASE_URL}/level1/servers/sync-all?background=${background ? 'true' : 'false'}`,
          {
            method: 'POST',
            headers: ainewAuthHeaders(),
            body: JSON.stringify({ dropt_token: droptToken }),
          },
        )
        const text = await res.text()
        let parsed: Record<string, unknown> = {}
        try {
          parsed = text ? JSON.parse(text) : {}
        } catch {
          parsed = {}
        }
        if (!res.ok) {
          throw new Error(syncErrorMessage(parsed, text.slice(0, 300) || `HTTP ${res.status}`))
        }
        return parsed
      })
      localStorage.setItem(SYNC_AT_KEY, String(Date.now()))
      const jobId = typeof data.job_id === 'string' ? data.job_id : null
      if (jobId) {
        if (!silent) {
          beginBulkJobModal(jobId)
          setBulkJobId(jobId)
          setSyncMsg('Envanter senkronu arka planda başladı…')
        }
      } else if (!silent) {
        const ensured = Number(data.ensured ?? 0)
        const created = Number(data.created ?? 0)
        const errors = Array.isArray(data.errors) ? data.errors : []
        setSyncMsg(
          `Senkron tamam: ${ensured} eşlendi, ${created} yeni` +
            (errors.length ? ` (${errors.length} uyarı)` : ''),
        )
        if (errors.length) {
          setSyncError(String(errors[0]))
        }
        setListKey((k) => k + 1)
      }
    } catch (e) {
      if (!silent) {
        setSyncError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      if (!silent) setSyncing(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const last = Number(localStorage.getItem(SYNC_AT_KEY) || 0)
        if (Date.now() - last < SYNC_STALE_MS) return
        if (cancelled) return
        await runSync({ silent: true, background: true })
      } catch {
        /* sessiz auto-sync */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runSync])

  return (
    <Level1Shell>
      {bulkJobId && (
        <BulkJobOverlay
          jobId={bulkJobId}
          onDone={() => {
            setListKey((k) => k + 1)
            setSyncMsg('Envanter senkronu tamamlandı — liste yenilendi.')
            setSyncError(null)
          }}
          onDismiss={() => {
            setBulkJobId(null)
            setListKey((k) => k + 1)
          }}
        />
      )}
      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
        <div className="shrink-0 flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-4 py-2.5">
          <button
            type="button"
            disabled={syncing || !!bulkJobId}
            onClick={() => void runSync({ silent: false, background: true })}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
              bg-blue-600/90 hover:bg-blue-500 text-white border border-blue-500/40
              disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Ainew Linux envanterini Level 1 (Dropt) listesine yazar"
          >
            <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Senkronize ediliyor…' : 'Envanteri senkronize et'}
          </button>
          <span className="text-[11px] text-slate-500 max-w-xl leading-snug">
            ainew&apos;de AI Ready + RHEL/Oracle Linux olanları aktarır; Exadata bağlı sunucular hariç (SSH yeniden denenmez).
          </span>
          {syncMsg && !syncError && (
            <span className="text-xs text-emerald-400/90 ml-auto">{syncMsg}</span>
          )}
          {syncError && (
            <span className="text-xs text-amber-400/95 ml-auto max-w-md truncate" title={syncError}>
              {syncError}
            </span>
          )}
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-4 md:p-5">
          <I18nProvider>
            <ServersPage
              key={listKey}
              level1Mode
              onSyncAinewInventory={() => void runSync({ silent: false, background: true })}
              syncingAinewInventory={syncing || !!bulkJobId}
            />
          </I18nProvider>
        </div>
      </div>
    </Level1Shell>
  )
}
