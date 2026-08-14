import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, Download, Maximize2, Minimize2, PanelLeftClose, PanelLeftOpen,
  RefreshCw, RotateCcw, Search, Square, X,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

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

async function readError(res: Response, fallback: string) {
  try {
    const j = await res.json()
    return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || j)
  } catch {
    return res.statusText || fallback
  }
}

function filterLogLines(text: string, query: string) {
  const lines = text ? text.split('\n') : []
  const needle = query.trim().toLowerCase()
  const shown = needle ? lines.filter((line) => line.toLowerCase().includes(needle)) : lines
  return { total: lines.length, shown: shown.length, display: shown.join('\n') }
}

function downloadText(filename: string, body: string) {
  const blob = new Blob([body], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export const PlatformStatusTab: React.FC = () => {
  const t = useT()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [logText, setLogText] = useState('')
  const [logErr, setLogErr] = useState<string | null>(null)
  const [logFilter, setLogFilter] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(true)
  const logBoxRef = useRef<HTMLPreElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const stickBottomRef = useRef(true)

  const { data, isLoading, isFetching, error, refetch } = useQuery<PlatformStatusPayload>({
    queryKey: ['platform-containers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/platform/containers`)
      if (!r.ok) throw new Error(await readError(r, t('pu_req_fail')))
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
      if (!r.ok) throw new Error(await readError(r, t('pu_req_fail')))
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-containers'] })
    },
  })

  const containers = data?.containers || []
  const selectedRow = containers.find((c) => c.name === selected) || null
  const filtered = useMemo(() => filterLogLines(logText, logFilter), [logText, logFilter])

  useEffect(() => {
    if (!selected && containers.length) {
      const prefer = containers.find((c) => c.name === 'server_management_backend' && c.present)
        || containers.find((c) => c.present)
      if (prefer) setSelected(prefer.name)
    }
  }, [containers, selected])

  useEffect(() => {
    if (!selected || live) return
    let cancelled = false
    ;(async () => {
      setLogErr(null)
      try {
        const r = await fetch(
          `${API_BASE_URL}/platform/containers/${encodeURIComponent(selected)}/logs?tail=250`,
        )
        if (!r.ok) throw new Error(await readError(r, t('pu_req_fail')))
        const body = await r.json()
        if (!cancelled) setLogText(body.logs || '')
      } catch (e) {
        if (!cancelled) setLogErr(e instanceof Error ? e.message : t('ps_log_fail'))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, live, data?.checked_at, t])

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
    stickBottomRef.current = true

    ;(async () => {
      try {
        const r = await fetch(
          `${API_BASE_URL}/platform/containers/${encodeURIComponent(selected)}/logs/stream?tail=120`,
          { signal: ac.signal },
        )
        if (!r.ok || !r.body) throw new Error(await readError(r, t('pu_req_fail')))
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
              if (next.length > 400_000) return next.slice(-300_000)
              return next
            })
          }
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        setLogErr(e instanceof Error ? e.message : t('ps_live_cut'))
        setLive(false)
      }
    })()

    return () => {
      ac.abort()
    }
  }, [selected, live, t])

  useEffect(() => {
    const el = logBoxRef.current
    if (!el || !stickBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [filtered.display])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const ainew = containers.filter((c) => c.group === 'ainew')
  const dropt = containers.filter((c) => c.group === 'dropt')

  const onLogScroll = () => {
    const el = logBoxRef.current
    if (!el) return
    stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }

  const exportLogs = () => {
    const body = (logFilter.trim() ? filtered.display : logText).replace(/\s+$/, '')
    if (!body) return
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    downloadText(`${selected || 'container'}-logs-${stamp}.txt`, body + '\n')
  }

  const confirmRestart = (n: string) => {
    if (window.confirm(t('ps_restart_confirm', { n }))) restartMut.mutate(n)
  }

  const emptyLog = !logText
    ? (selectedRow?.present ? t('ps_log_loading') : t('ps_log_empty'))
    : (logFilter.trim() && filtered.shown === 0 ? t('ps_no_match') : '')

  return (
    <div
      className={
        expanded
          ? 'fixed inset-0 z-[80] bg-[#080d16] p-4 flex flex-col gap-4'
          : 'flex flex-col gap-4 flex-1 min-h-0 h-full overflow-hidden'
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-3 shrink-0">
        <div>
          <h2 className="text-xl font-semibold text-white flex items-center gap-2">
            <Activity size={20} className="text-blue-400" />
            {t('set_tab_platform')}
          </h2>
          {!expanded && (
            <p className="text-sm text-slate-400 mt-1 max-w-2xl">
              {t('ps_subtitle')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-white/[0.06] border border-white/[0.08] text-slate-200 hover:bg-white/[0.1] disabled:opacity-50"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
            {t('refresh_action')}
          </button>
          {expanded && (
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-white/[0.06] border border-white/[0.08] text-slate-200 hover:bg-white/[0.1]"
            >
              <Minimize2 size={14} />
              {t('ps_collapse')}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="shrink-0 rounded-[10px] border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && data && !data.available && (
        <div className="shrink-0 rounded-[10px] border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          {t('ps_docker_unavailable')} {(data.reasons || []).join(' · ')}
          <div className="text-xs text-amber-200/70 mt-1">
            {t('ps_docker_sock_hint')}
          </div>
        </div>
      )}

      {data?.summary && !expanded && (
        <div className="shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: t('total'), value: data.summary.total },
            { label: t('ps_sum_running'), value: data.summary.running },
            { label: t('ps_sum_unhealthy'), value: data.summary.unhealthy },
            { label: t('ps_sum_missing'), value: data.summary.missing },
          ].map((s) => (
            <div key={s.label} className="rounded-[10px] border border-white/[0.06] bg-cyber-deep/40 px-4 py-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">{s.label}</div>
              <div className="text-2xl font-semibold text-white mt-1 tabular-nums">{s.value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-3 flex-1 min-h-0">
        {drawerOpen && (
          <div className="w-full max-w-[22rem] lg:w-[22rem] shrink-0 min-h-0 flex flex-col">
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-4 pr-0.5">
              <GroupList
                title="ainew"
                rows={ainew}
                selected={selected}
                onSelect={setSelected}
                restartAllowed={!!data?.restart_allowed}
                onRestart={confirmRestart}
                restarting={restartMut.isPending}
                headerAction={
                  <button
                    type="button"
                    onClick={() => setDrawerOpen(false)}
                    title={t('ps_drawer_hide')}
                    aria-label={t('ps_drawer_hide')}
                    className="inline-flex items-center justify-center h-7 w-7 rounded-md text-slate-400 hover:text-white hover:bg-white/[0.08]"
                  >
                    <PanelLeftClose size={15} />
                  </button>
                }
              />
              <GroupList
                title={t('ps_group_dropt')}
                rows={dropt}
                selected={selected}
                onSelect={setSelected}
                restartAllowed={!!data?.restart_allowed}
                onRestart={confirmRestart}
                restarting={restartMut.isPending}
              />
            </div>
          </div>
        )}

        <div className="flex-1 min-w-0 min-h-0 flex flex-col rounded-[10px] border border-white/[0.06] bg-cyber-deep/30 overflow-hidden h-full">
          <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-white/[0.06]">
            <div className="min-w-0 flex items-center gap-2">
              {!drawerOpen && (
                <button
                  type="button"
                  onClick={() => setDrawerOpen(true)}
                  title={t('ps_drawer_show')}
                  aria-label={t('ps_drawer_show')}
                  className="inline-flex items-center justify-center h-7 w-7 shrink-0 rounded-md text-slate-400 hover:text-white hover:bg-white/[0.08]"
                >
                  <PanelLeftOpen size={15} />
                </button>
              )}
              <div className="min-w-0">
                <div className="text-sm font-medium text-white truncate">
                  {selectedRow ? selectedRow.name : t('ps_select')}
                </div>
                {selectedRow && (
                  <div className="text-[11px] text-slate-500 font-mono truncate mt-0.5">
                    {selectedRow.role}
                    {selectedRow.image ? ` · ${selectedRow.image}` : ''}
                    {selectedRow.id ? ` · ${selectedRow.id}` : ''}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap justify-end">
              <button
                type="button"
                disabled={!logText.trim()}
                title={!logText.trim() ? t('ps_export_empty') : t('ps_export')}
                onClick={exportLogs}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-white/[0.06] text-slate-200 border border-white/[0.08] hover:bg-white/[0.1] disabled:opacity-40"
              >
                <Download size={12} /> {t('ps_export')}
              </button>
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-white/[0.06] text-slate-200 border border-white/[0.08] hover:bg-white/[0.1]"
              >
                {expanded ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                {expanded ? t('ps_collapse') : t('ps_expand')}
              </button>
              {live ? (
                <button
                  type="button"
                  onClick={() => setLive(false)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-rose-600/20 text-rose-300 border border-rose-500/30"
                >
                  <Square size={12} /> {t('stop')}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!selectedRow?.present}
                  onClick={() => setLive(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-blue-600/20 text-blue-300 border border-blue-500/30 disabled:opacity-40"
                >
                  <Activity size={12} /> {t('ps_live')}
                </button>
              )}
            </div>
          </div>

          <div className="shrink-0 px-3 py-2 border-b border-white/[0.06] flex items-center gap-2">
            <div className="relative flex-1 min-w-0">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
              <input
                type="text"
                value={logFilter}
                onChange={(e) => setLogFilter(e.target.value)}
                placeholder={t('ps_filter_ph')}
                className="w-full bg-black/30 border border-white/[0.08] rounded-lg pl-8 pr-8 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/40"
              />
              {logFilter && (
                <button
                  type="button"
                  onClick={() => setLogFilter('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  aria-label={t('close')}
                >
                  <X size={12} />
                </button>
              )}
            </div>
            {logText && (
              <span className="shrink-0 text-[11px] text-slate-500 tabular-nums">
                {t('ps_filter_n', { shown: filtered.shown, total: filtered.total })}
              </span>
            )}
          </div>

          {logErr && (
            <div className="shrink-0 px-4 py-2 text-xs text-rose-300 bg-rose-500/10 border-b border-rose-500/20">{logErr}</div>
          )}
          <pre
            ref={logBoxRef}
            onScroll={onLogScroll}
            className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 text-[11px] leading-relaxed font-mono text-slate-300 whitespace-pre-wrap break-all bg-black/40"
          >
            {emptyLog || filtered.display}
          </pre>
        </div>
      </div>

      {restartMut.isError && (
        <div className="shrink-0 text-sm text-rose-300">{(restartMut.error as Error).message}</div>
      )}
      {restartMut.isSuccess && (
        <div className="shrink-0 text-sm text-emerald-300">{t('ps_restart_sent')}</div>
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
  headerAction?: React.ReactNode
}> = ({ title, rows, selected, onSelect, restartAllowed, onRestart, restarting, headerAction }) => {
  const t = useT()
  return (
    <div className="rounded-[10px] border border-white/[0.06] overflow-hidden shrink-0">
      <div className="px-3 py-2 bg-white/[0.03] border-b border-white/[0.06] flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</span>
        {headerAction}
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-3 text-xs text-slate-500">{t('ps_none')}</div>
      ) : (
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
                    title={t('ps_restart')}
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
      )}
    </div>
  )
}

export default PlatformStatusTab
