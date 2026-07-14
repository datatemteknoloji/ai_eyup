import React, { useEffect, useState } from 'react'
import { RefreshCw, Check, AlertTriangle } from 'lucide-react'
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

const fmtDur = (sec: number) => {
  if (sec < 60) return `${sec} sn`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m} dk ${s} sn`
  return `${Math.floor(m / 60)} sa ${m % 60} dk`
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
  const startedAtRef = React.useRef(Date.now())
  const onDoneRef = React.useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    startedAtRef.current = Date.now()
    setElapsedSec(0)
    const t = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [jobId])

  useEffect(() => {
    let cancelled = false
    let finished = false
    setJob({ id: jobId, status: 'running', percent: 1, message: 'İşlem başlıyor...' })

    const tick = async () => {
      if (finished || cancelled) return
      try {
        const r = await fetch(`${API_BASE_URL}/servers/bulk-jobs/${jobId}`)
        if (!r.ok || cancelled) return
        const j: BulkJob = await r.json()
        setJob(j)
        if (j.status === 'done' || j.status === 'error') {
          finished = true
          onDoneRef.current?.(j)
        }
      } catch {
        /* poll again */
      }
    }
    tick()
    const id = setInterval(tick, 1500)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [jobId])

  const pct = Math.max(0, Math.min(100, Number(job.percent) || 0))
  const done = job.status === 'done' || job.status === 'error'
  const etaSec =
    !done && pct >= 8 && elapsedSec >= 10
      ? Math.max(0, Math.round((elapsedSec / pct) * (100 - pct)))
      : null

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
                  : job.title || 'Toplu işlem sürüyor'}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5 truncate">
              {job.kind === 'ai_ready'
                ? 'Linux SSH AI Ready'
                : job.kind === 'win_ai_ready'
                  ? 'Windows WinRM AI Ready'
                  : job.kind === 'health_check'
                    ? 'Sunucu durum kontrolü'
                    : job.kind === 'os_refresh'
                      ? 'OS bilgisi yenileme'
                      : job.kind || 'bulk'}
            </p>
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
            Büyük ortamlarda bu işlem birkaç dakika sürebilir. Pencereyi kapatırsanız işlem arka planda
            devam eder.
          </p>
        )}
        {job.status === 'error' && job.error && (
          <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-4">
            {job.error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onDismiss}
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
