import React, { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { GhostButton, NEON } from '../aiops/ui'
import { apiGet, apiSend, fmt, pctTone } from './insightsKit'
import { TermHint } from './InfoDot'

type Cluster = any

/** İstekte geçici değiştirilebilen eşikler (politikadaki rs_* anahtarlarıyla aynı). */
export const RS_KEYS = ['rs_window_days', 'rs_target_pct', 'rs_min_reduction_pct', 'rs_min_vcpu'] as const

const N1_TONE: Record<string, string> = { ok: 'text-emerald-400', warn: 'text-amber-400', fail: 'text-red-400' }

/** Yalnız politikadan farklı eşikleri gönderir (politika kaydedilmez; backend bunları "geçici" sayar). */
export function changedThresholds(vals: Record<string, string>, policy: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const k of RS_KEYS) {
    const n = Number(vals[k])
    if (vals[k] !== '' && !Number.isNaN(n) && n !== policy[k]) out[k] = n
  }
  return out
}

function Arrow({ a, b, suffix = '', d = 1, tone }: { a: unknown; b: unknown; suffix?: string; d?: number; tone?: (v: number) => string }) {
  const nb = typeof b === 'number' ? b : null
  return (
    <span className="font-mono">
      {fmt(a, d)}{suffix} → <span className={nb != null && tone ? tone(nb) : ''}>{fmt(b, d)}{suffix}</span>
    </span>
  )
}

function N1Cell({ before, after }: { before: any; after: any }) {
  const t = useT()
  const N1_KEY: Record<string, string> = { ok: 'ok', warn: 'warn', fail: 'fail', single_host: 'single', no_data: 'nodata' }
  const label = (s?: string) => (s && N1_KEY[s] ? t((`vi_n1_${N1_KEY[s]}`) as any) : '—')
  return (
    <span className="font-mono text-xs">
      {before.n1_memory_pct == null ? '—' : `%${fmt(before.n1_memory_pct)}`}{' → '}
      <span className={N1_TONE[after.n1_status] || ''}>{after.n1_memory_pct == null ? '—' : `%${fmt(after.n1_memory_pct)}`} {label(after.n1_status)}</span>
    </span>
  )
}

const KIND_TONE: Record<string, string> = {
  idle: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  oversized: 'border-blue-500/40 bg-blue-500/10 text-blue-300',
}

