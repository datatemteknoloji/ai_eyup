import React, { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Workflow, Plus, Pencil, Trash2, PlugZap, Search, Play, RotateCcw, Check, X, ChevronLeft, ChevronRight,
  AlertTriangle, CheckCircle2, Loader2, ArrowRight, Info, BookOpen, ChevronDown,
} from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import { apiGet, apiSend, type AutomationStatus, type AutomicSystem } from './api'
import { AutomicInfoButton, Card, ErrorNote, fmtAgo, fmtDateTime, fmtDuration, fmtNumber, NoticeBox } from './ui'

type Profiles = {
  source_types: { id: string; label: string; available: boolean }[]
  sql_profiles: Record<string, string[]>
  defaults: Record<string, any>
  limits: { path: string; min: number; max: number }[]
}

type Projection = {
  executions_hot_gb: number; executions_compressed_gb: number; report_excerpts_gb: number
  failed_index_gb: number; daily_aggregates_gb: number; estimated_db_gb: number
  quota_gb: number; min_disk_gb: number; fits: boolean; prune_threshold_gb: number
}

type TestResult = {
  ok: boolean
  message: string
  db_version?: string | null
  driver_mode?: string | null
  latency_ms?: number | null
  warnings?: string[]
  details?: Record<string, any>
  capability?: Record<string, any>
  discover_error?: string
}

type Form = {
  id?: number
  name: string
  source_type: string
  connection: Record<string, any>
  password: string
  has_secret: boolean
  clients: number[]
  settings: Record<string, any>
  is_default: boolean
  enabled: boolean
  primary_ack: boolean
}

const DAY_LABELS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v))
}

function deepMerge(base: any, over: any): any {
  if (!over || typeof over !== 'object' || Array.isArray(over)) return over ?? base
  const out: any = { ...(base ?? {}) }
  for (const [k, v] of Object.entries(over)) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && base?.[k] && typeof base[k] === 'object'
      ? deepMerge(base[k], v) : v
  }
  return out
}

function getPath(obj: any, path: string): any {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj)
}

function setPath(obj: any, path: string, value: any): any {
  const keys = path.split('.')
  const out = clone(obj ?? {})
  let cur = out
  keys.slice(0, -1).forEach(k => {
    if (cur[k] == null || typeof cur[k] !== 'object') cur[k] = {}
    cur = cur[k]
  })
  cur[keys[keys.length - 1]] = value
  return out
}

function rangesToText(r: number[][] | undefined): string {
  return (r ?? []).map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(', ')
}

function textToRanges(t: string): number[][] {
  return t.split(',').map(s => s.trim()).filter(Boolean).map(s => {
    const [a, b] = s.split('-').map(x => Number(x.trim()))
    return [a, Number.isFinite(b) ? b : a]
  }).filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b))
}

function codesToText(c: number[] | undefined): string {
  return (c ?? []).join(', ')
}

function textToCodes(t: string): number[] {
  return t.split(',').map(s => Number(s.trim())).filter(n => Number.isFinite(n) && n > 0)
}

const inputCls = 'w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40'

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-slate-500">{hint}</span>}
    </label>
  )
}

const STEP_LABELS: Record<string, string> = {
  ingest: 'Yeni kayıt alımı', active: 'Aktif anlık görüntü', reports: 'Rapor kırpıntıları', refresh: 'Durum güncelleme',
  resync: 'Yeniden eşitleme', users: 'Kullanıcı çözümü', infra: 'Altyapı', gap: 'Boşluk tespiti', jpp: 'JPP',
  script: 'Script', reconcile: 'Uzlaştırma', backfill: 'Geçmiş doldurma',
}

function reportCoverageText(c: any): string {
  if (!c) return '—'
  if (c.unavailable) return 'bu bilgi alınamadı'
  const pct = c.coverage_pct != null ? `%${String(c.coverage_pct).replace('.', ',')}` : '—'
  const extra = [
    c.pending_report ? `${fmtNumber(c.pending_report)} toplanmayı bekliyor` : '',
    c.report_unavailable ? `${fmtNumber(c.report_unavailable)} için kaynakta rapor alınamadı` : '',
  ].filter(Boolean).join(' · ')
  return `${pct} — ${fmtNumber(c.with_report)}/${fmtNumber(c.failed_total)} hatalı çalışmada rapor var${extra ? ` · ${extra}` : ''}`
}

function reportQueueText(q: any): string {
  if (!q) return '—'
  return `bekleyen ${fmtNumber(q.pending)} · yeniden denenecek ${fmtNumber(q.retrying)} · rapor alınamadı ${fmtNumber(q.unavailable)}`
}

function overrunText(o: Record<string, number> | null | undefined): string {
  const e = Object.entries(o || {})
  if (!e.length) return 'yok'
  return e.map(([k, n]) => `${STEP_LABELS[k] ?? k}: ${n}`).join(' · ')
}

function errorCountText(c: any): string {
  if (!c) return '—'
  return c.total ? `${fmtNumber(c.total)} (${(c.components || []).length} bileşen)` : 'yok'
}

