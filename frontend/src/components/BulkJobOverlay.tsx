import React, { useEffect, useState } from 'react'
import { RefreshCw, Check, AlertTriangle, Maximize2 } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

export interface BulkJob {
  id: string
  kind?: string
  title?: string
  status?: string
  percent?: number
  message?: string
  done?: number
  total?: number
  ok_count?: number
  fail_count?: number
  error?: string
  result?: Record<string, unknown>
}

const STORAGE_JOB = 'ainew.bulkJobId'
const STORAGE_MIN = 'ainew.bulkJobMinimized'

const fmtDur = (sec: number) => {
  if (sec < 60) return `${sec} sn`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m} dk ${s} sn`
  return `${Math.floor(m / 60)} sa ${m % 60} dk`
}

const kindLabel = (kind?: string) =>
  kind === 'ai_ready'
    ? 'Linux SSH AI Ready'
    : kind === 'win_ai_ready'
      ? 'Windows WinRM AI Ready'
      : kind === 'health_check'
        ? 'Sunucu durum kontrolü'
        : kind === 'dropt_sync_all'
          ? 'Level 1 envanter senkronu'
          : kind === 'os_refresh'
            ? 'OS bilgisi yenileme'
            : kind?.startsWith('events_scan_')
              ? 'Log / event taraması'
              : kind || 'bulk'

/** Sayfa yenileme / navigasyonda — yalnızca bu sekmede kullanıcı başlatmış işi geri yükle.
 *  Credential apply / auto-onboarding gibi arka plan turları modal açmaz. */
export async function restoreActiveBulkJobId(): Promise<string | null> {
  const saved = sessionStorage.getItem(STORAGE_JOB)
  if (!saved) return null
  try {
    const r = await fetch(`${API_BASE_URL}/servers/bulk-jobs/${saved}`)
    if (r.ok) {
      const j: BulkJob = await r.json()
      if (j.status === 'running' || j.status === 'done' || j.status === 'error' || j.status === 'cancelled') {
        return saved
      }
    }
  } catch {
    /* fall through */
  }
  sessionStorage.removeItem(STORAGE_JOB)
  sessionStorage.removeItem(STORAGE_MIN)
  return null
}

/** Kullanıcı manuel tetiklediğinde: tam ekran modal açılsın */
export function beginBulkJobModal(jobId: string) {
  sessionStorage.removeItem(STORAGE_MIN)
  sessionStorage.setItem(STORAGE_JOB, jobId)
}

export function persistBulkJobId(jobId: string | null) {
  if (jobId) sessionStorage.setItem(STORAGE_JOB, jobId)
  else {
    sessionStorage.removeItem(STORAGE_JOB)
    sessionStorage.removeItem(STORAGE_MIN)
  }
}

/** vCenter tarama ekranı ile aynı stil — toplu AI Ready / health / OS işleri */
export const BulkJobOverlay: React.FC<{
  jobId: string
  onDone?: (job: BulkJob) => void
  onDismiss: () => void
}> = ({ jobId, onDone, onDismiss }) => {
  const [job, setJob] = useState<BulkJob>({
    id: jobId,
    status: 'running',
    percent: 1,
    message: 'İşlem başlıyor...',
  })
  const [elapsedSec, setElapsedSec] = useState(0)
  const [cancelling, setCancelling] = useState(false)
  const [minimized, setMinimized] = useState(
    () => sessionStorage.getItem(STORAGE_MIN) === jobId
  )
  const startedAtRef = React.useRef(Date.now())
  const onDoneRef = React.useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    startedAtRef.current = Date.now()
    setElapsedSec(0)
    setMinimized(sessionStorage.getItem(STORAGE_MIN) === jobId)
    const t = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [jobId])

  useEffect(() => {
    let cancelled = false
    let finished = false
    let delay = 1500
    let timer: ReturnType<typeof setTimeout> | undefined
    setJob({ id: jobId, status: 'running', percent: 1, message: 'İşlem başlıyor...' })

    const tick = async () => {
      if (finished || cancelled) return
      try {
        const r = await fetch(`${API_BASE_URL}/servers/bulk-jobs/${jobId}`)
        if (!r.ok || cancelled) return
        const j: BulkJob = await r.json()
        setJob(j)
        if (j.status === 'done' || j.status === 'error' || j.status === 'cancelled') {
          finished = true
          onDoneRef.current?.(j)
          return
        }
      } catch {
        /* poll again */
      }
      if (!finished && !cancelled) {
        delay = Math.min(delay + 500, 5000)
        timer = setTimeout(() => { void tick() }, delay)
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  const goBackground = () => {
    sessionStorage.setItem(STORAGE_MIN, jobId)
    setMinimized(true)
  }

  const reopen = () => {
    sessionStorage.removeItem(STORAGE_MIN)
    setMinimized(false)
  }

  const closeFully = () => {
    sessionStorage.removeItem(STORAGE_MIN)
    sessionStorage.removeItem(STORAGE_JOB)
    onDismiss()
  }

  const pct = Math.max(0, Math.min(100, Number(job.percent) || 0))
  const done = job.status === 'done' || job.status === 'error' || job.status === 'cancelled'
  const etaSec =
    !done && pct >= 5 && elapsedSec >= 5
      ? Math.max(0, Math.round((elapsedSec / pct) * (100 - pct)))
      : null

  const requestCancel = async () => {
    if (cancelling || job.status !== 'running') return
    setCancelling(true)
    try {
      await fetch(`${API_BASE_URL}/servers/bulk-jobs/${jobId}/cancel`, { method: 'POST' })
    } catch {
      /* poll will refresh */
    } finally {
      setCancelling(false)
    }
  }

  if (minimized) {
    return (
      <div className="fixed bottom-4 right-4 z-[60] max-w-sm w-[min(100vw-2rem,22rem)]">
        <button
          type="button"
          onClick={reopen}
          className="w-full text-left bg-slate-800/95 backdrop-blur border border-slate-600 rounded-xl shadow-2xl shadow-black/50 p-3 hover:border-blue-500/50 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div
              className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                job.status === 'error'
                  ? 'bg-red-500/15'
                  : job.status === 'done'
                    ? 'bg-green-500/15'
                    : 'bg-blue-500/15'
              }`}
            >
              {job.status === 'error' ? (
                <AlertTriangle className="w-4 h-4 text-red-400" />
              ) : job.status === 'done' ? (
                <Check className="w-4 h-4 text-green-400" />
              ) : (
                <RefreshCw className="w-4 h-4 text-blue-400 animate-spin" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm text-white font-medium truncate">
                {done
                  ? job.status === 'error'
                    ? 'İşlem hatası'
                    : job.status === 'cancelled'
                      ? 'İşlem iptal edildi'
                      : 'İşlem tamamlandı'
                  : job.title || 'Toplu işlem sürüyor'}
              </div>
              <div className="text-[11px] text-slate-400 truncate mt-0.5">
                {done ? kindLabel(job.kind) : `${pct}% · ${job.message || 'İşleniyor...'}`}
              </div>
            </div>
            <Maximize2 className="w-4 h-4 text-slate-400 flex-shrink-0" />
          </div>
          {!done && (
            <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden mt-2.5">
              <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${pct || 3}%` }} />
            </div>
          )}
        </button>
        {done ? (
          <div className="flex justify-end mt-1.5">
            <button
              type="button"
              onClick={closeFully}
              className="text-[11px] px-2.5 py-1 rounded-lg text-slate-400 hover:text-white bg-slate-800/80 border border-slate-700"
            >
              Kapat
            </button>
          </div>
        ) : (
          <p className="text-[10px] text-slate-500 mt-1.5 pl-1">
            Tıklayarak ilerleme ekranını tekrar açın
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.08] w-full max-w-lg shadow-2xl p-6">
        <div className="flex items-start gap-4 mb-5">
          <div
            className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 ${
              job.status === 'error'
                ? 'bg-red-500/15'
                : job.status === 'done'
                  ? 'bg-green-500/15'
                  : 'bg-blue-500/15'
            }`}
          >
            {job.status === 'error' ? (
              <AlertTriangle className="w-6 h-6 text-red-400" />
            ) : job.status === 'done' ? (
              <Check className="w-6 h-6 text-green-400" />
            ) : (
              <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-white">
              {job.status === 'done'
                ? 'İşlem tamamlandı'
                : job.status === 'error'
                  ? 'İşlem hatası'
                  : job.status === 'cancelled'
                    ? 'İşlem iptal edildi'
                    : job.title || 'Toplu işlem sürüyor'}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5 truncate">{kindLabel(job.kind)}</p>
          </div>
        </div>

        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span className="truncate pr-2">{job.message || 'İşleniyor...'}</span>
            <span className="font-mono text-slate-300 flex-shrink-0">{pct}%</span>
          </div>
          <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                job.status === 'error'
                  ? 'bg-red-500'
                  : job.status === 'done'
                    ? 'bg-green-500'
                    : 'bg-blue-500'
              }`}
              style={{ width: `${pct || 3}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-5">
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">İlerleme</div>
            <div className="text-sm text-white font-medium mt-0.5">
              {job.total != null && job.total > 0
                ? `${job.done ?? 0} / ${job.total}`
                : '—'}
            </div>
          </div>
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Geçen süre</div>
            <div className="text-sm text-white font-medium mt-0.5">{fmtDur(elapsedSec)}</div>
          </div>
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Tahmini kalan</div>
            <div className="text-sm text-white font-medium mt-0.5">
              {done ? '—' : etaSec != null ? `~${fmtDur(etaSec)}` : 'hesaplanıyor…'}
            </div>
          </div>
        </div>

        {(Number(job.ok_count) > 0 || Number(job.fail_count) > 0) && (
          <p className="text-[11px] text-slate-500 mb-3">
            Başarılı: {job.ok_count ?? 0}
            {Number(job.fail_count) > 0 ? ` · Başarısız: ${job.fail_count}` : ''}
          </p>
        )}

        {!done && (
          <p className="text-xs text-slate-500 mb-4 leading-relaxed">
            Bu kontrol SSH değil, TCP port taramasıdır. Büyük ortamlarda birkaç dakika sürebilir.
            “Arka planda devam et” ile küçültebilir; “İptal” ile durdurabilirsiniz.
          </p>
        )}
        {job.status === 'error' && job.error && (
          <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-4">
            {job.error}
          </p>
        )}
        {job.status === 'cancelled' && (
          <p className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 mb-4">
            {job.message || 'İşlem kullanıcı tarafından iptal edildi.'}
          </p>
        )}

        <div className="flex justify-end gap-2">
          {!done && (
            <button
              type="button"
              onClick={() => { void requestCancel() }}
              disabled={cancelling}
              className="px-4 py-2 rounded-lg text-sm text-red-200 bg-red-500/15 hover:bg-red-500/25 border border-red-500/40 disabled:opacity-50"
            >
              {cancelling ? 'İptal…' : 'İptal'}
            </button>
          )}
          <button
            type="button"
            onClick={done ? closeFully : goBackground}
            className="px-4 py-2 rounded-lg text-sm text-slate-300 bg-white/[0.07] hover:bg-slate-600 border border-slate-600"
          >
            {done ? 'Kapat' : 'Arka planda devam et'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default BulkJobOverlay
