import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Copy, FileCode2, Info, ShieldOff, Wrench, RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useLocale, useT } from '../../i18n/LocaleProvider'
import { GhostButton, Modal, NEON, SeverityBadge } from '../aiops/ui'

export type InsightsBase = 'virt-insights' | 'ocp-insights'

export type Finding = {
  id: number
  platform: string
  source_id: number | null
  source_name: string | null
  category: string
  check_id: string
  entity_kind: string
  entity_ref: string
  entity_name: string
  cluster_name: string | null
  result: 'pass' | 'fail' | 'not_measurable'
  severity: string
  title: string
  detail: string | null
  evidence: Record<string, unknown> | null
  recommendation: string | null
  refs: string[] | null
  first_seen: string | null
  last_seen: string | null
  has_draft?: boolean
  exception?: { reason: string; created_by: string; expires_at: string | null } | null
}

export async function apiGet<T = any>(base: InsightsBase, path: string, locale = 'tr'): Promise<T> {
  const r = await fetch(`${API_BASE_URL}/${base}${path}`, { headers: { 'Accept-Language': locale } })
  if (!r.ok) {
    const b = await r.json().catch(() => ({}))
    throw new Error(b.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export async function apiSend<T = any>(base: InsightsBase, path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE_URL}/${base}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const b = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`)
  return b as T
}

export function useInsights<T = any>(base: InsightsBase, path: string, opts: { enabled?: boolean; refetch?: number } = {}) {
  const { locale } = useLocale()
  return useQuery<T>({
    queryKey: [base, path, locale],
    queryFn: () => apiGet<T>(base, path, locale),
    enabled: opts.enabled ?? true,
    refetchInterval: opts.refetch,
    staleTime: 30_000,
  })
}

export function useRole() {
  const { user } = useAuth() as any
  const role: string = user?.role || 'viewer'
  const isAdmin = !!(user?.is_admin || role === 'admin')
  return { isAdmin, isOperator: isAdmin || role === 'operator' }
}

export const fmt = (v: unknown, d = 1) => (typeof v === 'number' ? v.toFixed(d).replace(/\.0+$/, '') : v == null || v === '' ? '—' : String(v))

export function pctTone(v?: number | null, warn = 75, crit = 90) {
  if (v == null) return 'text-slate-400'
  if (v >= crit) return 'text-red-400'
  if (v >= warn) return 'text-amber-400'
  return 'text-emerald-400'
}

export function Panel({ title, right, children, className = '' }: {
  title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  return (
    <div className={`bg-cyber-card border border-white/[0.06] rounded-lg ${className}`}>
      {title && (
        <div className="px-4 py-3 flex items-center justify-between border-b border-white/[0.06]">
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

export function Stat({ label, value, tone = 'text-white', hint }: { label: string; value: React.ReactNode; tone?: string; hint?: string }) {
  return (
    <div className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-3" title={hint}>
      <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`text-2xl font-bold mt-0.5 font-mono ${tone}`}>{value}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-0.5 truncate">{hint}</div>}
    </div>
  )
}

export function Bar({ pct, warn = 75, crit = 90 }: { pct?: number | null; warn?: number; crit?: number }) {
  const v = Math.max(0, Math.min(100, pct ?? 0))
  const c = pct == null ? 'bg-slate-600' : v >= crit ? 'bg-red-500' : v >= warn ? 'bg-amber-500' : 'bg-blue-600'
  return (
    <div className="h-1.5 w-full rounded bg-white/[0.06] overflow-hidden">
      <div className={`h-full ${c}`} style={{ width: `${v}%` }} />
    </div>
  )
}

export function ResultBadge({ result }: { result: string }) {
  const t = useT()
  const map: Record<string, string> = {
    fail: 'bg-red-500/10 text-red-300 border-red-500/30',
    pass: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    not_measurable: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
  }
  const label = result === 'fail' ? t('vi_res_fail') : result === 'pass' ? t('vi_res_pass') : t('vi_res_nm')
  return <span className={`px-2 py-0.5 rounded border text-[11px] font-medium whitespace-nowrap ${map[result] || map.not_measurable}`}>{label}</span>
}

export function RunBar({ base, lastRun }: { base: InsightsBase; lastRun?: { finished_at?: string | null; started_at?: string | null; status?: string } | null }) {
  const t = useT()
  const { isAdmin } = useRole()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const run = async () => {
    setBusy(true); setMsg('')
    try {
      await apiSend(base, '/run', 'POST', {})
      setMsg(t('vi_run_started'))
      setTimeout(() => qc.invalidateQueries({ queryKey: [base] }), 20_000)
    } catch (e: any) {
      setMsg(e.message)
    } finally {
      setBusy(false)
    }
  }
  const ts = lastRun?.finished_at || lastRun?.started_at
  return (
    <div className="flex items-center gap-3 text-xs text-slate-400">
      {ts && <span>{t('vi_last_run')}: <span className="font-mono text-slate-300">{new Date(ts).toLocaleString()}</span>{lastRun?.status && lastRun.status !== 'ok' ? ` · ${lastRun.status}` : ''}</span>}
      {msg && <span className="text-blue-300">{msg}</span>}
      {isAdmin && (
        <GhostButton accent={NEON.blue} onClick={run} disabled={busy}>
          <span className="inline-flex items-center gap-1.5"><RefreshCw size={13} className={busy ? 'animate-spin' : ''} />{t('vi_run_now')}</span>
        </GhostButton>
      )}
    </div>
  )
}

function DraftModal({ base, finding, onClose }: { base: InsightsBase; finding: Finding; onClose: () => void }) {
  const t = useT()
  const q = useInsights<any>(base, `/findings/${finding.id}/draft`)
  const copy = (s: string) => navigator.clipboard?.writeText(s)
  return (
    <Modal title={t('vi_draft_title')} subtitle={`${finding.title} · ${finding.entity_name}`} onClose={onClose} maxWidth="max-w-3xl">
      <div className="p-5 space-y-3 text-sm">
        {q.isLoading && <div className="text-slate-400">{t('loading')}</div>}
        {q.error && <div className="text-red-300">{(q.error as Error).message}</div>}
        {q.data && (
          <>
            <div className="text-xs text-amber-300">{t('vi_draft_note')}</div>
            <div className="relative">
              <pre className="bg-black/40 border border-white/[0.06] rounded p-3 text-xs font-mono text-slate-200 whitespace-pre-wrap">{q.data.script}</pre>
              <button className="absolute top-2 right-2 text-slate-400 hover:text-white" onClick={() => copy(q.data.script)} title={t('vi_copy')}><Copy size={14} /></button>
            </div>
            {q.data.rollback && (
              <div>
                <div className="text-xs text-slate-400 mb-1">{t('vi_rollback')}</div>
                <pre className="bg-black/40 border border-white/[0.06] rounded p-3 text-xs font-mono text-slate-300 whitespace-pre-wrap">{q.data.rollback}</pre>
              </div>
            )}
            {(q.data.notes || []).map((n: string, i: number) => <div key={i} className="text-xs text-slate-400">• {n}</div>)}
          </>
        )}
      </div>
    </Modal>
  )
}

function ExceptionModal({ base, finding, onClose }: { base: InsightsBase; finding: Finding; onClose: () => void }) {
  const t = useT()
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [days, setDays] = useState('90')
  const [err, setErr] = useState('')
  const save = async () => {
    try {
      await apiSend(base, `/findings/${finding.id}/exception`, 'POST', { reason, expires_days: days ? Number(days) : null })
      qc.invalidateQueries({ queryKey: [base] })
      onClose()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Modal title={t('vi_exc_title')} subtitle={`${finding.title} · ${finding.entity_name}`} onClose={onClose}
      footer={<div className="flex justify-end gap-2"><GhostButton onClick={onClose}>{t('cancel')}</GhostButton><GhostButton accent={NEON.blue} onClick={save} disabled={reason.trim().length < 3}>{t('save')}</GhostButton></div>}>
      <div className="p-5 space-y-3 text-sm">
        <div className="text-xs text-slate-400">{t('vi_exc_hint')}</div>
        <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder={t('vi_exc_reason')}
          className="w-full rounded bg-black/30 border border-white/[0.08] p-2 text-sm text-white" />
        <label className="flex items-center gap-2 text-xs text-slate-400">{t('vi_exc_days')}
          <input value={days} onChange={e => setDays(e.target.value.replace(/\D/g, ''))} className="w-20 rounded bg-black/30 border border-white/[0.08] px-2 py-1 text-white font-mono" />
        </label>
        {err && <div className="text-red-300 text-xs">{err}</div>}
      </div>
    </Modal>
  )
}

function RemediateModal({ finding, onClose }: { finding: Finding; onClose: () => void }) {
  const t = useT()
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const propose = async () => {
    setBusy(true); setErr('')
    try { setRes(await apiSend('virt-insights', '/remediation/propose', 'POST', { finding_id: finding.id })) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <Modal title={t('vi_rem_title')} subtitle={`${finding.title} · ${finding.entity_name}`} onClose={onClose}
      footer={<div className="flex justify-end gap-2"><GhostButton onClick={onClose}>{t('close')}</GhostButton>{!res && <GhostButton accent={NEON.orange} onClick={propose} disabled={busy}>{t('vi_rem_propose')}</GhostButton>}</div>}>
      <div className="p-5 space-y-3 text-sm">
        <div className="text-xs text-slate-300">{t('vi_rem_hint')}</div>
        {err && <div className="text-red-300 text-xs">{err}</div>}
        {res && (
          <div className="space-y-2">
            <div className="text-emerald-300 text-sm">{t('vi_rem_ok', { id: res.agent_action_id })}</div>
            <div className="font-mono text-xs text-slate-300">{res.preview}</div>
            <div className="text-xs text-amber-300">{res.rollback}</div>
            <a href="/agent" className="text-blue-400 text-xs hover:underline">{t('vi_rem_goto')}</a>
          </div>
        )}
      </div>
    </Modal>
  )
}

const REMEDIABLE = new Set(['reclaim.vm.snapshot_age', 'vmw.host.ntp_running', 'vmw.host.ntp_configured', 'vmw.cluster.ntp_consistency', 'cmp.host.ssh_disabled'])

export function FindingsTable({ base, rows, showPlatform = true, emptyText }: {
  base: InsightsBase; rows: Finding[]; showPlatform?: boolean; emptyText?: string
}) {
  const t = useT()
  const { isAdmin, isOperator } = useRole()
  const qc = useQueryClient()
  const [open, setOpen] = useState<number | null>(null)
  const [draft, setDraft] = useState<Finding | null>(null)
  const [exc, setExc] = useState<Finding | null>(null)
  const [rem, setRem] = useState<Finding | null>(null)
  if (!rows.length) return <div className="py-10 text-center text-sm text-slate-500">{emptyText || t('vi_no_findings')}</div>
  const unexcept = async (f: Finding) => {
    await apiSend(base, `/findings/${f.id}/exception`, 'DELETE').catch(() => null)
    qc.invalidateQueries({ queryKey: [base] })
  }
  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
            <th className="px-3 py-2 w-6" />
            <th className="px-3 py-2">{t('vi_col_severity')}</th>
            <th className="px-3 py-2">{t('vi_col_check')}</th>
            <th className="px-3 py-2">{t('vi_col_entity')}</th>
            {showPlatform && <th className="px-3 py-2">{t('vi_col_source')}</th>}
            <th className="px-3 py-2">{t('vi_col_detail')}</th>
            <th className="px-3 py-2">{t('vi_col_result')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(f => {
            const isOpen = open === f.id
            return (
              <React.Fragment key={f.id}>
                <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer" onClick={() => setOpen(isOpen ? null : f.id)}>
                  <td className="px-3 py-2 text-slate-500">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  <td className="px-3 py-2"><SeverityBadge severity={f.severity} /></td>
                  <td className="px-3 py-2 text-white">{f.title}{f.exception && <span className="ml-2 text-[10px] text-slate-400 border border-white/10 rounded px-1">{t('vi_excepted')}</span>}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-300">{f.entity_name}{f.cluster_name && f.cluster_name !== f.entity_name ? <span className="text-slate-500"> · {f.cluster_name}</span> : null}</td>
                  {showPlatform && <td className="px-3 py-2 text-xs text-slate-400">{f.source_name} <span className="text-slate-600">({f.platform})</span></td>}
                  <td className="px-3 py-2 text-xs text-slate-400 max-w-[28rem] truncate" title={f.detail || ''}>{f.detail || '—'}</td>
                  <td className="px-3 py-2"><ResultBadge result={f.result} /></td>
                </tr>
                {isOpen && (
                  <tr className="border-b border-white/[0.04] bg-black/20">
                    <td />
                    <td colSpan={showPlatform ? 6 : 5} className="px-3 py-3 space-y-2">
                      {f.recommendation && <div className="text-xs text-slate-300"><span className="text-slate-500">{t('vi_recommendation')}: </span>{f.recommendation}</div>}
                      {f.refs && f.refs.length > 0 && <div className="text-[11px] text-slate-500">{f.refs.join(' · ')}</div>}
                      {f.evidence && Object.keys(f.evidence).length > 0 && (
                        <pre className="text-[11px] font-mono text-slate-400 bg-black/30 rounded p-2 max-h-56 overflow-auto whitespace-pre-wrap">{JSON.stringify(f.evidence, null, 2)}</pre>
                      )}
                      <div className="text-[11px] text-slate-500">{t('vi_first_seen')}: {f.first_seen ? new Date(f.first_seen).toLocaleString() : '—'} · {t('vi_last_seen')}: {f.last_seen ? new Date(f.last_seen).toLocaleString() : '—'} · <span className="font-mono">{f.check_id}</span></div>
                      {f.exception && <div className="text-xs text-slate-400">{t('vi_exc_reason')}: {f.exception.reason} ({f.exception.created_by}{f.exception.expires_at ? ` → ${new Date(f.exception.expires_at).toLocaleDateString()}` : ''})</div>}
                      <div className="flex gap-2 pt-1">
                        {base === 'virt-insights' && f.has_draft && f.result === 'fail' && (
                          <GhostButton accent={NEON.blue} onClick={() => setDraft(f)}><span className="inline-flex items-center gap-1.5"><FileCode2 size={13} />{t('vi_draft_btn')}</span></GhostButton>
                        )}
                        {base === 'virt-insights' && isOperator && f.result === 'fail' && f.platform === 'vmware' && REMEDIABLE.has(f.check_id) && (
                          <GhostButton accent={NEON.orange} onClick={() => setRem(f)}><span className="inline-flex items-center gap-1.5"><Wrench size={13} />{t('vi_rem_btn')}</span></GhostButton>
                        )}
                        {isAdmin && !f.exception && f.result === 'fail' && (
                          <GhostButton onClick={() => setExc(f)}><span className="inline-flex items-center gap-1.5"><ShieldOff size={13} />{t('vi_exc_btn')}</span></GhostButton>
                        )}
                        {isAdmin && f.exception && <GhostButton onClick={() => unexcept(f)}>{t('vi_exc_remove')}</GhostButton>}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
      {draft && <DraftModal base={base} finding={draft} onClose={() => setDraft(null)} />}
      {exc && <ExceptionModal base={base} finding={exc} onClose={() => setExc(null)} />}
      {rem && <RemediateModal finding={rem} onClose={() => setRem(null)} />}
    </>
  )
}

export function SimpleTable({ cols, rows, empty }: {
  cols: { key: string; label: string; render?: (r: any) => React.ReactNode; className?: string }[]
  rows: any[]; empty?: string
}) {
  const t = useT()
  if (!rows?.length) return <div className="py-8 text-center text-sm text-slate-500">{empty || t('vi_no_rows')}</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
            {cols.map(c => <th key={c.key} className="px-3 py-2 whitespace-nowrap">{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
              {cols.map(c => <td key={c.key} className={`px-3 py-2 ${c.className || 'text-slate-300'}`}>{c.render ? c.render(r) : fmt(r[c.key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


/** Başlık yanındaki (i): bu sayfa nedir / ne için / nasıl kullanılır. Metinler `info_<id>_what|use|how`. */
export function PageInfo({ id, titleKey }: { id: string; titleKey?: string }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const sections: [string, string][] = [
    ['info_what_title', `info_${id}_what`], ['info_use_title', `info_${id}_use`], ['info_how_title', `info_${id}_how`],
  ]
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title={t('info_btn')} aria-label={t('info_btn')}
        className="inline-flex items-center justify-center w-5 h-5 rounded-full border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 transition-colors">
        <Info size={12} />
      </button>
      {open && (
        <Modal title={t('info_btn')} subtitle={t((titleKey || `${id}_page`) as any)} onClose={() => setOpen(false)} maxWidth="max-w-2xl">
          <div className="px-5 py-4 space-y-4">
            {sections.map(([title, key]) => (
              <div key={key}>
                <div className="text-xs font-semibold uppercase tracking-wider text-blue-300 mb-1">{t(title as any)}</div>
                <div className="text-sm text-slate-300 whitespace-pre-line leading-relaxed">{t(key as any)}</div>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </>
  )
}