function KindBadge({ kind }: { kind: string }) {
  const t = useT()
  return (
    <span data-testid={`rc-kind-${kind}`}
      className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium ${KIND_TONE[kind] || 'border-white/[0.1] text-slate-300'}`}>
      {t(`vi_rc_kind_${kind}` as any)}
    </span>
  )
}

export function ReclaimResult({ res }: { res: any }) {
  const t = useT()
  const [open, setOpen] = useState<string | null>(null)
  const rows: any[] = res.clusters || []
  return (
    <div className="space-y-2" data-testid="rc-result">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
            <th className="px-3 py-2 w-6" />
            <th className="px-3 py-2">{t('vi_scope_cluster')}</th>
            <th className="px-3 py-2">{t('vi_rc_col_affected')}</th>
            <th className="px-3 py-2"><span className="inline-flex items-center">{t('vi_rc_col_vcpu')}<TermHint k="reclaim_vcpu" /></span></th>
            <th className="px-3 py-2"><span className="inline-flex items-center">{t('vi_rc_col_mem')}<TermHint k="reclaim_mem" /></span></th>
            <th className="px-3 py-2">{t('vi_rc_col_eff')}</th>
            <th className="px-3 py-2"><span className="inline-flex items-center">{t('vi_rc_col_ratio')}<TermHint k="vcpu_ratio" /></span></th>
            <th className="px-3 py-2"><span className="inline-flex items-center normal-case">N+1<TermHint k="reclaim_n1" /></span></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={8} className="py-6 text-center text-slate-500">{t('vi_no_rows')}</td></tr>}
          {rows.map(r => {
            const key = `${r.hypervisor_id}:${r.cluster}`
            const isOpen = open === key
            return (
              <React.Fragment key={key}>
                <tr data-testid="rc-row" className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer" onClick={() => setOpen(isOpen ? null : key)}>
                  <td className="px-3 py-2 text-slate-500">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  <td className="px-3 py-2 font-mono text-xs text-white">{r.path || r.cluster}</td>
                  <td className="px-3 py-2 font-mono">{r.vms_affected}</td>
                  <td className="px-3 py-2 font-mono" data-testid="rc-vcpu">{r.vcpu.freed} <span className="text-slate-500 text-[11px]">({r.vcpu.vms} VM)</span></td>
                  <td className="px-3 py-2 font-mono" data-testid="rc-mem">{fmt(r.memory.freed_gb)} <span className="text-slate-500 text-[11px]">({r.memory.vms} VM)</span></td>
                  <td className="px-3 py-2 text-xs"><Arrow a={r.before.memory_effective_pct} b={r.after.memory_effective_pct} suffix="%" tone={v => pctTone(v, 75, 85)} /></td>
                  <td className="px-3 py-2 text-xs"><Arrow a={r.before.vcpu_ratio} b={r.after.vcpu_ratio} d={2} /></td>
                  <td className="px-3 py-2"><N1Cell before={r.before} after={r.after} /></td>
                </tr>
                {isOpen && (
                  <tr className="border-b border-white/[0.04] bg-black/20">
                    <td />
                    <td colSpan={7} className="px-3 py-3 space-y-2 text-xs" data-testid="rc-detail">
                      {r.top.length === 0 && <div className="text-slate-500">{t('vi_rc_none')}</div>}
                      {r.top.length > 0 && (
                        <>
                          <div className="text-slate-500">{t('vi_rc_vms', { n: r.top.length })}</div>
                          <table className="w-full text-xs" data-testid="rc-vm-table">
                            <thead>
                              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
                                <th className="py-1.5 pr-3 font-medium">{t('vi_rc_dcol_vm')}</th>
                                <th className="py-1.5 pr-3 font-medium">{t('vi_rc_dcol_class')}</th>
                                <th className="py-1.5 pr-3 font-medium text-right">{t('vi_rc_dcol_vcpu')}</th>
                                <th className="py-1.5 pr-3 font-medium text-right">{t('vi_rc_dcol_mem')}</th>
                                <th className="py-1.5 pr-3 font-medium text-right">{t('vi_rc_dcol_p95cpu')}</th>
                                <th className="py-1.5 pr-3 font-medium text-right">{t('vi_rc_dcol_p95mem')}</th>
                                <th className="py-1.5 font-medium text-right">{t('vi_rc_dcol_days')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {r.top.map((v: any) => (
                                <tr key={v.vm} data-testid="rc-vm-row" className="border-b border-white/[0.04]">
                                  <td className="py-1.5 pr-3 font-mono text-slate-200">{v.vm}</td>
                                  <td className="py-1.5 pr-3"><KindBadge kind={v.kind} /></td>
                                  <td className="py-1.5 pr-3 font-mono text-right tabular-nums" data-testid="rc-vm-vcpu">{v.vcpu} → {v.new_vcpu ?? v.vcpu}</td>
                                  <td className="py-1.5 pr-3 font-mono text-right tabular-nums" data-testid="rc-vm-mem">{fmt(v.memory_gb)} → {fmt(v.new_memory_gb ?? v.memory_gb)}</td>
                                  <td className="py-1.5 pr-3 font-mono text-right tabular-nums">{v.p95_cpu_pct == null ? '—' : `%${fmt(v.p95_cpu_pct)}`}</td>
                                  <td className="py-1.5 pr-3 font-mono text-right tabular-nums">{v.p95_mem_pct == null ? '—' : `%${fmt(v.p95_mem_pct)}`}</td>
                                  <td className="py-1.5 font-mono text-right tabular-nums">{v.data_days ?? '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
      <div className="text-[11px] text-slate-500 space-y-0.5">{(res.notes || []).map((n: string) => <div key={n}>• {n}</div>)}</div>
    </div>
  )
}

export default function ReclaimSim({ clusters }: { clusters: Cluster[] }) {
  const t = useT()
  const [policy, setPolicy] = useState<Record<string, number>>({})
  const [specs, setSpecs] = useState<Record<string, any>>({})
  const [vals, setVals] = useState<Record<string, string>>({})
  const [key, setKey] = useState('')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    apiGet<any>('virt-insights', '/capacity/policy').then(r => {
      setPolicy(r.values || {})
      setSpecs(r.spec || {})
      setVals(Object.fromEntries(RS_KEYS.map(k => [k, String((r.values || {})[k] ?? '')])))
    }).catch(e => setErr(e.message))
  }, [])
  const spec = (k: string) => specs[k]?.label || k
  const run = async () => {
    setErr('')
    try {
      const sel = clusters.find(c => `${c.hypervisor_id}:${c.cluster}` === key)
      const body: any = { thresholds: changedThresholds(vals, policy) }
      if (sel) { body.hypervisor_id = sel.hypervisor_id; body.cluster = sel.cluster }
      setRes(await apiSend('virt-insights', '/capacity/reclaim-sim', 'POST', body))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <div className="p-4 space-y-4" data-testid="reclaim-sim">
      <div className="text-xs text-slate-400">{t('vi_rc_intro')}</div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_rc_cluster')}
          <select data-testid="rc-cluster" value={key} onChange={e => setKey(e.target.value)}
            className="rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white">
            <option value="">{t('vi_rc_all')}</option>
            {clusters.map(c => <option key={`${c.hypervisor_id}:${c.cluster}`} value={`${c.hypervisor_id}:${c.cluster}`}>{c.cluster} · {c.hypervisor}</option>)}
          </select>
        </label>
        {RS_KEYS.map(k => (
          <label key={k} className="flex flex-col gap-1 text-xs text-slate-400" data-testid={`rc-th-${k}`}>
            <span className="inline-flex items-center">{spec(k)}<TermHint k={k} /></span>
            <input type="number" value={vals[k] ?? ''} onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))}
              className="w-28 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono" />
          </label>
        ))}
        <GhostButton accent={NEON.blue} onClick={run}>{t('vi_rc_run')}</GhostButton>
        <GhostButton onClick={() => setVals(Object.fromEntries(RS_KEYS.map(k => [k, String(policy[k] ?? '')])))}>{t('vi_rc_reset')}</GhostButton>
      </div>
      <div className="text-[11px] text-slate-500">{t('vi_rc_temp')}</div>
      {err && <div className="text-red-300 text-xs">{err}</div>}
      {res && <ReclaimResult res={res} />}
    </div>
  )
}
