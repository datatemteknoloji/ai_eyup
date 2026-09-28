/**
 * OpenShift kaynak detay çekmecesi — Atlas WorkloadDetail / PodDetail parity.
 * Deployment/DS/STS: Ayrıntı · Kaynaklar(svc+route) · Pod'lar · Ortam · Loglar · Olaylar · YAML
 * Pod: Genel · Container'lar · Loglar · Terminal · Metrikler · Olaylar · YAML
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, Bell, Box, Boxes, Check, Copy, Download, FileCode, FileText,
  Gauge, Globe, Layers, ListTree, Lock, RefreshCw, Settings2,
  Terminal as TerminalIcon, Trash2, X,
} from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'

type Props = {
  clusterId: number
  kind: string
  name: string
  namespace?: string
  onClose: () => void
  onOpenPod?: (ns: string, pod: string) => void
  onDeleted?: () => void
}

type TabId =
  | 'detail' | 'resources' | 'pods' | 'env' | 'logs'
  | 'containers' | 'terminal' | 'metrics' | 'events' | 'yaml'

function statusTone(s?: string) {
  const v = (s || '').toLowerCase()
  if (['true', 'running', 'ready', 'succeeded', 'available', 'bound', 'active'].includes(v))
    return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
  if (['false', 'failed', 'error', 'crashloopbackoff', 'imagepullbackoff', 'pending'].some((x) => v.includes(x)))
    return 'bg-amber-500/15 text-amber-300 border-amber-500/30'
  return 'bg-white/[0.06] text-slate-300 border-white/[0.08]'
}

function condDot(status?: string) {
  return status === 'True' ? 'bg-emerald-400' : status === 'False' ? 'bg-red-400' : 'bg-slate-500'
}

function Kv({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-white/[0.04] text-xs">
      <span className="text-slate-500 flex-shrink-0">{label}</span>
      <span className="text-slate-100 text-right break-all min-w-0">{value ?? '—'}</span>
    </div>
  )
}

function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-mono bg-white/[0.06] border border-white/[0.08] text-slate-300 mr-1.5 mb-1.5">
      {children}
    </span>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-slate-300">{title}</h3>
      {children}
    </div>
  )
}

function stateCls(s: string) {
  if (s === 'running') return 'bg-emerald-500/15 text-emerald-300'
  if (/CrashLoop|Error|ImagePull|OOM/i.test(s)) return 'bg-red-500/15 text-red-300'
  if (s === 'Completed') return 'bg-blue-500/15 text-blue-300'
  return 'bg-amber-500/15 text-amber-300'
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('auth_token') || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Atlas tarzı pod terminali — JSON input/resize. */
function PodExecTerminal({
  clusterId, namespace, pod, containers, initial,
}: {
  clusterId: number
  namespace: string
  pod: string
  containers: string[]
  initial?: string
}) {
  const [container, setContainer] = useState(initial || containers[0] || '')
  const [nonce, setNonce] = useState(0)
  const [state, setState] = useState<'connecting' | 'open' | 'closed' | 'error'>('connecting')
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!hostRef.current || !container) return
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: { background: '#0a0f1a', foreground: '#e5e7eb', cursor: '#f87171' },
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(hostRef.current)
    try { fit.fit() } catch { /* */ }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const token = localStorage.getItem('auth_token') || ''
    const qs = new URLSearchParams({ token })
    qs.set('container', container)
    const url =
      `${proto}://${window.location.host}/api/v1/openshift/clusters/${clusterId}`
      + `/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(pod)}/exec?${qs}`

    setState('connecting')
    term.writeln(`\x1b[90m${namespace}/${pod} · ${container} bağlanıyor…\x1b[0m`)
    const ws = new WebSocket(url)

    ws.onopen = () => {
      setState('open')
      term.writeln('\x1b[90mbağlandı\x1b[0m\r\n')
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      term.focus()
    }
    ws.onmessage = (e) => term.write(typeof e.data === 'string' ? e.data : '')
    ws.onerror = () => setState('error')
    ws.onclose = (e) => {
      setState((s) => (s === 'error' ? s : 'closed'))
      term.writeln(`\r\n\x1b[90m[oturum kapandı${e.reason ? `: ${e.reason}` : ''}]\x1b[0m`)
    }
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }))
      }
    })
    const onWin = () => {
      try { fit.fit() } catch { /* */ }
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }
    window.addEventListener('resize', onWin)
    const t = window.setTimeout(onWin, 120)

    return () => {
      window.clearTimeout(t)
      window.removeEventListener('resize', onWin)
      try { ws.close() } catch { /* */ }
      term.dispose()
    }
  }, [clusterId, namespace, pod, container, nonce])

  return (
    <div className="rounded-lg border border-white/[0.08] overflow-hidden flex flex-col h-[30rem]">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.06] flex-wrap">
        <TerminalIcon className="w-4 h-4 text-rose-400 flex-shrink-0" />
        <span className="text-xs text-slate-200 font-mono truncate">{pod}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
          state === 'open' ? 'bg-emerald-500/15 text-emerald-300'
            : state === 'connecting' ? 'bg-amber-500/15 text-amber-300'
              : 'bg-red-500/15 text-red-300'
        }`}>
          {state === 'open' ? 'bağlı' : state === 'connecting' ? 'bağlanıyor' : 'kapalı'}
        </span>
        {containers.length > 1 && (
          <select
            className="text-[11px] bg-cyber-deep border border-white/[0.08] rounded px-2 py-1 text-slate-200 w-40"
            value={container}
            onChange={(e) => setContainer(e.target.value)}
          >
            {containers.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        <button
          type="button"
          title="Yeniden bağlan"
          onClick={() => setNonce((n) => n + 1)}
          className="ml-auto p-1.5 rounded-md text-slate-500 hover:text-slate-200 hover:bg-white/[0.06]"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>
      <div ref={hostRef} className="flex-1 bg-[#0a0f1a] p-2 overflow-hidden" />
      <p className="text-[10px] text-slate-600 px-3 py-1.5 border-t border-white/[0.06]">
        Pod içinde kabuk açar (bash yoksa sh). Kabuğu olmayan container&apos;larda bağlantı hemen kapanır.
      </p>
    </div>
  )
}

function LogsPanel({
  clusterId, namespace, pods, containers, defaultPod, defaultContainer, problem,
}: {
  clusterId: number
  namespace: string
  pods?: { name: string; containers?: string[] }[]
  containers: string[]
  defaultPod?: string
  defaultContainer?: string
  problem?: string
}) {
  const t = useT()
  const multiPod = (pods || []).length > 0
  const [pod, setPod] = useState(defaultPod || pods?.[0]?.name || '')
  const [container, setContainer] = useState(problem || defaultContainer || containers[0] || '')
  const [tail, setTail] = useState(300)
  const [previous, setPrevious] = useState(false)
  const [timestamps, setTimestamps] = useState(true)
  const [auto, setAuto] = useState(multiPod)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const boxRef = useRef<HTMLPreElement>(null)

  const current = (pods || []).find((p) => p.name === pod)
  const contOpts = multiPod
    ? (current?.containers || containers)
    : containers

  useEffect(() => {
    if (multiPod && current && contOpts.length && !contOpts.includes(container)) {
      setContainer(contOpts[0] || '')
    }
  }, [pod]) // eslint-disable-line react-hooks/exhaustive-deps

  const pull = () => {
    const targetPod = multiPod ? pod : (defaultPod || '')
    if (!targetPod || !container || !namespace) return
    setLoading(true)
    const params = new URLSearchParams({
      tail: String(tail),
      previous: String(previous),
      timestamps: String(timestamps),
      container,
    })
    fetch(
      `${API_BASE_URL}/openshift/clusters/${clusterId}/pods/`
      + `${encodeURIComponent(namespace)}/${encodeURIComponent(targetPod)}/logs?${params}`,
      { headers: authHeaders() },
    )
      .then((r) => r.json())
      .then((d) => setText(d.logs || d.log || d.error || ''))
      .catch((e) => setText(`HATA: ${e.message}`))
      .finally(() => setLoading(false))
  }

  useEffect(() => { pull() }, [pod, container, previous, timestamps, tail]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!auto) return
    const id = setInterval(pull, 5000)
    return () => clearInterval(id)
  }, [auto, pod, container, previous, timestamps, tail]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [text])

  const download = () => {
    const blob = new Blob([text], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${pod || defaultPod}-${container}.log`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        {multiPod && (
          <select
            className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200"
            value={pod}
            onChange={(e) => setPod(e.target.value)}
          >
            {(pods || []).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        )}
        <select
          className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200 w-44"
          value={container}
          onChange={(e) => setContainer(e.target.value)}
        >
          {contOpts.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200 w-28"
          value={tail}
          onChange={(e) => setTail(Number(e.target.value))}
        >
          {[100, 300, 1000, 5000].map((n) => (
            <option key={n} value={n}>son {n}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
          <input type="checkbox" checked={previous} onChange={(e) => setPrevious(e.target.checked)} />
          {t('ocp_previous')}
        </label>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
          <input type="checkbox" checked={timestamps} onChange={(e) => setTimestamps(e.target.checked)} />
          Zaman damgası
        </label>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Otomatik yenile
        </label>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(text)
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}
            className="text-[11px] px-2 py-1 rounded border border-white/[0.08] text-slate-300 flex items-center gap-1"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
            Kopyala
          </button>
          <button
            type="button"
            onClick={download}
            className="text-[11px] px-2 py-1 rounded border border-white/[0.08] text-slate-300 flex items-center gap-1"
          >
            <Download className="w-3 h-3" /> İndir
          </button>
          <button
            type="button"
            onClick={pull}
            className="text-[11px] px-2 py-1 rounded border border-white/[0.08] text-rose-300 flex items-center gap-1"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Yenile
          </button>
        </div>
      </div>
      {previous && (
        <p className="text-[11px] text-amber-300/80">
          Çöken container&apos;ın <b>bir önceki</b> çalışmasının logu — çökme sebebi genelde buradadır.
        </p>
      )}
      <pre
        ref={boxRef}
        className="bg-[#0a0f1a] border border-white/[0.08] rounded-lg p-3 text-[11px] leading-relaxed
                   text-slate-300 font-mono whitespace-pre-wrap break-all h-[26rem] overflow-auto"
      >
        {loading && !text ? 'Yükleniyor…' : (text || t('ocp_empty_paren'))}
      </pre>
    </div>
  )
}

export default function OcpResourceDetailDrawer({
  clusterId, kind, name, namespace, onClose, onOpenPod, onDeleted,
}: Props) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const isPod = kind === 'pods'
  const isWorkload = ['deployments', 'statefulsets', 'daemonsets'].includes(kind)
  const [tab, setTab] = useState<TabId>('detail')

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['ocp-resource-detail', clusterId, kind, namespace, name],
    queryFn: async () => {
      const params = new URLSearchParams({ kind, name })
      if (namespace) params.set('namespace', namespace)
      const r = await fetch(
        `${API_BASE_URL}/openshift/clusters/${clusterId}/resource-detail?${params}`,
        { headers: authHeaders() },
      )
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body.detail || t('ocp_pod_detail_fail'))
      return body
    },
  })

  const { data: yamlData, isFetching: yamlLoading, refetch: refetchYaml } = useQuery({
    queryKey: ['ocp-resource-yaml', clusterId, kind, namespace, name],
    queryFn: async () => {
      const params = new URLSearchParams({ kind, name })
      if (namespace) params.set('namespace', namespace)
      const r = await fetch(
        `${API_BASE_URL}/openshift/clusters/${clusterId}/resource-yaml?${params}`,
        { headers: authHeaders() },
      )
      return r.json()
    },
    enabled: tab === 'yaml',
  })

  const logNs = (data?.namespace || namespace || '') as string
  const allContainers = useMemo(
    () => [...(data?.init_containers || []), ...(data?.containers || [])],
    [data],
  )
  const containerNames = useMemo(
    () => allContainers.map((c: any) => c.name).filter(Boolean) as string[],
    [allContainers],
  )
  const problem = allContainers.find((c: any) => /CrashLoop|Error|ImagePull|OOM/i.test(c.state || ''))
  const pods = (data?.pods || data?.related_pods || []) as any[]
  const replicas = data?.replicas

  const tabs = useMemo(() => {
    if (isPod) {
      return [
        { id: 'detail' as const, label: t('ocp_tab_general'), icon: Settings2 },
        { id: 'containers' as const, label: t('ocp_tab_containers'), icon: Box },
        { id: 'logs' as const, label: t('ocp_tab_logs'), icon: FileText },
        { id: 'terminal' as const, label: t('ocp_tab_terminal'), icon: TerminalIcon },
        { id: 'metrics' as const, label: t('ocp_tab_metrics'), icon: Gauge },
        { id: 'events' as const, label: t('ocp_tab_events'), icon: Bell },
        { id: 'yaml' as const, label: 'YAML', icon: FileCode },
      ]
    }
    type TabDef = { id: TabId; label: string; icon: typeof Settings2 }
    const base: TabDef[] = [{ id: 'detail', label: t('ocp_tab_detail'), icon: Settings2 }]
    if (isWorkload) {
      base.push(
        { id: 'resources', label: t('ocp_tab_resources'), icon: Boxes },
        { id: 'pods', label: t('ocp_tab_pods'), icon: ListTree },
        { id: 'env', label: t('ocp_tab_env'), icon: Layers },
        { id: 'logs', label: t('ocp_tab_logs'), icon: FileText },
      )
    } else if (kind === 'services') {
      base.push({ id: 'pods', label: t('ocp_tab_pods'), icon: ListTree })
    } else if (kind === 'configmaps') {
      base.push({ id: 'resources', label: t('ocp_tab_keys'), icon: Layers })
    }
    base.push(
      { id: 'events', label: t('ocp_tab_events'), icon: Bell },
      { id: 'yaml', label: 'YAML', icon: FileCode },
    )
    return base
  }, [isPod, isWorkload, kind, t])

  const badge = isWorkload && replicas
    ? `${replicas.ready}/${replicas.desired ?? '?'} hazır`
    : (data?.status_badge || data?.phase || '—')

  const ownerLine = data?.owner
    || (data?.owner_refs || []).map((o: any) => `${o.kind}/${o.name}`).join(', ')

  const deletePod = async () => {
    if (!isPod || !logNs) return
    if (!window.confirm(
      `${name} silinsin mi?\n\nDeployment/StatefulSet yönetiyorsa yerine yenisi gelir; yönetilmiyorsa kalıcı silinir.`,
    )) return
    const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/pod/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ kind: 'pods', namespace: logNs, name }),
    })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) {
      window.alert(body.detail || 'Pod silinemedi')
      return
    }
    onDeleted?.()
    onClose()
  }

  const maxW = isPod ? 'max-w-5xl' : 'max-w-4xl'

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`w-full ${maxW} h-full bg-cyber-card border-l border-white/[0.08] flex flex-col shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex-shrink-0 px-5 pt-3 pb-0 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="min-w-0">
              <p className="text-[11px] text-slate-500 truncate">
                {data?.kind || kind}
                {data?.namespace ? <> · <span className="font-mono">{data.namespace}</span></> : null}
                {isPod && ownerLine ? <> · sahip <span className="font-mono">{ownerLine}</span></> : null}
              </p>
              <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                <h2 className="text-base font-semibold text-white truncate">{name}</h2>
                <span className={`text-[11px] px-2 py-0.5 rounded-full border ${statusTone(String(badge))}`}>
                  {badge}
                </span>
                {problem && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> {problem.name}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0 ml-auto">
              <button
                type="button"
                title={t('refresh_action')}
                onClick={() => refetch()}
                className="p-2 rounded-lg text-slate-400 hover:bg-white/[0.06] hover:text-white"
              >
                <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
              </button>
              {isPod && isAdmin && (
                <button
                  type="button"
                  title="Pod'u sil"
                  onClick={deletePod}
                  className="p-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-white/[0.06]"
                >
                  <Trash2 size={16} />
                </button>
              )}
              <button
                type="button"
                onClick={onClose}
                className="p-2 rounded-lg text-slate-400 hover:bg-white/[0.06] hover:text-white"
              >
                <X size={18} />
              </button>
            </div>
          </div>

          <div className="flex gap-0.5 mt-2 overflow-x-auto -mb-px">
            {tabs.map((tb) => {
              const Icon = tb.icon
              const active = tab === tb.id
              return (
                <button
                  key={tb.id}
                  type="button"
                  onClick={() => setTab(tb.id)}
                  className={`flex items-center gap-1.5 px-3 py-2.5 text-xs whitespace-nowrap border-b-2 transition-colors ${
                    active
                      ? 'border-rose-500 text-white'
                      : 'border-transparent text-slate-500 hover:text-slate-300'
                  }`}
                >
                  <Icon size={13} />
                  {tb.label}
                </button>
              )
            })}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {isLoading && (
            <div className="text-sm text-slate-400 flex items-center gap-2">
              <RefreshCw size={14} className="animate-spin" /> {t('loading')}
            </div>
          )}
          {error && (
            <div className="text-sm text-red-400">
              {error instanceof Error ? error.message : t('error_generic')}
            </div>
          )}

          {data && tab === 'detail' && (
            <>
              {isPod ? (
                <>
                  <Section title={t('ocp_sec_placement')}>
                    <Kv label="Node" value={<span className="font-mono">{data.node}</span>} />
                    <Kv label="Pod IP" value={<span className="font-mono">{data.pod_ip}</span>} />
                    <Kv label="Host IP" value={<span className="font-mono">{data.host_ip}</span>} />
                    <Kv label={t('ocp_age')} value={data.age} />
                    <Kv label={t('ocp_start')} value={<span className="font-mono">{data.start_time}</span>} />
                  </Section>
                  <Section title={t('ocp_sec_config')}>
                    <Kv label={t('ocp_owner')} value={<span className="font-mono">{ownerLine || '—'}</span>} />
                    <Kv label={t('ocp_qos')} value={data.qos || data.qos_class} />
                    <Kv label={t('ocp_sa')} value={<span className="font-mono">{data.service_account}</span>} />
                    <Kv label={t('ocp_restart_policy')} value={data.restart_policy} />
                    {Object.keys(data.node_selector || {}).length > 0 && (
                      <Kv
                        label={t('ocp_node_selector')}
                        value={
                          <span className="font-mono">
                            {Object.entries(data.node_selector).map(([k, v]) => `${k}=${v}`).join(', ')}
                          </span>
                        }
                      />
                    )}
                  </Section>
                </>
              ) : isWorkload ? (
                <Section title={t('ocp_sec_config')}>
                  <Kv label="Ad" value={<span className="font-mono">{data.name}</span>} />
                  <Kv label="Namespace" value={<span className="font-mono">{data.namespace}</span>} />
                  <Kv label="Tür" value={data.kind} />
                  <Kv label="Oluşturulma" value={`${data.age} önce`} />
                  <Kv label="Güncelleme stratejisi" value={data.strategy} />
                  <Kv
                    label="Replika"
                    value={`${replicas?.ready}/${replicas?.desired ?? '?'} hazır · ${replicas?.available ?? '?'} kullanılabilir`}
                  />
                  <Kv
                    label="Selector"
                    value={
                      <span className="font-mono">
                        {Object.entries(data.selector || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—'}
                      </span>
                    }
                  />
                </Section>
              ) : (
                <Section title={t('ocp_sec_config')}>
                  {Object.entries(data.configuration || {}).map(([k, v]) => (
                    <Kv key={k} label={k} value={v == null ? '—' : String(v)} />
                  ))}
                </Section>
              )}

              {(data.conditions || []).length > 0 && (
                <Section title={t('ocp_sec_conditions')}>
                  <div className="space-y-1.5">
                    {(data.conditions || []).map((c: any, i: number) => (
                      <div
                        key={`${c.type}-${i}`}
                        className="flex items-start gap-2 text-xs rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2"
                      >
                        <span className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${condDot(c.status)}`} />
                        <div className="min-w-0">
                          <p className="text-slate-200">
                            {c.type} <span className="text-slate-500">= {c.status}</span>
                            {c.reason && <span className="text-slate-600"> · {c.reason}</span>}
                          </p>
                          {c.message && <p className="text-[11px] text-slate-500 mt-0.5">{c.message}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {Object.keys(data.labels || {}).length > 0 && (
                <Section title={t('ocp_sec_labels')}>
                  <div className="flex flex-wrap">
                    {Object.entries(data.labels || {}).map(([k, v]) => (
                      <Pill key={k}>{k}={String(v)}</Pill>
                    ))}
                  </div>
                </Section>
              )}

              {(data.volumes || []).length > 0 && (
                <Section title={t('ocp_sec_volumes')}>
                  <div className="flex flex-wrap">
                    {(data.volumes || []).map((v: any) => (
                      <Pill key={v.name}>
                        {v.name}
                        <span className="text-slate-500 ml-1">
                          · {v.type}{v.detail ? ` · ${v.detail}` : ''}
                        </span>
                      </Pill>
                    ))}
                  </div>
                </Section>
              )}
            </>
          )}

          {/* Atlas Kaynaklar: Services + Routes + container resources */}
          {data && tab === 'resources' && isWorkload && (
            <div className="space-y-5">
              <Section title={`Servisler (${(data.services || []).length})`}>
                {(data.services || []).length === 0 ? (
                  <p className="text-xs text-slate-600">Servis yok</p>
                ) : (
                  <div className="space-y-1.5">
                    {(data.services || []).map((s: any) => (
                      <div key={s.name} className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2 text-xs">
                        <p className="text-slate-200 font-mono flex items-center gap-1.5">
                          <Boxes className="w-3.5 h-3.5 text-emerald-400" /> {s.name}
                        </p>
                        <p className="text-[11px] text-slate-500 mt-0.5">
                          {s.type} · {s.cluster_ip} · {(s.ports || []).join(', ') || 'port yok'}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </Section>
              <Section title={`Route'lar (${(data.routes || []).length})`}>
                {(data.routes || []).length === 0 ? (
                  <p className="text-xs text-slate-600">Dışarı açık değil</p>
                ) : (
                  <div className="space-y-1.5">
                    {(data.routes || []).map((r: any) => (
                      <div key={r.name} className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2 text-xs">
                        <p className="text-slate-200 font-mono flex items-center gap-1.5">
                          <Globe className="w-3.5 h-3.5 text-cyan-400" /> {r.name}
                        </p>
                        {r.host && (
                          <a
                            href={`${r.tls ? 'https' : 'http'}://${r.host}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[11px] text-cyan-400 hover:text-cyan-300 break-all"
                          >
                            {r.tls ? 'https' : 'http'}://{r.host}
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Section>
              <Section title="Container kaynakları">
                <div className="space-y-1.5">
                  {(data.containers || []).map((c: any) => (
                    <div key={c.name} className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2 text-xs">
                      <p className="text-slate-200">
                        {c.name} {c.init && <span className="text-[10px] text-slate-600">(init)</span>}
                      </p>
                      <p className="text-[11px] text-slate-600 font-mono break-all mt-0.5">{c.image}</p>
                      <p className="text-[11px] text-slate-500 mt-1">
                        istek: {Object.entries(c.requests || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—'}
                        {' · '}
                        limit: {Object.entries(c.limits || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—'}
                        {(c.ports || []).length > 0 && ` · port: ${(c.ports || []).join(', ')}`}
                      </p>
                    </div>
                  ))}
                </div>
              </Section>
            </div>
          )}

          {data && tab === 'resources' && !isWorkload && (
            <Section title={t('ocp_tab_resources')}>
              {(data.related_resources || []).length === 0 ? (
                <div className="text-sm text-slate-500">{t('ocp_empty_paren')}</div>
              ) : (
                <div className="space-y-1.5">
                  {(data.related_resources || []).map((r: any) => (
                    <div
                      key={`${r.kind}/${r.name}`}
                      className="flex items-center gap-2 rounded-lg border border-white/[0.06] px-3 py-2 text-sm"
                    >
                      <span className="text-slate-500 text-xs">{r.kind}</span>
                      <span className="text-white font-mono truncate">{r.name}</span>
                      <span className="text-slate-500 ml-auto text-xs">{r.info}</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          )}

          {data && tab === 'pods' && (
            <div className="space-y-1.5">
              {pods.length === 0 && <p className="text-xs text-slate-600">{t('ocp_no_pods')}</p>}
              {pods.map((p: any) => (
                <button
                  key={p.name}
                  type="button"
                  onClick={() => onOpenPod?.(p.namespace || logNs, p.name)}
                  className={`w-full text-left rounded-lg border px-3 py-2.5 ${
                    p.healthy !== false && (p.phase || '').toLowerCase() === 'running'
                      ? 'border-white/[0.06] bg-cyber-deep/40'
                      : 'border-red-900/40 bg-red-950/15'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      p.healthy || (p.phase || '').toLowerCase() === 'running' ? 'bg-emerald-400' : 'bg-red-400'
                    }`} />
                    <span className="text-xs text-white font-mono truncate">{p.name}</span>
                    <span className="text-[11px] text-slate-500 ml-auto flex-shrink-0">{p.age}</span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">
                    {p.phase} · {p.ready} hazır
                    {p.restarts > 0 && <span className="text-amber-400"> · ↻{p.restarts}</span>}
                    {p.node && <span className="text-slate-600"> · {String(p.node).split('.')[0]}</span>}
                  </p>
                </button>
              ))}
            </div>
          )}

          {data && tab === 'env' && isWorkload && (
            <div className="space-y-5">
              {(data.containers || []).map((c: any) => (
                <div key={c.name}>
                  <p className="text-xs font-medium text-slate-300 mb-2">
                    {c.name}{' '}
                    <span className="text-slate-600 font-normal">
                      ({(c.env || []).length} değişken)
                    </span>
                  </p>
                  {(c.env || []).length === 0 ? (
                    <p className="text-xs text-slate-600">Ortam değişkeni yok</p>
                  ) : (
                    <div className="rounded-lg border border-white/[0.06] overflow-hidden">
                      {(c.env || []).map((e: any, i: number) => (
                        <div
                          key={i}
                          className={`flex items-start gap-3 px-3 py-1.5 text-[11px] ${
                            i % 2 ? 'bg-cyber-deep/40' : 'bg-cyber-deep/20'
                          }`}
                        >
                          <span className="text-slate-300 font-mono flex-shrink-0 w-1/3 truncate">{e.name}</span>
                          {e.secret ? (
                            <span className="text-amber-400/80 flex items-center gap-1">
                              <Lock className="w-3 h-3" /> Secret ·{' '}
                              <span className="font-mono text-slate-500">{e.ref}</span>
                            </span>
                          ) : e.from ? (
                            <span className="text-slate-500">
                              {e.from} · <span className="font-mono">{e.ref}</span>
                            </span>
                          ) : (
                            <span className="text-slate-400 font-mono break-all">{e.value || '—'}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {(c.mounts || []).length > 0 && (
                    <p className="text-[11px] text-slate-600 mt-1.5">
                      Bağlı volume:{' '}
                      {(c.mounts || []).map((m: any) => `${m.name}→${m.path}${m.readonly ? ' (ro)' : ''}`).join(', ')}
                    </p>
                  )}
                </div>
              ))}
              <p className="text-[11px] text-slate-600">
                Secret değerleri güvenlik gereği çözülmez — yalnızca hangi Secret&apos;a başvurduğu gösterilir.
              </p>
            </div>
          )}

          {data && tab === 'containers' && isPod && (
            <div className="space-y-3">
              {allContainers.map((c: any) => (
                <div
                  key={`${c.init ? 'init-' : ''}${c.name}`}
                  className={`rounded-lg border p-4 ${
                    /CrashLoop|Error|ImagePull|OOM/i.test(c.state || '')
                      ? 'border-red-900/40'
                      : 'border-white/[0.06]'
                  } bg-cyber-deep/30`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-2">
                    <span className="text-sm text-white font-medium">{c.name}</span>
                    {c.init && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-400">init</span>
                    )}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${stateCls(c.state || '')}`}>
                      {c.state}
                    </span>
                    {!c.ready && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
                        hazır değil
                      </span>
                    )}
                    {(c.restarts || c.restart_count || 0) > 0 && (
                      <span className={`text-[11px] ml-auto tabular-nums ${
                        (c.restarts || 0) > 100 ? 'text-red-400'
                          : (c.restarts || 0) > 10 ? 'text-amber-400' : 'text-slate-500'
                      }`}>
                        {(c.restarts || c.restart_count || 0).toLocaleString('tr-TR')} restart
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 font-mono break-all mb-2">{c.image}</p>

                  {c.last_exit && (
                    <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/50 px-2.5 py-1.5 mb-2">
                      <p className="text-[11px] text-slate-300">
                        Son çıkış:{' '}
                        <b className={c.last_exit.code ? 'text-red-300' : 'text-slate-200'}>
                          {c.last_exit.reason} (kod {c.last_exit.code})
                        </b>
                        <span className="text-slate-600 ml-1.5 font-mono">{c.last_exit.at}</span>
                      </p>
                    </div>
                  )}

                  <div className="grid sm:grid-cols-2 gap-3 text-[11px]">
                    <div>
                      <p className="text-slate-500 mb-1">Kaynaklar</p>
                      {Object.keys(c.requests || {}).length === 0 && Object.keys(c.limits || {}).length === 0 ? (
                        <p className="text-slate-600">tanımsız — limitsiz çalışıyor</p>
                      ) : (
                        <>
                          {Object.entries(c.requests || {}).map(([k, v]) => (
                            <p key={`r${k}`} className="text-slate-400">
                              istek {k}: <span className="text-slate-300">{String(v)}</span>
                            </p>
                          ))}
                          {Object.entries(c.limits || {}).map(([k, v]) => (
                            <p key={`l${k}`} className="text-slate-400">
                              limit {k}: <span className="text-slate-300">{String(v)}</span>
                            </p>
                          ))}
                        </>
                      )}
                    </div>
                    <div>
                      <p className="text-slate-500 mb-1">Portlar</p>
                      {(c.ports || []).length === 0 ? (
                        <p className="text-slate-600">yok</p>
                      ) : (
                        (c.ports || []).map((p: any, i: number) => (
                          <p key={i} className="text-slate-400 font-mono">
                            {p.port}/{p.protocol}{p.name ? ` (${p.name})` : ''}
                          </p>
                        ))
                      )}
                    </div>
                  </div>

                  {(c.mounts || []).length > 0 && (
                    <div className="mt-2">
                      <p className="text-[11px] text-slate-500 mb-1">Mount&apos;lar</p>
                      {(c.mounts || []).map((m: any, i: number) => (
                        <p key={i} className="text-[11px] text-slate-400 font-mono">
                          {m.path}{' '}
                          <span className="text-slate-600">
                            ← {m.name}{m.readonly ? ' (ro)' : ''}
                          </span>
                        </p>
                      ))}
                    </div>
                  )}

                  {(c.env || []).length > 0 && (
                    <div className="mt-2">
                      <p className="text-[11px] text-slate-500 mb-1 flex items-center gap-1.5">
                        Ortam değişkenleri
                        <span className="text-slate-600 flex items-center gap-1">
                          <Lock className="w-2.5 h-2.5" /> Secret değerleri gösterilmez
                        </span>
                      </p>
                      <div className="max-h-40 overflow-y-auto space-y-0.5">
                        {(c.env || []).map((e: any, i: number) => (
                          <p key={i} className="text-[11px] font-mono">
                            <span className="text-slate-300">{e.name}</span>
                            <span className="text-slate-600">=</span>
                            {e.from === 'literal' || (!e.from && e.value != null)
                              ? <span className="text-slate-400">{e.value || '""'}</span>
                              : (
                                <span className={e.from === 'secret' ? 'text-amber-400/80' : 'text-cyan-400/80'}>
                                  {'<'}{e.from}: {e.ref}{'>'}
                                </span>
                              )}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {tab === 'logs' && logNs && (
            <LogsPanel
              clusterId={clusterId}
              namespace={logNs}
              pods={isPod ? undefined : pods.map((p: any) => ({
                name: p.name,
                containers: p.containers || containerNames,
              }))}
              containers={containerNames}
              defaultPod={isPod ? name : pods[0]?.name}
              defaultContainer={problem?.name || containerNames[0]}
              problem={problem?.name}
            />
          )}

          {tab === 'terminal' && isPod && logNs && (
            containerNames.length ? (
              <PodExecTerminal
                clusterId={clusterId}
                namespace={logNs}
                pod={name}
                containers={containerNames}
                initial={problem?.name || containerNames[0]}
              />
            ) : (
              <p className="text-xs text-slate-600">{t('ocp_pick_container')}</p>
            )
          )}

          {tab === 'metrics' && isPod && (
            <Section title={t('ocp_tab_metrics')}>
              {Object.keys(data?.usage || {}).length === 0 && !data?.metrics ? (
                <p className="text-xs text-slate-500">{t('ocp_metrics_unavailable')}</p>
              ) : (
                <div className="space-y-2">
                  <p className="text-[11px] text-slate-500">
                    Anlık kullanım (metrics.k8s.io). Limit tanımlıysa yanında gösterilir.
                  </p>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 border-b border-white/[0.06]">
                        {['Container', 'CPU (millicore)', 'Bellek (MB)', 'CPU limiti', 'Bellek limiti'].map((h) => (
                          <th key={h} className="text-left font-medium py-2 pr-3 whitespace-nowrap">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {allContainers.map((c: any) => {
                        const u = (data.usage || {})[c.name]
                          || (data.metrics?.containers || []).find((x: any) => x.name === c.name)
                        return (
                          <tr key={c.name} className="border-b border-white/[0.04]">
                            <td className="py-1.5 pr-3 font-mono text-slate-200">{c.name}</td>
                            <td className="py-1.5 pr-3 tabular-nums text-slate-300">
                              {u?.cpu_millicores ?? '—'}
                            </td>
                            <td className="py-1.5 pr-3 tabular-nums text-slate-300">
                              {u?.memory_mb ?? '—'}
                            </td>
                            <td className="py-1.5 pr-3 text-slate-500">{c.limits?.cpu || '—'}</td>
                            <td className="py-1.5 pr-3 text-slate-500">{c.limits?.memory || '—'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          )}

          {tab === 'events' && (
            <div className="space-y-1.5">
              {(data?.events || []).length === 0 ? (
                <p className="text-xs text-slate-500">{t('ocp_empty_paren')}</p>
              ) : (
                (data.events || []).map((e: any, i: number) => (
                  <div
                    key={i}
                    className={`rounded-lg border px-3 py-2 ${
                      e.warning || e.type === 'Warning'
                        ? 'border-amber-900/40 bg-amber-950/15'
                        : 'border-white/[0.06] bg-cyber-deep/40'
                    }`}
                  >
                    <div className="flex items-center gap-2 flex-wrap text-xs">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        e.warning || e.type === 'Warning'
                          ? 'bg-amber-500/15 text-amber-300'
                          : 'bg-white/[0.06] text-slate-400'
                      }`}>
                        {e.reason}
                      </span>
                      {e.kind && (
                        <span className="text-slate-300">
                          <span className="text-slate-500">{e.kind}/</span>{e.name}
                        </span>
                      )}
                      {e.count > 1 && <span className="text-[10px] text-slate-600">×{e.count}</span>}
                      {(e.age || e.last_timestamp) && (
                        <span className="text-[10px] text-slate-600 ml-auto">
                          {e.age ? `${e.age} önce` : e.last_timestamp}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1 break-words">{e.message}</p>
                  </div>
                ))
              )}
            </div>
          )}

          {tab === 'yaml' && (
            <div className="space-y-2">
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => refetchYaml()}
                  className="text-[11px] text-rose-300 flex items-center gap-1"
                >
                  <RefreshCw size={11} className={yamlLoading ? 'animate-spin' : ''} /> {t('refresh_action')}
                </button>
              </div>
              <pre className="bg-[#0a0f1a] border border-white/[0.08] rounded-lg p-3 text-[10px] text-cyan-100/90 overflow-auto max-h-[36rem] whitespace-pre font-mono">
                {yamlLoading ? '…' : (yamlData?.yaml || yamlData?.error || '—')}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
