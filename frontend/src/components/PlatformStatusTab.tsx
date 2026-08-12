import React, { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw, RotateCcw, Square } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

interface PlatformContainer {
  name: string
  group: string
  role: string
  critical: boolean
  present: boolean
  status: string
  health: string | null
  state: string | null
  image: string | null
  id: string | null
  started_at: string | null
  ports: { private?: number; public?: number; type?: string; ip?: string }[]
}

interface PlatformStatusPayload {
  available: boolean
  restart_allowed: boolean
  reasons: string[]
  containers: PlatformContainer[]
  summary: { total: number; running: number; unhealthy: number; missing: number }
  checked_at?: string
}

function statusColor(status: string) {
  switch (status) {
    case 'running':
      return 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
    case 'starting':
    case 'restarting':
      return 'text-amber-300 bg-amber-500/15 border-amber-500/30'
    case 'unhealthy':
    case 'exited':
    case 'dead':
    case 'missing':
      return 'text-rose-300 bg-rose-500/15 border-rose-500/30'
    default:
      return 'text-slate-300 bg-white/[0.06] border-white/[0.08]'
  }
}

function statusDot(status: string) {
  if (status === 'running') return 'bg-emerald-400'
  if (status === 'starting' || status === 'restarting') return 'bg-amber-400 animate-pulse'
  if (status === 'missing' || status === 'exited' || status === 'unhealthy' || status === 'dead')
    return 'bg-rose-400'
  return 'bg-slate-500'
}

async function readError(res: Response) {
  try {
    const j = await res.json()
    return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || j)
  } catch {
    return res.statusText || 'İstek başarısız'
  }
}