function StepMetricsTable({ metrics }: { metrics: any }) {
  const last = metrics?.last as Record<string, any> | undefined
  if (!last || !Object.keys(last).length) return null
  const rows = Object.entries(last).sort((a, b) => (b[1]?.duration_sec ?? 0) - (a[1]?.duration_sec ?? 0))
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] font-medium text-fg-muted">Son toplama turu — adım süreleri</div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-fg-muted">
            <th className="py-0.5 pr-2 font-normal">Adım</th>
            <th className="py-0.5 pr-2 font-normal">Süre / bütçe</th>
            <th className="py-0.5 pr-2 font-normal">Kayıt</th>
            <th className="py-0.5 font-normal">Durum</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, m]) => (
            <tr key={k} className="border-t border-border/40">
              <td className="py-0.5 pr-2">{STEP_LABELS[k] ?? k}</td>
              <td className="py-0.5 pr-2 tabular-nums">{Number(m.duration_sec ?? 0).toFixed(1)} sn / {Number(m.budget_sec ?? 0).toFixed(0)} sn</td>
              <td className="py-0.5 pr-2 tabular-nums">{fmtNumber(m.items)}</td>
              <td className="py-0.5">{m.error ? <span className="text-red-400">hata: {String(m.error).slice(0, 60)}</span> : m.overrun ? <span className="text-amber-400">bütçe aşıldı — kaldığı yerden sürer</span> : 'tamam'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ErrorCountersList({ counters }: { counters: any }) {
  const comps = (counters?.components || []).slice(0, 5)
  if (!comps.length) return null
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] font-medium text-fg-muted">Yutulan hatalar (en sık 5 bileşen)</div>
      <ul className="space-y-0.5 text-[11px]">
        {comps.map((c: any) => (
          <li key={c.component} className="flex gap-2">
            <span className="tabular-nums text-amber-400">{fmtNumber(c.count)}×</span>
            <span className="font-mono">{c.component}</span>
            <span className="truncate text-fg-muted">{c.last_msg}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function AutomicIntegrationPage() {
  const qc = useQueryClient()
  const { user, hasModule } = useAuth()
  const canManage = !!user && (user.role === 'admin' || (user.role === 'operator' && hasModule('integrations')))
  const [editing, setEditing] = useState<Form | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState<{ tone: string; text: string } | null>(null)

  const status = useQuery({ queryKey: ['automic-status'], queryFn: () => apiGet<AutomationStatus>('/status'), refetchInterval: 30_000 })
  const systems = useQuery({
    queryKey: ['automic-systems'],
    queryFn: () => apiGet<AutomicSystem[]>('/systems'),
    enabled: status.data?.db_available === true,
  })
  const profiles = useQuery({ queryKey: ['automic-profiles'], queryFn: () => apiGet<Profiles>('/profiles'), staleTime: Infinity })

  const healthById = useMemo(() => Object.fromEntries((status.data?.systems ?? []).map(s => [s.system_id, s])), [status.data])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['automic-status'] })
    qc.invalidateQueries({ queryKey: ['automic-systems'] })
  }

  const act = async (key: string, fn: () => Promise<any>, ok: (r: any) => string) => {
    setBusy(key)
    setActionMsg(null)
    try {
      const r = await fn()
      setActionMsg({ tone: r?.ok === false ? 'warning' : 'ok', text: ok(r) })
      refresh()
    } catch (e: any) {
      setActionMsg({ tone: 'critical', text: e?.message || 'İşlem başarısız' })
    } finally {
      setBusy(null)
    }
  }

  const startNew = () => {
    if (!profiles.data) return
    setEditing({
      name: '', source_type: 'db_oracle',
      connection: { port: 1521, driver_mode: 'auto', profile: profiles.data.sql_profiles.oracle?.[0] ?? 'ae-24', timestamps: 'auto' },
      password: '', has_secret: false, clients: [], settings: clone(profiles.data.defaults), is_default: (systems.data ?? []).length === 0, enabled: true, primary_ack: false,
    })
  }

  const startEdit = (s: AutomicSystem) => {
    if (!profiles.data) return
    setEditing({
      id: s.id, name: s.name, source_type: s.source_type, connection: clone(s.connection ?? {}), password: '',
      has_secret: s.has_secret, clients: [...s.clients], settings: deepMerge(profiles.data.defaults, s.settings ?? {}),
      is_default: s.is_default, enabled: s.enabled, primary_ack: !!(s as any).source_info?.primary_ack,
    })
  }

  if (editing && profiles.data) {
    return (
      <Wizard
        initial={editing}
        profiles={profiles.data}
        fakeAllowed={!!status.data?.fake}
        onCancel={() => setEditing(null)}
        onSaved={msg => { setEditing(null); setActionMsg({ tone: 'ok', text: msg }); refresh() }}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Workflow size={18} /></div>
          <div>
            <h1 className="text-lg font-semibold text-white">UC4 Automic Entegrasyonu</h1>
            <p className="text-xs text-slate-500">UC4 Automic kaynak veritabanından (kurulumda verdiğiniz bağlantı) salt okunur çalışma ve hata verisi toplar. Automic&apos;e yazma yapılmaz.</p>
          </div>
        </div>
        <div className="ml-auto flex gap-2">
          <AutomicInfoButton systemId={systems.data?.[0]?.id} />
          <Link to="/automation" className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:text-white">
            Genel bakış <ArrowRight size={14} />
          </Link>
          {canManage && status.data?.db_available && (
            <button type="button" onClick={startNew} disabled={!profiles.data}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50">
              <Plus size={14} /> Sistem ekle
            </button>
          )}
        </div>
      </div>

      {status.error ? <ErrorNote error={status.error} /> : null}
      {status.data && !status.data.db_available && (
        <NoticeBox tone="critical" text="Automic modül veritabanına erişilemiyor. automic_db konteynerinin çalıştığını ve AUTOMIC_DB_* ortam değişkenlerini kontrol edin." />
      )}
      {actionMsg && <NoticeBox tone={actionMsg.tone} text={actionMsg.text} />}
      {!canManage && <p className="text-xs text-slate-500">Sistem eklemek/düzenlemek için 'integrations' modülü ve en az operator rolü gerekir.</p>}

      <AutomicSetupGuide systemId={systems.data?.[0]?.id} />

      {status.data?.quota && (
        <Card title="Depolama">
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span className="text-slate-400">Kullanım <strong className="text-white">{(status.data.quota.used_bytes / 1e9).toFixed(2)} GB</strong> / {status.data.quota.quota_gb} GB</span>
            <div className="h-2 w-60 overflow-hidden rounded-full bg-slate-700">
              <div className={`h-full ${status.data.quota.level === 'ok' ? 'bg-green-500' : status.data.quota.level === 'warn' ? 'bg-amber-500' : 'bg-red-500'}`}
                style={{ width: `${Math.min(100, status.data.quota.usage_pct)}%` }} />
            </div>
            <span className="text-slate-400">%{status.data.quota.usage_pct} · seviye <strong className="text-white">{status.data.quota.level}</strong></span>
            <span className="text-slate-500">eşikler: uyarı %{status.data.quota.thresholds.warn_pct} · budama %{status.data.quota.thresholds.prune_pct} · kritik %{status.data.quota.thresholds.critical_pct}</span>
          </div>
        </Card>
      )}

      {systems.data && systems.data.length === 0 && (
        <Card><p className="py-6 text-center text-sm text-slate-400">Henüz Automic sistemi tanımlı değil.{canManage ? ' "Sistem ekle" ile başlayın.' : ''}</p></Card>
      )}

      <div className="grid gap-3 xl:grid-cols-2">
        {(systems.data ?? []).map(s => {
          const h = healthById[s.id]
          const cap = s.capability_summary
          return (
            <Card key={s.id}
              title={(
                <span className="flex items-center gap-2">
                  {s.name}
                  {s.is_default && <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-300">varsayılan</span>}
                  {!s.enabled && <span className="rounded bg-slate-600/40 px-1.5 py-0.5 text-[10px] text-slate-300">devre dışı</span>}
                  {s.source_type === 'fake' && <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">fake</span>}
                </span>
              )}
              actions={canManage ? (
                <div className="flex gap-1">
                  <IconBtn title="Bağlantı testi" busy={busy === `test-${s.id}`} onClick={() => act(`test-${s.id}`, () => apiSend(`/systems/${s.id}/test`, 'POST'), r => r.message)}><PlugZap size={14} /></IconBtn>
                  <IconBtn title="Keşfi yenile" busy={busy === `disc-${s.id}`} onClick={() => act(`disc-${s.id}`, () => apiSend(`/systems/${s.id}/discover`, 'POST'), r => `Keşif tamamlandı${r?.warnings?.length ? ` — ${r.warnings.length} uyarı` : ''}.`)}><Search size={14} /></IconBtn>
                  <IconBtn title="Şimdi topla" busy={busy === `col-${s.id}`} onClick={() => act(`col-${s.id}`, () => apiSend(`/systems/${s.id}/collect`, 'POST'), r => r.skipped === 'outside_window' ? 'Şu an toplama penceresi dışında; toplama yapılmadı.' : r.ok ? `Toplama tamamlandı: ${fmtNumber(r.rows)} satır, ${fmtNumber(r.failed)} hatalı, ${fmtNumber(r.reports)} rapor.` : `Toplama yapılamadı: ${r.error || r.skipped || 'bilinmeyen neden'}`)}><Play size={14} /></IconBtn>
                  {h && h.circuit_open_sec > 0 && (
                    <IconBtn title="Devre kesiciyi sıfırla" busy={busy === `cb-${s.id}`} onClick={() => act(`cb-${s.id}`, () => apiSend(`/systems/${s.id}/circuit/reset`, 'POST'), () => 'Devre kesici sıfırlandı.')}><RotateCcw size={14} /></IconBtn>
                  )}
                  <IconBtn title="Düzenle" onClick={() => startEdit(s)}><Pencil size={14} /></IconBtn>
                  <IconBtn title="Sil" onClick={() => {
                    if (!window.confirm(`"${s.name}" sistemi silinsin mi?`)) return
                    const purge = window.confirm('Toplanmış çalışma verileri de silinsin mi? (İptal = veriler kalsın)')
                    void act(`del-${s.id}`, () => apiSend(`/systems/${s.id}?purge=${purge}`, 'DELETE'), () => `Sistem silindi${purge ? ' (veriler dahil)' : ''}.`)
                  }}><Trash2 size={14} /></IconBtn>
                </div>
              ) : null}
            >
              <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
                <KV k="Kaynak" v={s.source_type === 'fake' ? 'Sahte kaynak' : `${s.connection.host ?? s.connection.dsn ?? '—'}${s.connection.port ? `:${s.connection.port}` : ''} / ${s.connection.service_name ?? s.connection.sid ?? '—'}`} />
                <KV k="Kullanıcı" v={s.connection.user ?? '—'} />
                <KV k="Client'lar" v={s.clients.join(', ') || '—'} />
                <KV k="Veritabanı" v={cap ? `${cap.db_version ?? '—'} · ${h?.database_role_display ?? cap.database_role_display ?? cap.database_role ?? 'bilinmiyor'}` : 'keşif yapılmadı'} />
                <KV k="Son toplama" v={h?.last_success_at ? `${fmtAgo(h.last_success_at)} · ${fmtNumber(h.last_rows)} satır` : '—'} />
                <KV k="Son yeni kayıt" v={(h as any)?.last_new_record_at ? fmtDateTime((h as any).last_new_record_at) : '—'} />
                <KV k="Kaynak gecikmesi" v={h?.source_lag_sec != null ? fmtDuration(h.source_lag_sec) : '—'} />
                <KV k="Canlı okuma" v={`${h?.live_read_mode ?? 'off'}${(h as any)?.live_read_metrics ? ` · ok ${(h as any).live_read_metrics.live_reads_ok_60m ?? 0}/60dk · red ${(h as any).live_read_metrics.live_reads_denied_60m ?? 0}` : ''}`} />
                <KV k="Sonraki toplama" v={fmtDateTime(h?.next_run_at)} />
                <KV k="Aralık" v={h ? `${h.interval_min} dk` : '—'} />
                <KV k="Rapor kapsamı (7 gün)" v={reportCoverageText((h as any)?.report_coverage)} />
                <KV k="Rapor kuyruğu" v={reportQueueText((h as any)?.report_queue)} />
                <KV k="Bütçe aşımı (24 sa)" v={overrunText((h as any)?.step_overruns_24h)} />
                <KV k="Yutulan hata sayacı" v={errorCountText((h as any)?.error_counters)} />
              </dl>
              <StepMetricsTable metrics={(h as any)?.step_metrics} />
              <ErrorCountersList counters={(h as any)?.error_counters} />
              {h?.role_drift && h.role_drift_message && (
                <div className="mt-2"><NoticeBox tone="warning" text={h.role_drift_message} /></div>
              )}
              {h?.last_error && <div className="mt-2"><NoticeBox tone="critical" text={h.last_error} /></div>}
              {(h as any)?.ingest_stall_warning && (
                <div className="mt-2"><NoticeBox tone="critical" text={(h as any).ingest_stall_warning} /></div>
              )}
              {h && h.circuit_open_sec > 0 && <div className="mt-2"><NoticeBox tone="warning" text={`Devre kesici açık — ${fmtDuration(h.circuit_open_sec)} sonra yeniden denenecek.`} /></div>}
              {cap?.warnings && cap.warnings.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-[11px] text-amber-300/90">
                  {cap.warnings.slice(0, 5).map(w => <li key={w} className="flex gap-1"><AlertTriangle size={11} className="mt-0.5 flex-shrink-0" />{w}</li>)}
                </ul>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500 whitespace-nowrap">{k}</dt>
      <dd className="text-right text-slate-200 break-all">{v}</dd>
    </div>
  )
}

function IconBtn({ title, onClick, busy, children }: { title: string; onClick: () => void; busy?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" title={title} onClick={onClick} disabled={busy}
      className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white disabled:opacity-50">
      {busy ? <Loader2 size={14} className="animate-spin" /> : children}
    </button>
  )
}

// ── Sihirbaz ───────────────────────────────────────────────────────────────

const STEPS = [
  'Kaynak tipi', 'Bağlantı', 'Test ve keşif', "Client'lar", 'Toplama zamanı', 'Kaynak koruması',
  'Durum sınıfları', 'Rapor alıntıları', 'Saklama', 'Depolama ve projeksiyon', 'Maskeleme', 'Genel', 'Özet',
]

function Wizard({ initial, profiles, fakeAllowed, onCancel, onSaved }: {
  initial: Form
  profiles: Profiles
  fakeAllowed: boolean
  onCancel: () => void
  onSaved: (msg: string) => void
}) {
  const [f, setF] = useState<Form>(initial)
  const [step, setStep] = useState(0)
  const [test, setTest] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newClient, setNewClient] = useState('')

  const conn = (k: string) => f.connection[k] ?? ''
  const setConn = (k: string, v: any) => setF(p => ({ ...p, connection: { ...p.connection, [k]: v } }))
  const st = (path: string) => getPath(f.settings, path)
  const setSt = (path: string, v: any) => setF(p => ({ ...p, settings: setPath(p.settings, path, v) }))
  const limit = (path: string) => profiles.limits.find(l => l.path === path)

  const num = (path: string, label: string, hint?: string, step = 1) => {
    const l = limit(path)
    return (
      <Field label={label} hint={[hint, l ? `aralık ${l.min}–${l.max}` : null].filter(Boolean).join(' · ') || undefined}>
        <input type="number" step={step} min={l?.min} max={l?.max} value={st(path) ?? ''}
          onChange={e => setSt(path, e.target.value === '' ? null : Number(e.target.value))} className={inputCls} />
      </Field>
    )
  }

  const isFake = f.source_type === 'fake'
  const clientsSeen: { client: number; count_24h: number; failed_24h: number }[] = test?.capability?.clients_seen ?? []
  const userLower = String(conn('user')).trim().toLowerCase()
  const masterUser = ['master', 'uc4', 'system', 'sys'].includes(userLower)

  const runTest = async () => {
    setTesting(true)
    setTest(null)
    try {
      const r = await apiSend<TestResult>('/systems/test', 'POST', {
        source_type: f.source_type, connection: f.connection, password: f.password || null, system_id: f.id ?? null, discover: true,
      })
      setTest(r)
      if (r.ok && f.clients.length === 0 && r.capability?.clients_seen?.length) {
        const seen = (r.capability.clients_seen as { client: number }[]).map(c => c.client).filter(c => c !== 0)
        setF(p => ({ ...p, clients: seen }))
      }
    } catch (e: any) {
      setTest({ ok: false, message: e?.message || 'Test başarısız' })
    } finally {
      setTesting(false)
    }
  }

  const runProjection = async () => {
    try {
      setProjection(await apiSend<Projection>('/projection', 'POST', { settings: f.settings }))
    } catch (e: any) {
      setError(e?.message)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = {
      name: f.name.trim(), source_type: f.source_type, connection: f.connection,
      password: f.password || undefined, clients: f.clients, settings: f.settings, is_default: f.is_default, enabled: f.enabled,
      primary_ack: f.primary_ack,
    }
    try {
      if (f.id) {
        await apiSend(`/systems/${f.id}`, 'PUT', body)
        onSaved(`"${body.name}" güncellendi.`)
      } else {
        const created = await apiSend<AutomicSystem>('/systems', 'POST', body)
        if (!isFake) await apiSend(`/systems/${created.id}/discover`, 'POST').catch(() => null)
        onSaved(`"${body.name}" eklendi. İlk toplama zamanlayıcı tarafından birkaç dakika içinde başlatılır; hemen başlatmak için "Şimdi topla" düğmesini kullanabilirsiniz.`)
      }
    } catch (e: any) {
      setError(e?.message || 'Kaydedilemedi')
    } finally {
      setSaving(false)
    }
  }

  const stepError = (): string | null => {
    if (step === 1 && !isFake) {
      if (!conn('dsn') && !conn('host')) return 'Host veya DSN gerekli.'
      if (!conn('dsn') && !conn('service_name') && !conn('sid')) return 'Service name veya SID gerekli.'
      if (!conn('user')) return 'Kullanıcı gerekli.'
      if (masterUser) return 'Uygulama/sistem kullanıcısı kullanılamaz; salt okunur servis kullanıcısı tanımlayın.'
      if (!f.password && !f.has_secret) return 'Şifre gerekli.'
    }
    if (step === 2 && test?.details?.requires_primary_ack && !f.primary_ack) {
      return 'PRIMARY kaynak için açık onay gerekli.'
    }
    if (step === 3 && f.clients.length === 0) return 'En az bir client seçin.'
    if (step === 11 && !f.name.trim()) return 'Sistem adı gerekli.'
    if (test?.details?.requires_primary_ack && !f.primary_ack) return 'PRIMARY kaynak için açık onay gerekli.'
    return null
  }
  const err = stepError()

  const windowsEditor = (path: string, emptyText: string) => {
    const list: { days?: number[]; from: string; to: string }[] = st(path) ?? []
    const update = (i: number, patch: Partial<{ days: number[]; from: string; to: string }>) =>
      setSt(path, list.map((w, j) => (j === i ? { ...w, ...patch } : w)))
    return (
      <div className="space-y-2">
        {list.length === 0 && <p className="text-xs text-slate-500">{emptyText}</p>}
        {list.map((w, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-700/60 p-2">
            <div className="flex gap-1">
              {DAY_LABELS.map((d, di) => {
                const on = !w.days?.length || w.days.includes(di)
                return (
                  <button key={d} type="button"
                    onClick={() => {
                      const cur = w.days?.length ? w.days : [0, 1, 2, 3, 4, 5, 6]
                      const next = cur.includes(di) ? cur.filter(x => x !== di) : [...cur, di].sort()
                      update(i, { days: next.length === 7 ? [] : next })
                    }}
                    className={`rounded px-1.5 py-0.5 text-[11px] ${on ? 'bg-blue-600/30 text-blue-200' : 'bg-slate-800 text-slate-500'}`}>{d}</button>
                )
              })}
            </div>
            <input type="time" value={w.from} onChange={e => update(i, { from: e.target.value })} className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-white" style={{ colorScheme: 'dark' }} />
            <span className="text-xs text-slate-500">–</span>
            <input type="time" value={w.to} onChange={e => update(i, { to: e.target.value })} className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-white" style={{ colorScheme: 'dark' }} />
            <button type="button" onClick={() => setSt(path, list.filter((_, j) => j !== i))} className="ml-auto text-slate-500 hover:text-red-400"><X size={14} /></button>
          </div>
        ))}
        <button type="button" onClick={() => setSt(path, [...list, { days: [], from: '00:00', to: '23:59' }])}
          className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200"><Plus size={12} /> Aralık ekle</button>
      </div>
    )
  }

  const body = (() => {
    switch (step) {
      case 0:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Automic verisinin okunacağı kaynak bağlantısı. Bu sürümde Oracle Automic kaynak DB desteklenir; kaynak türü (primary/standby/kopya) varsayılmaz.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {[...profiles.source_types, ...(fakeAllowed ? [{ id: 'fake', label: 'Sahte kaynak (geliştirme)', available: true }] : [])].map(t => (
                <button key={t.id} type="button" disabled={!t.available || !!f.id}
                  onClick={() => setF(p => ({ ...p, source_type: t.id, connection: t.id === 'fake' ? { fake_clients: [100, 200, 300] } : p.connection }))}
                  className={`rounded-xl border p-3 text-left text-sm transition-colors ${f.source_type === t.id ? 'border-blue-500/60 bg-blue-500/10 text-white' : 'border-slate-700 text-slate-300 hover:border-slate-500'} disabled:opacity-40`}>
                  <div className="font-medium">{t.label}</div>
                  {!t.available && <div className="text-[11px] text-slate-500">ileriki sürüm</div>}
                </button>
              ))}
            </div>
            {f.id && <p className="text-[11px] text-slate-500">Kayıtlı sistemde kaynak tipi değiştirilemez.</p>}
          </div>
        )
      case 1:
        if (isFake) return <p className="text-sm text-slate-400">Sahte kaynak için bağlantı bilgisi gerekmez.</p>
        return (
          <div className="space-y-4">
            <NoticeBox tone="info" text="Salt okunur bir servis kullanıcısı kullanın (yalnızca SELECT yetkisi). Automic uygulama kullanıcısı (ör. master/UC4) reddedilir. Şifre şifrelenmiş olarak saklanır ve hiçbir yerde gösterilmez." />
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Host"><input value={conn('host')} onChange={e => setConn('host', e.target.value)} placeholder="ae-db.kurum.local" className={inputCls} /></Field>
              <Field label="Port"><input type="number" value={conn('port')} onChange={e => setConn('port', e.target.value ? Number(e.target.value) : '')} className={inputCls} /></Field>
              <Field label="Protokol">
                <select value={conn('protocol') || 'tcp'} onChange={e => setConn('protocol', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }}>
                  <option value="tcp">TCP</option><option value="tcps">TCPS (TLS)</option>
                </select>
              </Field>
              <Field label="Service name"><input value={conn('service_name')} onChange={e => setConn('service_name', e.target.value)} className={inputCls} /></Field>
              <Field label="SID" hint="Service name yoksa"><input value={conn('sid')} onChange={e => setConn('sid', e.target.value)} className={inputCls} /></Field>
              <Field label="DSN / TNS" hint="Doluysa host/port/service yerine kullanılır"><input value={conn('dsn')} onChange={e => setConn('dsn', e.target.value)} className={inputCls} /></Field>
              <Field label="Kullanıcı"><input value={conn('user')} onChange={e => setConn('user', e.target.value)} autoComplete="off" className={inputCls} /></Field>
              <Field label="Şifre" hint={f.has_secret ? 'Boş bırakılırsa kayıtlı şifre kullanılır' : undefined}>
                <input type="password" value={f.password} onChange={e => setF(p => ({ ...p, password: e.target.value }))} autoComplete="new-password" className={inputCls} />
              </Field>
              <Field label="Şema sahibi" hint="Boş = keşifte bulunur"><input value={conn('schema')} onChange={e => setConn('schema', e.target.value.toUpperCase())} className={inputCls} /></Field>
              <Field label="Sürücü modu" hint="auto: önce thin, gerekirse thick (Oracle Client)">
                <select value={conn('driver_mode') || 'auto'} onChange={e => setConn('driver_mode', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }}>
                  <option value="auto">auto</option><option value="thin">thin</option><option value="thick">thick</option>
                </select>
              </Field>
              <Field label="SQL profili" hint="AE sürümüne göre tablo/kolon eşlemesi">
                <select value={conn('profile') || 'ae-24'} onChange={e => setConn('profile', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }}>
                  {(profiles.sql_profiles.oracle ?? []).map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </Field>
              <Field label="Zaman damgaları" hint="auto: keşifte belirlenir">
                <select value={conn('timestamps') || 'auto'} onChange={e => setConn('timestamps', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }}>
                  <option value="auto">auto</option><option value="utc">UTC</option><option value="local">Yerel saat</option>
                </select>
              </Field>
              {conn('timestamps') === 'local' && (
                <Field label="DB saat dilimi"><input value={conn('db_timezone')} onChange={e => setConn('db_timezone', e.target.value)} placeholder="Europe/Istanbul" className={inputCls} /></Field>
              )}
              <Field label="Bağlantı zaman aşımı (sn)"><input type="number" value={conn('connect_timeout_sec') || 10} onChange={e => setConn('connect_timeout_sec', Number(e.target.value))} className={inputCls} /></Field>
            </div>
          </div>
        )
      case 2:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Bağlantıyı dener, ardından tablo/kolon eşlemesi, yetkiler (yazma yetkisi olmamalı), indeksler, veritabanı rolü ve client'lar keşfedilir.</p>
            <button type="button" onClick={runTest} disabled={testing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-60">
              {testing ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />} Bağlantıyı test et ve keşfet
            </button>
            {test && (
              <div className="space-y-2">
                <NoticeBox tone={test.ok ? 'ok' : 'critical'} text={test.message} />
                {test.ok && (
                  <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                    <KV k="Sürüm" v={test.db_version ?? '—'} />
                    <KV k="Sürücü" v={test.driver_mode ?? '—'} />
                    <KV k="Gecikme" v={test.latency_ms != null ? `${Math.round(test.latency_ms)} ms` : '—'} />
                    <KV k="Veritabanı rolü" v={test.details?.database_role_display ?? test.capability?.database_role ?? 'bilinmiyor'} />
                    <KV k="Open mode" v={test.details?.open_mode_display ?? test.capability?.open_mode ?? 'bilinmiyor'} />
                    {test.capability && <>
                      <KV k="Şema" v={test.capability.schema ?? '—'} />
                      <KV k="Zaman damgaları" v={test.capability.timestamps ?? '—'} />
                      <KV k="Salt okunur" v={test.capability.read_only_ok ? 'evet' : 'HAYIR — yazma yetkisi var'} />
                    </>}
                  </dl>
                )}
                {test.details?.requires_primary_ack && (
                  <label className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                    <input type="checkbox" checked={f.primary_ack} onChange={e => setF(p => ({ ...p, primary_ack: e.target.checked }))} className="mt-0.5" />
                    <span>
                      Canlı primary veritabanı; sorgular Automic performansını etkileyebilir.
                      Kurulumu tamamlamak için bu riski kabul ettiğimi onaylıyorum.
                    </span>
                  </label>
                )}
                {test.capability?.features && (
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(test.capability.features).map(([k, v]) => (
                      <span key={k} className={`rounded px-1.5 py-0.5 text-[10px] ${v === true || (typeof v === 'string' && v !== 'unavailable') ? 'bg-green-500/10 text-green-300' : 'bg-slate-700/50 text-slate-500'}`}>{k}</span>
                    ))}
                  </div>
                )}
                {[...(test.warnings ?? []), ...((test.capability?.warnings as string[]) ?? [])].map(w => <NoticeBox key={w} tone="warning" text={w} />)}
                {test.discover_error && <NoticeBox tone="warning" text={`Keşif: ${test.discover_error}`} />}
              </div>
            )}
          </div>
        )
      case 3:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">İzlenecek Automic client'ları (AE içindeki mantıksal ortamlar). Client 0 yönetim client'ıdır; gerekmedikçe seçmeyin.</p>
            {clientsSeen.length > 0 ? (
              <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {clientsSeen.map(c => (
                  <label key={c.client} className="flex items-center gap-2 rounded-lg border border-slate-700/60 px-3 py-2 text-xs">
                    <input type="checkbox" checked={f.clients.includes(c.client)}
                      onChange={e => setF(p => ({ ...p, clients: e.target.checked ? [...p.clients, c.client].sort((a, b) => a - b) : p.clients.filter(x => x !== c.client) }))} />
                    <span className="font-mono text-white">{c.client}</span>
                    <span className="ml-auto text-slate-500">24s: {fmtNumber(c.count_24h)} · hatalı {fmtNumber(c.failed_24h)}</span>
                  </label>
                ))}
              </div>
            ) : <p className="text-xs text-slate-500">Keşif sonucu yok — client numaralarını elle ekleyin veya önceki adımda testi çalıştırın.</p>}
            <div className="flex items-center gap-2">
              <input value={newClient} onChange={e => setNewClient(e.target.value.replace(/\D/g, ''))} placeholder="Client no" className="w-32 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white" />
              <button type="button" onClick={() => {
                const n = Number(newClient)
                if (newClient && !f.clients.includes(n)) setF(p => ({ ...p, clients: [...p.clients, n].sort((a, b) => a - b) }))
                setNewClient('')
              }} className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:text-white">Ekle</button>
              <div className="flex flex-wrap gap-1">
                {f.clients.map(c => (
                  <span key={c} className="inline-flex items-center gap-1 rounded bg-blue-500/15 px-2 py-0.5 font-mono text-xs text-blue-200">
                    {c}<button type="button" onClick={() => setF(p => ({ ...p, clients: p.clients.filter(x => x !== c) }))}><X size={11} /></button>
                  </span>
                ))}
              </div>
            </div>
          </div>
        )
      case 4:
        return (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              {num('collection.interval_min', 'Toplama aralığı (dk)')}
              {num('collection.max_run_minutes', 'Tek toplama en fazla (dk)')}
              {num('collection.overlap_min', 'Örtüşme (dk)', 'Geç gelen kayıtlar için geriye bakış')}
              <Field label="Saat dilimi" hint="Pencereler bu dilime göre yorumlanır">
                <input value={st('collection.timezone') ?? ''} onChange={e => setSt('collection.timezone', e.target.value)} className={inputCls} />
              </Field>
              {num('collection.backfill_days', 'Geçmiş yükleme (gün)', 'Yalnızca yoğun olmayan pencerede, saklama süresiyle sınırlı')}
              <Field label="Yoğun olmayan pencere" hint="Geçmiş yükleme ve ağır işler">
                <div className="flex items-center gap-1">
                  <input type="time" value={st('collection.heavy_window.from') ?? ''} onChange={e => setSt('collection.heavy_window.from', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }} />
                  <span className="text-slate-500">–</span>
                  <input type="time" value={st('collection.heavy_window.to') ?? ''} onChange={e => setSt('collection.heavy_window.to', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }} />
                </div>
              </Field>
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-slate-300">Toplama pencereleri</div>
              {windowsEditor('collection.windows', 'Pencere yok — 7×24 toplanır.')}
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-slate-300">Yasak aralıklar (blackout)</div>
              {windowsEditor('collection.blackout', 'Yasak aralık yok.')}
            </div>
          </div>
        )
      case 5:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Kaynak veritabanını korumak için oturum, zaman aşımı ve satır sınırları. Ardışık hatalarda devre kesici kaynağa gitmeyi geçici olarak durdurur.</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {num('source_guard.max_sessions', 'En fazla eş zamanlı oturum')}
              {num('source_guard.collector_timeout_sec', 'Toplayıcı sorgu zaman aşımı (sn)')}
              {num('source_guard.chat_timeout_sec', 'Sohbet sorgu zaman aşımı (sn)')}
              {num('source_guard.slice_minutes', 'Zaman dilimi (dk)', 'Doluysa otomatik yarıya bölünür')}
              {num('source_guard.max_rows_per_slice', 'Dilim başına en fazla satır')}
              {num('source_guard.arraysize', 'Fetch arraysize')}
              {num('source_guard.chat_max_rows', 'Sohbet en fazla satır')}
              <Field label="Devre kesici hata eşiği"><input type="number" value={st('source_guard.circuit_failures') ?? ''} onChange={e => setSt('source_guard.circuit_failures', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Devre açık kalma (sn)"><input type="number" value={st('source_guard.circuit_open_sec') ?? ''} onChange={e => setSt('source_guard.circuit_open_sec', Number(e.target.value))} className={inputCls} /></Field>
            </div>
            <div className="mt-4 space-y-3 border-t border-slate-800 pt-4">
              <p className="text-sm text-slate-400">Canlı okuma: collector dışı kaynak sorguları. Varsayılan kapalı — yalnız modül DB.</p>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Canlı okuma modu" hint="off = yok · windows_only = toplama penceresi · always = limitlerle">
                  <select value={st('source_guard.live_read_mode') ?? 'off'} onChange={e => setSt('source_guard.live_read_mode', e.target.value)} className={inputCls}>
                    <option value="off">Kapalı (varsayılan)</option>
                    <option value="windows_only">Yalnız toplama pencerelerinde</option>
                    <option value="always">Her zaman (limitlerle)</option>
                  </select>
                </Field>
                {num('source_guard.live_budget_per_min', 'Canlı okuma bütçesi (tümü / dk)', 'Varsayılan 10')}
                {num('source_guard.live_budget_per_user_per_min', 'Canlı okuma bütçesi (kullanıcı / dk)', 'Varsayılan 3')}
              </div>
            </div>
          </div>
        )
      case 6:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Automic durum kodlarının sınıflandırması. Aralıkları "1800-1899, 1700" biçiminde yazın. Varsayılan: ANY_ABEND (1800–1899), 1850/1851 iptal sayılır.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Hatalı — aralıklar"><TextList value={rangesToText(st('status_classes.failed.ranges'))} onCommit={t => setSt('status_classes.failed.ranges', textToRanges(t))} /></Field>
              <Field label="Hatalı — hariç kodlar"><TextList value={codesToText(st('status_classes.failed.exclude'))} onCommit={t => setSt('status_classes.failed.exclude', textToCodes(t))} /></Field>
              <Field label="İptal — kodlar"><TextList value={codesToText(st('status_classes.cancelled.codes'))} onCommit={t => setSt('status_classes.cancelled.codes', textToCodes(t))} /></Field>
              <Field label="Başarılı — aralıklar"><TextList value={rangesToText(st('status_classes.ok.ranges'))} onCommit={t => setSt('status_classes.ok.ranges', textToRanges(t))} /></Field>
            </div>
          </div>
        )
      case 7:
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">Hatalı çalışmaların raporlarından saklanacak alıntı. Tam rapor gerektiğinde kaynaktan okunur.</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Baştan satır"><input type="number" value={st('excerpt.head_lines') ?? ''} onChange={e => setSt('excerpt.head_lines', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Sondan satır"><input type="number" value={st('excerpt.tail_lines') ?? ''} onChange={e => setSt('excerpt.tail_lines', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Eşleşme çevresi (satır)"><input type="number" value={st('excerpt.context_lines') ?? ''} onChange={e => setSt('excerpt.context_lines', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="En fazla boyut (KB)"><input type="number" value={st('excerpt.max_kb') ?? ''} onChange={e => setSt('excerpt.max_kb', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Çalışma başına rapor"><input type="number" value={st('excerpt.max_reports_per_execution') ?? ''} onChange={e => setSt('excerpt.max_reports_per_execution', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Rapor tipleri" hint="Virgülle; boş = keşiften">
                <TextList value={(st('excerpt.report_types') ?? []).join(', ')} onCommit={t => setSt('excerpt.report_types', t.split(',').map(s => s.trim().toUpperCase()).filter(Boolean))} />
              </Field>
            </div>
            <Field label="Hata kalıpları" hint="Her satıra bir kalıp; hata imzası ve alıntı için kullanılır">
              <textarea rows={5} value={(st('excerpt.patterns') ?? []).join('\n')}
                onChange={e => setSt('excerpt.patterns', e.target.value.split('\n').map(s => s.trim()).filter(Boolean))} className={`${inputCls} font-mono text-xs`} />
            </Field>
          </div>
        )
      case 8:
        return (
          <div className="grid gap-3 sm:grid-cols-3">
            {num('retention.executions_days', 'Çalışmalar (gün)')}
            <Field label="Sıkıştırma (gün sonra)"><input type="number" value={st('retention.compress_after_days') ?? ''} onChange={e => setSt('retention.compress_after_days', Number(e.target.value))} className={inputCls} /></Field>
            {num('retention.failed_report_excerpts_days', 'Rapor alıntıları (gün)')}
            {num('retention.report_cache_hours', 'Rapor önbelleği (saat)')}
            {num('retention.failed_index_days', 'Hata dizini (gün)')}
            {num('retention.daily_aggregates_days', 'Günlük özetler (gün)')}
            {num('retention.conversations_days', 'Sohbetler (gün)')}
            {num('retention.audit_days', 'Denetim kayıtları (gün)')}
          </div>
        )
      case 9:
        return (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              {num('storage.quota_gb', 'Kota (GB)')}
              <Field label="Uyarı %"><input type="number" value={st('storage.warn_pct') ?? ''} onChange={e => setSt('storage.warn_pct', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Budama %"><input type="number" value={st('storage.prune_pct') ?? ''} onChange={e => setSt('storage.prune_pct', Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Kritik %"><input type="number" value={st('storage.critical_pct') ?? ''} onChange={e => setSt('storage.critical_pct', Number(e.target.value))} className={inputCls} /></Field>
            </div>
            <NoticeBox tone="info" text={`Modül veritabanı diski en az kota × ${st('storage.disk_overhead_factor') ?? 1.5} = ${Math.round((st('storage.quota_gb') ?? 0) * (st('storage.disk_overhead_factor') ?? 1.5))} GB olmalı (sıkıştırma, WAL ve bakım payı). Kota dolarken sırasıyla rapor önbelleği, alıntılar ve en eski çalışmalar budanır; kritik seviyede yalnız rapor alıntısı toplama durur.`} />
            <div className="rounded-xl border border-slate-700/60 p-3 space-y-3">
              <div className="text-xs font-medium text-slate-300">Depolama projeksiyonu</div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Günlük çalışma sayısı" hint="Örn. aylık 26 milyon ≈ 870.000/gün"><input type="number" value={st('projection.daily_exec') ?? ''} onChange={e => setSt('projection.daily_exec', Number(e.target.value))} className={inputCls} /></Field>
                <Field label="Hata oranı" hint="0.01 = %1"><input type="number" step="0.001" value={st('projection.failure_rate') ?? ''} onChange={e => setSt('projection.failure_rate', Number(e.target.value))} className={inputCls} /></Field>
                <Field label="Ort. alıntı (KB)"><input type="number" value={st('projection.avg_excerpt_kb') ?? ''} onChange={e => setSt('projection.avg_excerpt_kb', Number(e.target.value))} className={inputCls} /></Field>
                <Field label="Sıkıştırma oranı"><input type="number" value={st('projection.compression_ratio') ?? ''} onChange={e => setSt('projection.compression_ratio', Number(e.target.value))} className={inputCls} /></Field>
                <Field label="İndeks payı çarpanı"><input type="number" step="0.1" value={st('projection.index_overhead_factor') ?? ''} onChange={e => setSt('projection.index_overhead_factor', Number(e.target.value))} className={inputCls} /></Field>
              </div>
              <button type="button" onClick={runProjection} className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:text-white">Hesapla</button>
              {projection && (
                <div className="space-y-2">
                  <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                    <KV k="Sıcak çalışmalar" v={`${projection.executions_hot_gb} GB`} />
                    <KV k="Sıkıştırılmış" v={`${projection.executions_compressed_gb} GB`} />
                    <KV k="Rapor alıntıları" v={`${projection.report_excerpts_gb} GB`} />
                    <KV k="Hata dizini" v={`${projection.failed_index_gb} GB`} />
                    <KV k="Günlük özetler" v={`${projection.daily_aggregates_gb} GB`} />
                    <KV k="Tahmini toplam" v={<strong>{projection.estimated_db_gb} GB</strong>} />
                  </dl>
                  <NoticeBox tone={projection.fits ? 'ok' : 'warning'}
                    text={projection.fits
                      ? `Tahmini boyut budama eşiğinin (${projection.prune_threshold_gb} GB) altında. Önerilen en az disk: ${projection.min_disk_gb} GB.`
                      : `Tahmini boyut budama eşiğini (${projection.prune_threshold_gb} GB) aşıyor — kotayı artırın veya saklama sürelerini kısaltın. Önerilen en az disk: ${projection.min_disk_gb} GB.`} />
                </div>
              )}
            </div>
          </div>
        )
      case 10: {
        const pats: { name: string; regex: string }[] = st('masking.custom_patterns') ?? []
        const llmDep = (st('llm_deployment') ?? 'internal') as string
        return (
          <div className="space-y-3">
            <p className="text-sm text-slate-400">
              Şifre, token, API anahtarı ve kimlik bilgisi içeren bağlantı cümleleri her zaman maskelenir
              (LLM, modül DB, audit, UI). Automic kullanıcı adları (NAME/DEPARTMENT) maskelenmez.
              IP ve hostname varsayılan olarak gösterilir; aşağıdan kapatılabilir.
            </p>
            <Field label="LLM konumu">
              <select
                value={llmDep}
                onChange={e => setSt('llm_deployment', e.target.value)}
                className={inputCls}
                style={{ colorScheme: 'dark' }}
              >
                <option value="internal">Kurum içi (internal)</option>
                <option value="external">Harici (external)</option>
              </select>
            </Field>
            {llmDep === 'external' && (
              <NoticeBox
                tone="warning"
                text="Kullanıcı adları ve hostname'ler kişisel veya hassas veri içerebilir; harici LLM'e gönderilmeden önce kurum politikasını kontrol edin. Automic dışındaki modüllerde gizli bilgi maskelemesi uygulanmaz. Embedding yedeği (REMOTE_LLM /v1/embeddings) de dahildir — uzak sağlayıcıya düşülürse loglanır."
              />
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Ülke paketi">
                <select value={st('masking.country_pack') ?? 'tr'} onChange={e => setSt('masking.country_pack', e.target.value)} className={inputCls} style={{ colorScheme: 'dark' }}>
                  <option value="tr">Türkiye</option><option value="none">Yok (yalnız temel)</option>
                </select>
              </Field>
              <label className="flex items-center gap-2 pt-6 text-sm text-slate-300">
                <input type="checkbox" checked={!!st('masking.mask_ip')} onChange={e => setSt('masking.mask_ip', e.target.checked)} /> IP adreslerini maskele
              </label>
              <label className="flex items-center gap-2 pt-6 text-sm text-slate-300">
                <input type="checkbox" checked={!!st('masking.mask_hostname')} onChange={e => setSt('masking.mask_hostname', e.target.checked)} /> Hostname'leri maskele
              </label>
            </div>
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-300">Özel kalıplar</div>
              {pats.map((p, i) => (
                <div key={i} className="flex gap-2">
                  <input value={p.name} placeholder="ad" onChange={e => setSt('masking.custom_patterns', pats.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} className="w-40 rounded-lg border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-white" />
                  <input value={p.regex} placeholder="regex" onChange={e => setSt('masking.custom_patterns', pats.map((x, j) => j === i ? { ...x, regex: e.target.value } : x))} className="flex-1 rounded-lg border border-slate-600 bg-slate-800 px-2 py-1 font-mono text-xs text-white" />
                  <button type="button" onClick={() => setSt('masking.custom_patterns', pats.filter((_, j) => j !== i))} className="text-slate-500 hover:text-red-400"><X size={14} /></button>
                </div>
              ))}
              <button type="button" onClick={() => setSt('masking.custom_patterns', [...pats, { name: '', regex: '' }])} className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200"><Plus size={12} /> Kalıp ekle</button>
            </div>
          </div>
        )
      }
      case 11:
        return (
          <div className="space-y-3">
            {(st('llm_deployment') ?? 'internal') === 'external' && (
              <NoticeBox
                tone="warning"
                text="Kullanıcı adları ve hostname'ler kişisel veya hassas veri içerebilir; harici LLM'e gönderilmeden önce kurum politikasını kontrol edin. Automic dışındaki modüllerde gizli bilgi maskelemesi uygulanmaz. Embedding yedeği (REMOTE_LLM /v1/embeddings) de dahildir — uzak sağlayıcıya düşülürse loglanır."
              />
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Sistem adı" hint="Örn. AE-PROD, AE-TEST"><input value={f.name} onChange={e => setF(p => ({ ...p, name: e.target.value }))} className={inputCls} /></Field>
              <Field label="Automic AE sürümü" hint="Varsayılan 24.4 — otomatik tespit yok; şema doğrulaması 24.4'e göre">
                <input value={st('ae_version') ?? '24.4'} onChange={e => setSt('ae_version', e.target.value)} className={inputCls} placeholder="24.4" />
              </Field>
              <Field label="AWI adresi" hint="Bilgi amaçlı; bağlantı kurulmaz"><input value={st('awi_url') ?? ''} onChange={e => setSt('awi_url', e.target.value)} className={inputCls} /></Field>
              <div className="space-y-2 pt-5">
                <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={f.is_default} onChange={e => setF(p => ({ ...p, is_default: e.target.checked }))} /> Varsayılan sistem</label>
                <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={f.enabled} onChange={e => setF(p => ({ ...p, enabled: e.target.checked }))} /> Etkin (zamanlanmış toplama)</label>
              </div>
            </div>
            {String(st('ae_version') || '24.4').trim() !== '24.4' && (
              <NoticeBox
                tone="warning"
                text="Şema doğrulaması 24.4'e göre yapıldı. Girdiğiniz AE sürümü farklı; kolon eşlemeleri bu ortamda doğrulanmamış olabilir."
              />
            )}
          </div>
        )
      default:
        return (
          <div className="space-y-3 text-xs">
            <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              <KV k="Ad" v={f.name || '—'} />
              <KV k="Kaynak tipi" v={f.source_type} />
              {!isFake && <KV k="Bağlantı" v={`${conn('dsn') || `${conn('host')}:${conn('port')}/${conn('service_name') || conn('sid')}`}`} />}
              {!isFake && <KV k="Kullanıcı" v={conn('user')} />}
              <KV k="Şifre" v={f.password ? 'yeni şifre girildi' : f.has_secret ? 'kayıtlı' : '—'} />
              <KV k="Client'lar" v={f.clients.join(', ') || '—'} />
              <KV k="Aralık" v={`${st('collection.interval_min')} dk`} />
              <KV k="Pencereler" v={(st('collection.windows') ?? []).length ? `${st('collection.windows').length} pencere` : '7×24'} />
              <KV k="Saklama" v={`${st('retention.executions_days')} gün çalışma · ${st('retention.failed_report_excerpts_days')} gün alıntı`} />
              <KV k="Kota" v={`${st('storage.quota_gb')} GB`} />
              <KV k="LLM" v={(st('llm_deployment') ?? 'internal') === 'external' ? 'harici' : 'kurum içi'} />
              <KV k="Maskeleme" v={`${st('masking.country_pack')} · IP ${st('masking.mask_ip') ? 'maskeli' : 'açık'} · host ${st('masking.mask_hostname') ? 'maskeli' : 'açık'}`} />
              <KV k="Test" v={test ? (test.ok ? 'başarılı' : 'başarısız') : 'yapılmadı'} />
            </dl>
            {(st('llm_deployment') ?? 'internal') === 'external' && (
              <NoticeBox tone="warning" text="Kullanıcı adları ve hostname'ler kişisel veya hassas veri içerebilir; harici LLM'e gönderilmeden önce kurum politikasını kontrol edin. Automic dışındaki modüllerde gizli bilgi maskelemesi uygulanmaz. Embedding yedeği (REMOTE_LLM /v1/embeddings) de dahildir — uzak sağlayıcıya düşülürse loglanır." />
            )}
            {!test?.ok && !isFake && !f.id && <NoticeBox tone="warning" text="Bağlantı testi başarılı olmadan kaydediliyor. Toplama, bağlantı düzelene kadar hata verecektir." />}
          </div>
        )
    }
  })()

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button type="button" onClick={onCancel} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"><ChevronLeft size={14} /> Geri</button>
        <h1 className="text-lg font-semibold text-white">{f.id ? `Sistemi düzenle — ${initial.name}` : 'Yeni Automic sistemi'}</h1>
      </div>
      <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
        <nav className="space-y-0.5">
          {STEPS.map((s, i) => (
            <button key={s} type="button" onClick={() => setStep(i)}
              className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs ${i === step ? 'bg-blue-600/20 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}>
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] ${i < step ? 'bg-green-600/40 text-green-200' : i === step ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400'}`}>
                {i < step ? <Check size={10} /> : i + 1}
              </span>
              {s}
            </button>
          ))}
        </nav>
        <Card title={`${step + 1}. ${STEPS[step]}`}>
          <div className="min-h-[18rem]">{body}</div>
          {error && <div className="mt-3"><NoticeBox tone="critical" text={error} /></div>}
          {err && <p className="mt-3 flex items-center gap-1 text-xs text-amber-300"><Info size={12} /> {err}</p>}
          <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
            <button type="button" onClick={() => setStep(s => Math.max(0, s - 1))} disabled={step === 0}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-40"><ChevronLeft size={14} /> Önceki</button>
            {step < STEPS.length - 1 ? (
              <button type="button" onClick={() => setStep(s => s + 1)} disabled={!!err}
                className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50">Sonraki <ChevronRight size={14} /></button>
            ) : (
              <button type="button" onClick={save} disabled={saving || !f.name.trim() || f.clients.length === 0}
                className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-1.5 text-sm text-white hover:bg-green-500 disabled:opacity-50">
                {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Kaydet
              </button>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

function TextList({ value, onCommit }: { value: string; onCommit: (t: string) => void }) {
  const [v, setV] = useState(value)
  return <input value={v} onChange={e => setV(e.target.value)} onBlur={() => onCommit(v)} className={inputCls} />
}

/** Kısa operasyon rehberi: ne nereden + kurulum gereksinimleri */
function AutomicSetupGuide({ systemId }: { systemId?: number }) {
  const [open, setOpen] = useState(true)
  const [showReq, setShowReq] = useState(false)
  const info = useQuery({
    queryKey: ['automic-info-guide', systemId ?? 'default'],
    queryFn: () => apiGet<any>(`/info${systemId != null ? `?system_id=${systemId}` : ''}`),
    staleTime: 60_000,
  })
  const reqs: { title: string; items: { must: boolean; text: string }[] }[] = info.data?.requirements || []
  const mdb = info.data?.module_db
  const ports = info.data?.ainew_ports

  return (
    <Card
      title={
        <button type="button" onClick={() => setOpen(o => !o)} className="inline-flex w-full items-center gap-2 text-left">
          <BookOpen size={14} className="text-blue-300" />
          <span>Nasıl kullanılır? (kısa rehber)</span>
          <ChevronDown size={14} className={`ml-auto text-slate-500 transition ${open ? 'rotate-180' : ''}`} />
        </button>
      }
    >
      {open && (
        <div className="space-y-4 text-[13px] leading-relaxed text-slate-300">
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              <strong className="text-white">Sistem ekle</strong> (bu sayfa) → Oracle Automic kaynak / fake bağlantısı, client seçimi,
              toplama penceresi, kota, maskeleme. Kaydetmeden önce <em>Bağlantıyı test et</em> + keşif.
            </li>
            <li>
              Kart üzerindeki düğmeler: <strong className="text-white">test</strong> · <strong className="text-white">keşif</strong> ·
              <strong className="text-white">şimdi topla</strong> · gerekirse <strong className="text-white">devre sıfırla</strong>.
              Ayar değiştirmek için kalem ikonu (aynı sihirbaz).
            </li>
            <li>
              Veri geldikten sonra menü <strong className="text-white">UC4 Automic</strong>: Genel bakış (KPI/widget),
              Çalışmalar, Aktif işler, Nesne/Agent detay, Asistan. Ayarların çoğu yine bu entegrasyon sayfasındadır.
            </li>
            <li>
              Yetki: görüntüleme/asistan → modül <code className="text-blue-200">automation</code>;
              sistem ekle/düzenle → <code className="text-blue-200">integrations</code> + operator.
            </li>
            <li>
              Teşhis: <code className="rounded bg-slate-800 px-1 text-[11px] text-slate-200">scripts/automic-diagnose.sh</code>
              (sır yazdırmaz). (i) ikonu her sayfada davranış + gereksinim özetini açar.
            </li>
          </ol>

          <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 font-mono text-[11px] text-slate-400">
            AE Oracle (SELECT) → Collector → automic_db :{mdb?.port || '5435'} → API :{ports?.api || 8000} / UI :{ports?.ui || 3000}
          </div>

          <div>
            <button type="button" onClick={() => setShowReq(s => !s)}
              className="inline-flex items-center gap-1.5 text-xs text-blue-300 hover:text-blue-200">
              <ChevronDown size={13} className={showReq ? 'rotate-180' : ''} />
              Kurulum gereksinimleri (port, firewall, kullanıcı…)
            </button>
            {showReq && (
              <div className="mt-2 space-y-2">
                {info.isLoading && <p className="text-xs text-slate-500">Yükleniyor…</p>}
                {info.error && <ErrorNote error={info.error} />}
                {reqs.map(g => (
                  <div key={g.title} className="rounded-lg border border-slate-700/50 p-2.5">
                    <div className="mb-1.5 text-xs font-medium text-slate-200">{g.title}</div>
                    <ul className="space-y-1.5">
                      {g.items.map((it, i) => (
                        <li key={i} className="flex gap-2 text-[12px]">
                          <span className={`mt-0.5 shrink-0 rounded px-1 py-0.5 text-[10px] ${it.must ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/10 text-amber-200'}`}>
                            {it.must ? 'zorunlu' : 'öneri'}
                          </span>
                          <span>{it.text}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