export const PlatformStatusTab: React.FC = () => {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [logText, setLogText] = useState('')
  const [logErr, setLogErr] = useState<string | null>(null)
  const logBoxRef = useRef<HTMLPreElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data, isLoading, isFetching, error, refetch } = useQuery<PlatformStatusPayload>({
    queryKey: ['platform-containers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/platform/containers`)
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    refetchInterval: 8000,
  })

  const restartMut = useMutation({
    mutationFn: async (name: string) => {
      const r = await fetch(`${API_BASE_URL}/platform/containers/${encodeURIComponent(name)}/restart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      })
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-containers'] })
    },
  })

  const containers = data?.containers || []
  const selectedRow = containers.find((c) => c.name === selected) || null

  useEffect(() => {
    if (!selected && containers.length) {
      const prefer = containers.find((c) => c.name === 'server_management_backend' && c.present)
        || containers.find((c) => c.present)
      if (prefer) setSelected(prefer.name)
    }
  }, [containers, selected])

  // Tail yükle (canlı değilken)
  useEffect(() => {
    if (!selected || live) return
    let cancelled = false
    ;(async () => {
      setLogErr(null)
      try {
        const r = await fetch(
          `${API_BASE_URL}/platform/containers/${encodeURIComponent(selected)}/logs?tail=250`,
        )
        if (!r.ok) throw new Error(await readError(r))
        const body = await r.json()
        if (!cancelled) setLogText(body.logs || '')
      } catch (e) {
        if (!cancelled) setLogErr(e instanceof Error ? e.message : 'Log alınamadı')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, live, data?.checked_at])

  // Canlı SSE (fetch + Authorization interceptor)
  useEffect(() => {
    if (!selected || !live) {
      abortRef.current?.abort()
      abortRef.current = null
      return
    }
    const ac = new AbortController()
    abortRef.current = ac
    setLogText('')
    setLogErr(null)

    ;(async () => {
      try {
        const r = await fetch(
          `${API_BASE_URL}/platform/containers/${encodeURIComponent(selected)}/logs/stream?tail=120`,
          { signal: ac.signal },
        )
        if (!r.ok || !r.body) throw new Error(await readError(r))
        const reader = r.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const part of parts) {
            const lines = part.split('\n')
            let event = 'message'
            const dataLines: string[] = []
            for (const line of lines) {
              if (line.startsWith('event:')) event = line.slice(6).trim()
              else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
            }
            const payload = dataLines.join('\n')
            if (event === 'error') {
              setLogErr(payload)
              continue
            }
            if (event === 'meta') continue
            setLogText((prev) => {
              const next = prev + payload + '\n'
              // bellek sınırı
              if (next.length > 400_000) return next.slice(-300_000)
              return next
            })
          }
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        setLogErr(e instanceof Error ? e.message : 'Canlı log kesildi')
        setLive(false)
      }
    })()

    return () => {
      ac.abort()
    }
  }, [selected, live])

  useEffect(() => {
    const el = logBoxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logText])

  const ainew = containers.filter((c) => c.group === 'ainew')
  const dropt = containers.filter((c) => c.group === 'dropt')

  return (
    <div className="flex flex-col gap-4 h-[min(780px,calc(100vh-9rem))] min-h-[520px]">
      <div className="flex flex-wrap items-start justify-between gap-3 shrink-0">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Activity size={20} className="text-blue-400" />
            Platform Durumu
          </h2>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            ainew ve Level 1 (Dropt) stack container&apos;larının durumu, sağlık kontrolü ve canlı logları.
            Yalnızca yönetici erişebilir.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-white/[0.06] border border-white/[0.08] text-slate-200 hover:bg-white/[0.1] disabled:opacity-50"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          Yenile
        </button>
      </div>

      {error && (
        <div className="shrink-0 rounded-[10px] border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && data && !data.available && (
        <div className="shrink-0 rounded-[10px] border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          Docker API erişilemiyor. {(data.reasons || []).join(' · ')}
          <div className="text-xs text-amber-200/70 mt-1">
            Backend&apos;e <code className="font-mono">/var/run/docker.sock</code> mount edilmeli.
          </div>
        </div>
      )}

      {data?.summary && (
        <div className="shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Toplam', value: data.summary.total },
            { label: 'Çalışıyor', value: data.summary.running },
            { label: 'Sağlıksız', value: data.summary.unhealthy },
            { label: 'Eksik', value: data.summary.missing },
          ].map((s) => (
            <div key={s.label} className="rounded-[10px] border border-white/[0.06] bg-cyber-deep/40 px-4 py-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">{s.label}</div>
              <div className="text-2xl font-semibold text-white mt-1 tabular-nums">{s.value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid lg:grid-cols-5 gap-4 flex-1 min-h-0">
        <div className="lg:col-span-2 flex flex-col gap-4 min-h-0 overflow-y-auto pr-0.5">
          <GroupList
            title="ainew"
            rows={ainew}
            selected={selected}
            onSelect={setSelected}
            restartAllowed={!!data?.restart_allowed}
            onRestart={(n) => {
              if (window.confirm(`${n} yeniden başlatılsın mı?`)) restartMut.mutate(n)
            }}
            restarting={restartMut.isPending}
          />
          <GroupList
            title="Level 1 (Dropt)"
            rows={dropt}
            selected={selected}
            onSelect={setSelected}
            restartAllowed={!!data?.restart_allowed}
            onRestart={(n) => {
              if (window.confirm(`${n} yeniden başlatılsın mı?`)) restartMut.mutate(n)
            }}
            restarting={restartMut.isPending}
          />
        </div>

        <div className="lg:col-span-3 flex flex-col rounded-[10px] border border-white/[0.06] bg-cyber-deep/30 overflow-hidden min-h-0 h-full">
          <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-white/[0.06]">
            <div className="min-w-0">
              <div className="text-sm font-medium text-white truncate">
                {selectedRow ? selectedRow.name : 'Container seçin'}
              </div>
              {selectedRow && (
                <div className="text-[11px] text-slate-500 font-mono truncate mt-0.5">
                  {selectedRow.role}
                  {selectedRow.image ? ` · ${selectedRow.image}` : ''}
                  {selectedRow.id ? ` · ${selectedRow.id}` : ''}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              {live ? (
                <button
                  type="button"
                  onClick={() => setLive(false)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-rose-600/20 text-rose-300 border border-rose-500/30"
                >
                  <Square size={12} /> Durdur
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!selectedRow?.present}
                  onClick={() => setLive(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-blue-600/20 text-blue-300 border border-blue-500/30 disabled:opacity-40"
                >
                  <Activity size={12} /> Canlı takip
                </button>
              )}
            </div>
          </div>
          {logErr && (
            <div className="shrink-0 px-4 py-2 text-xs text-rose-300 bg-rose-500/10 border-b border-rose-500/20">{logErr}</div>
          )}
          <pre
            ref={logBoxRef}
            className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 text-[11px] leading-relaxed font-mono text-slate-300 whitespace-pre-wrap break-all bg-black/40"
          >
            {logText || (selectedRow?.present ? 'Log yükleniyor…' : 'Container yok veya seçilmedi.')}
          </pre>
        </div>
      </div>

      {restartMut.isError && (
        <div className="shrink-0 text-sm text-rose-300">{(restartMut.error as Error).message}</div>
      )}
      {restartMut.isSuccess && (
        <div className="shrink-0 text-sm text-emerald-300">Yeniden başlatma isteği gönderildi.</div>
      )}
    </div>
  )
}

const GroupList: React.FC<{
  title: string
  rows: PlatformContainer[]
  selected: string | null
  onSelect: (n: string) => void
  restartAllowed: boolean
  onRestart: (n: string) => void
  restarting: boolean
}> = ({ title, rows, selected, onSelect, restartAllowed, onRestart, restarting }) => (
  <div className="rounded-[10px] border border-white/[0.06] overflow-hidden">
    <div className="px-3 py-2 bg-white/[0.03] border-b border-white/[0.06] text-xs font-semibold uppercase tracking-wide text-slate-400">
      {title}
    </div>
    <ul className="divide-y divide-white/[0.04]">
      {rows.map((c) => (
        <li key={c.name}>
          <button
            type="button"
            onClick={() => onSelect(c.name)}
            className={`w-full text-left px-3 py-2.5 flex items-start gap-2 transition-colors ${
              selected === c.name ? 'bg-blue-600/15' : 'hover:bg-white/[0.04]'
            }`}
          >
            <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${statusDot(c.status)}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-white font-medium truncate">{c.name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded border ${statusColor(c.status)}`}>
                  {c.status}
                </span>
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">{c.role}</div>
            </div>
            {restartAllowed && c.present && (
              <span
                role="button"
                tabIndex={0}
                title="Yeniden başlat"
                onClick={(e) => {
                  e.stopPropagation()
                  onRestart(c.name)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.stopPropagation()
                    onRestart(c.name)
                  }
                }}
                className={`shrink-0 p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-white/[0.08] ${
                  restarting ? 'opacity-40 pointer-events-none' : ''
                }`}
              >
                <RotateCcw size={14} />
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  </div>
)

export default PlatformStatusTab
