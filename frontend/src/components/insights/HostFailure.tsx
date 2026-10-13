import React, { useEffect, useMemo, useState } from 'react'
import { useT } from '../../i18n/LocaleProvider'
import { apiSend, fmt } from './insightsKit'
import { LimitChip } from './WhatIfResults'
import { TermHint } from './InfoDot'

type Cluster = any

const VERDICT_TONE: Record<string, string> = {
  fit: 'text-emerald-400', tight: 'text-amber-400', fail: 'text-red-400', no_vm: 'text-slate-300',
}
const VERDICT_ICON: Record<string, string> = { fit: '✅', tight: '⚠️', fail: '❌', no_vm: '✅' }
const SHORT_KEY: Record<string, string> = { fit: 'vi_wi_filter_fit', tight: 'vi_hf_level_tight', fail: 'vi_wi_filter_nofit' }

/** Genel karar başlığı. Yalnız CPU sınırlıyorsa CPU'ya özel metin (Sığmaz (CPU) / Sınırda (CPU)). */
function headline(overall: any): string {
  const v = overall.verdict as string
  const lim: string[] = overall.limiting || []
  if ((v === 'fail' || v === 'tight') && lim.length === 1 && lim[0] === 'cpu') return `vi_hf_verdict_${v}_cpu`
  return `vi_hf_verdict_${v}`
}

function MemCell({ r }: { r: any }) {
  const t = useT()
  const v = r.verdict as string
  return (
    <span className={`font-medium ${VERDICT_TONE[v] || ''}`} data-testid={`hf-mem-${v}`}>
      {VERDICT_ICON[v]} {t((SHORT_KEY[v] || 'vi_hf_verdict_no_vm') as any)}
    </span>
  )
}

/** Memory: tanımlı ve p95 sonuçları yan yana. Yalnız backend alanlarını gösterir. */
function MemoryCompare({ res }: { res: any }) {
  const t = useT()
  const d = res.memory.defined
  const p = res.memory.p95
  const cov = res.p95?.coverage
  const row = (label: React.ReactNode, a: React.ReactNode, b: React.ReactNode, id: string) => (
    <tr className="border-t border-white/[0.05]" data-testid={id}>
      <td className="py-1 pr-3 text-slate-400">{label}</td><td className="font-mono text-slate-200">{a}</td><td className="font-mono text-slate-200">{b}</td>
    </tr>
  )
  return (
    <div className="space-y-1" data-testid="hf-memory">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="py-1 pr-3 font-normal">Memory</th>
            <th className="font-normal"><span className="inline-flex items-center">{t('vi_hf_col_defined')}<TermHint k="defined_mem" /></span></th>
            <th className="font-normal"><span className="inline-flex items-center">{t('vi_hf_col_p95')}<TermHint k="p95_mem" /></span></th>
          </tr>
        </thead>
        <tbody>
          {row(t('vi_hf_row_verdict'), <MemCell r={d} />, <MemCell r={p} />, 'hf-row-verdict')}
          {row(t('vi_hf_row_moved'), fmt(d.displaced_gb), fmt(p.displaced_gb), 'hf-row-moved')}
          {row(t('vi_hf_row_after'), `%${fmt(d.after_memory_pct)}`, `%${fmt(p.after_memory_pct)}`, 'hf-row-after')}
          {row(t('vi_hf_row_unplaced'), d.unplaced.length, p.unplaced.length, 'hf-row-unplaced')}
        </tbody>
      </table>
      {cov && cov.vms_total > 0 && (
        <div className="text-[11px] text-slate-500 inline-flex items-center" data-testid="hf-coverage">
          {t('vi_hf_p95_cov', { a: cov.mem_with_p95, b: cov.vms_total, d: res.p95.window_days })}
          <TermHint k="p95_cov" />
        </div>
      )}
      {cov && cov.vms_total > 0 && <div className="text-[11px] text-slate-500">{t('vi_hf_p95_cov_cpu', { a: cov.cpu_with_p95, b: cov.vms_total })}</div>}
    </div>
  )
}

function CpuBlock({ cpu }: { cpu: any }) {
  const t = useT()
  const v = cpu.verdict as string
  return (
    <div className="space-y-0.5 text-xs" data-testid="hf-cpu">
      <div className="text-slate-500 inline-flex items-center">{t('vi_hf_cpu_title')}<TermHint k="cpu_thr" /></div>
      <div className="font-mono text-slate-300">{t('vi_hf_cpu_cores')}: {fmt(cpu.remaining_cores)}</div>
      <div className="font-mono text-slate-300 flex flex-wrap items-center gap-x-2">
        <span>{t('vi_hf_cpu_ratio')}: {cpu.vcpu_ratio == null ? '—' : `${fmt(cpu.vcpu_ratio, 2)}:1`}</span>
        <TermHint k="vcpu_ratio" />
        {cpu.ratio_warn && <span className="text-amber-300" data-testid="hf-ratio-warn">{t('vi_hf_cpu_ratio_warn', { limit: cpu.ratio_limit })}</span>}
      </div>
      <div className="font-mono text-slate-300">
        {t('vi_hf_cpu_demand')}: {t('vi_hf_cpu_demand_val', { d: fmt(cpu.p95_demand_cores), p: cpu.p95_pct == null ? '—' : fmt(cpu.p95_pct), thr: fmt(cpu.threshold_pct) })}
        <span className={`ml-2 ${VERDICT_TONE[v] || ''}`} data-testid={`hf-cpu-${v}`}>{VERDICT_ICON[v]}</span>
      </div>
    </div>
  )
}

/** Host arızası: "Seçilen host(lar) kapanırsa çalışan VM'ler kalan host'lara sığar mı?" — tüm sayılar backend'den. */
export function HostFailureResult({ res }: { res: any }) {
  const t = useT()
  const placed: any[] = res.placed || []
  const unplaced: any[] = res.unplaced || []
  const overall = res.overall || { verdict: res.verdict, limiting: [], warnings: [] }
  const byHost = useMemo(() => {
    const m = new Map<string, { count: number; mem: number; tight: number }>()
    placed.forEach(p => {
      const cur = m.get(p.host) || { count: 0, mem: 0, tight: 0 }
      cur.count += 1; cur.mem += p.memory_gb || 0; cur.tight += p.level === 'tight' ? 1 : 0
      m.set(p.host, cur)
    })
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [placed])
  const p95Placed: Record<string, any> = useMemo(
    () => Object.fromEntries(((res.memory?.p95?.placed || []) as any[]).map(p => [p.vm, p])), [res])
  const v = overall.verdict as string
  return (
    <div className="space-y-3" data-testid="hf-result">
      <div className={`text-sm font-semibold ${VERDICT_TONE[v] || 'text-slate-300'}`} data-testid={`hf-verdict-${v}`}>
        {VERDICT_ICON[v]} {t(headline(overall) as any)}
        {(v === 'fit' || v === 'tight' || v === 'fail') && <TermHint k={v} />}
      </div>
      {((overall.limiting || []).length > 0 || (overall.warnings || []).length > 0) && (
        <div className="flex flex-wrap gap-1" data-testid="hf-limiting">
          {(overall.limiting || []).map((c: string) => <LimitChip key={`l-${c}`} code={c} tone="fail" />)}
          {(overall.warnings || []).map((c: string) => <LimitChip key={`w-${c}`} code={c} tone="warn" />)}
        </div>
      )}
      <div className="text-xs text-slate-400 font-mono">
        {t('vi_hf_summary', {
          n: res.displaced?.count ?? 0, mem: fmt(res.displaced?.memory_gb), hosts: (res.remaining_hosts || []).length,
          after: res.after?.memory_pct == null ? '—' : fmt(res.after.memory_pct), thr: fmt(res.threshold_pct),
        })}
      </div>
      {res.memory && <MemoryCompare res={res} />}
      {res.cpu && <CpuBlock cpu={res.cpu} />}
      {unplaced.length > 0 && (
        <div className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs space-y-1" data-testid="hf-unplaced">
          <div className="text-red-300 font-medium">{t('vi_hf_unplaced', { n: unplaced.length })}</div>
          {unplaced.map(u => (
            <div key={u.vm} className="font-mono text-slate-300">
              {u.vm} · {fmt(u.memory_gb)} GB · <span className="text-red-300">{t(`vi_lim_${u.reason}` as any)}</span>
            </div>
          ))}
        </div>
      )}
      {byHost.length > 0 && (
        <table className="w-full text-xs" data-testid="hf-hosts">
          <thead><tr className="text-left text-slate-500">
            <th className="py-1">{t('vi_hf_target_host')}</th><th>{t('vi_hf_vm_count')}</th><th>Memory (GB)</th><th>{t('vi_hf_level')}</th>
          </tr></thead>
          <tbody>
            {byHost.map(([h, x]) => (
              <tr key={h} className="border-t border-white/[0.05]">
                <td className="py-1 font-mono text-slate-200">{h}</td>
                <td className="font-mono">{x.count}</td>
                <td className="font-mono">{fmt(x.mem)}</td>
                <td className={x.tight ? 'text-amber-300' : 'text-emerald-300'}>{x.tight ? t('vi_hf_level_tight') : t('vi_hf_level_ok')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {placed.length > 0 && (
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer">{t('vi_hf_vm_list', { n: placed.length })} <span className="text-slate-600">({t('vi_hf_vm_cols')})</span></summary>
          <div className="mt-1 space-y-0.5 font-mono">
            {placed.map(p => {
              const q = p95Placed[p.vm]
              return <div key={p.vm}>{p.vm} · {fmt(p.memory_gb)} GB → {p.host}{q ? ` · ${fmt(q.memory_gb)} GB → ${q.host}` : ''}</div>
            })}
          </div>
        </details>
      )}
      <ul className="list-disc pl-5 text-[11px] text-slate-500 space-y-0.5">
        {(res.notes || []).map((n: string) => <li key={n}>{n}</li>)}
      </ul>
    </div>
  )
}

const RANK: Record<string, number> = { fail: 0, tight: 1, fit: 2, no_vm: 3 }

/** Matris hücresi: Memory sonucu + (kalan host Memory %). VM yoksa '—'. */
function MatrixMem({ r, vms }: { r: any; vms: number }) {
  const t = useT()
  if (!vms) return <span className="text-slate-500">—</span>
  const v = r.verdict as string
  return (
    <span className={`font-medium ${VERDICT_TONE[v] || ''}`} data-testid={`hf-mx-mem-${v}`}>
      {VERDICT_ICON[v]} {t((SHORT_KEY[v] || 'vi_hf_verdict_no_vm') as any)}
      {r.after_memory_pct != null && <span className="ml-1 font-mono text-[11px] text-slate-400">%{fmt(r.after_memory_pct)}</span>}
    </span>
  )
}

/** Otomatik N+1 matrisi: her host tek başına düşerse sonuç (backend `/capacity/host-failure/matrix`). Satır tıklanınca ayrıntı. */
export function HostFailureMatrix({ mat, onOpen, active, selected, onToggle }:
  { mat: any; onOpen: (host: string) => void; active: string | null; selected: string[]; onToggle: (h: string) => void }) {
  const t = useT()
  const rows: any[] = useMemo(
    () => [...(mat.rows || [])].sort((a, b) => (RANK[a.overall?.verdict] ?? 9) - (RANK[b.overall?.verdict] ?? 9) || a.host.localeCompare(b.host)),
    [mat])
  return (
    <div className="space-y-2" data-testid="hf-matrix">
      {mat.single_host && (
        <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300" data-testid="hf-single-host">
          {t('vi_hf_no_remaining')}
        </div>
      )}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
            <th className="px-2 py-2 w-6" />
            <th className="px-2 py-2 font-medium">{t('vi_hf_m_host')}</th>
            <th className="px-2 py-2 font-medium text-right">{t('vi_hf_m_vms')}</th>
            <th className="px-2 py-2 font-medium text-right">Memory (GB)</th>
            <th className="px-2 py-2 font-medium"><span className="inline-flex items-center normal-case">{t('vi_hf_m_def')}<TermHint k="defined_mem" /></span></th>
            <th className="px-2 py-2 font-medium"><span className="inline-flex items-center normal-case">{t('vi_hf_m_p95')}<TermHint k="p95_mem" /></span></th>
            <th className="px-2 py-2 font-medium"><span className="inline-flex items-center normal-case">CPU<TermHint k="cpu_thr" /></span></th>
            <th className="px-2 py-2 font-medium">{t('vi_hf_m_lim')}</th>
            <th className="px-2 py-2 font-medium">{t('vi_hf_m_detail')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const v = r.overall?.verdict as string
            const isOpen = active === r.host
            return (
              <tr key={r.host} data-testid={`hf-mrow-${r.host}`} onClick={() => onOpen(r.host)}
                className={`border-b border-white/[0.04] cursor-pointer hover:bg-white/[0.03] ${isOpen ? 'bg-white/[0.04]' : ''}`}>
                <td className="px-2 py-1.5" onClick={e => e.stopPropagation()}>
                  <input type="checkbox" aria-label={r.host} data-testid={`hf-pick-${r.host}`} checked={selected.includes(r.host)}
                    onChange={() => onToggle(r.host)} />
                </td>
                <td className="px-2 py-1.5 font-mono text-slate-200">{r.host}</td>
                {!r.ok ? (
                  <td colSpan={7} className="px-2 py-1.5 text-red-300">{r.error}</td>
                ) : (
                  <>
                    <td className="px-2 py-1.5 font-mono text-right tabular-nums">{r.vms}</td>
                    <td className="px-2 py-1.5 font-mono text-right tabular-nums">{r.vms ? fmt(r.memory_gb) : '—'}</td>
                    {r.no_remaining_host && r.vms > 0 ? (
                      <td colSpan={3} className="px-2 py-1.5 text-red-300" data-testid="hf-mx-noremain">{t('vi_hf_no_remaining')}</td>
                    ) : (
                      <>
                        <td className="px-2 py-1.5"><MatrixMem r={r.defined} vms={r.vms} /></td>
                        <td className="px-2 py-1.5"><MatrixMem r={r.p95} vms={r.vms} /></td>
                        <td className="px-2 py-1.5">
                          {r.cpu ? (
                            <span className={`font-medium ${VERDICT_TONE[r.cpu.verdict] || ''}`} data-testid={`hf-mx-cpu-${r.cpu.verdict}`}>
                              {VERDICT_ICON[r.cpu.verdict]} {t((SHORT_KEY[r.cpu.verdict] || 'vi_hf_verdict_no_vm') as any)}
                              {r.cpu.p95_pct != null && <span className="ml-1 font-mono text-[11px] text-slate-400">%{fmt(r.cpu.p95_pct)}</span>}
                            </span>
                          ) : <span className="text-slate-500">—</span>}
                        </td>
                      </>
                    )}
                    <td className="px-2 py-1.5">
                      {v === 'no_vm' ? <span className="text-slate-500">{t('vi_hf_m_novm')}</span> : (
                        <span className="flex flex-wrap gap-1">
                          {(r.overall?.limiting || []).map((c: string) => <LimitChip key={`l-${c}`} code={c} tone="fail" />)}
                          {(r.overall?.warnings || []).map((c: string) => <LimitChip key={`w-${c}`} code={c} tone="warn" />)}
                          {!(r.overall?.limiting || []).length && !(r.overall?.warnings || []).length && <span className="text-slate-500">—</span>}
                        </span>
                      )}
                    </td>
                  </>
                )}
                <td className="px-2 py-1.5 text-blue-300">{isOpen ? t('vi_hf_m_hide') : t('vi_hf_m_open')}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function HostFailure({ clusters }: { clusters: Cluster[] }) {
  const t = useT()
  const [key, setKey] = useState(clusters.length === 1 ? `${clusters[0].hypervisor_id}:${clusters[0].cluster}` : '')
  const [hosts, setHosts] = useState<string[]>([])
  const [mat, setMat] = useState<any>(null)
  const [matBusy, setMatBusy] = useState(false)
  const [matErr, setMatErr] = useState('')
  const [detail, setDetail] = useState<{ title: string; hosts: string[]; res?: any; err?: string; busy: boolean } | null>(null)
  const sel = clusters.find(c => `${c.hypervisor_id}:${c.cluster}` === key)
  const chipHosts: string[] = mat?.rows?.length ? mat.rows.map((r: any) => r.host) : (sel?.host_names || [])
  const toggle = (h: string) => setHosts(cur => cur.includes(h) ? cur.filter(x => x !== h) : [...cur, h])

  useEffect(() => {
    setHosts([]); setDetail(null); setMat(null); setMatErr('')
    if (!sel) return
    let cancelled = false
    setMatBusy(true)
    apiSend('virt-insights', '/capacity/host-failure/matrix', 'POST', { hypervisor_id: sel.hypervisor_id, cluster: sel.cluster })
      .then(r => { if (!cancelled) setMat(r) })
      .catch((e: any) => { if (!cancelled) setMatErr(e.message) })
      .finally(() => { if (!cancelled) setMatBusy(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const open = async (title: string, hs: string[]) => {
    if (!sel) return
    setDetail({ title, hosts: hs, busy: true })
    try {
      const res = await apiSend('virt-insights', '/capacity/host-failure', 'POST', { hypervisor_id: sel.hypervisor_id, cluster: sel.cluster, hosts: hs })
      setDetail({ title, hosts: hs, res, busy: false })
    } catch (e: any) { setDetail({ title, hosts: hs, err: e.message, busy: false }) }
  }
  const noneSelected = hosts.length === 0

  return (
    <div className="p-4 space-y-4" data-testid="host-failure">
      <div className="text-xs text-slate-400 inline-flex items-center" data-testid="hf-intro">{t('vi_hf_intro')}<TermHint k="hf_matrix" /></div>
      <label className="flex flex-col gap-1 text-xs text-slate-400 max-w-md">{t('vi_scope_cluster')}
        <select data-testid="hf-cluster" value={key} onChange={e => setKey(e.target.value)}
          className="rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white">
          <option value="">{t('vi_hf_pick_cluster')}</option>
          {clusters.map(c => <option key={`${c.hypervisor_id}:${c.cluster}`} value={`${c.hypervisor_id}:${c.cluster}`}>{c.cluster} · {c.hypervisor}</option>)}
        </select>
      </label>
      {!sel && <div className="text-xs text-slate-500" data-testid="hf-pick-hint">{t('vi_hf_pick_hint')}</div>}
      {sel && matBusy && <div className="text-xs text-slate-500" data-testid="hf-matrix-busy">{t('vi_hf_matrix_busy')}</div>}
      {sel && matErr && <div className="text-red-300 text-xs" data-testid="hf-matrix-err">{matErr}</div>}
      {sel && mat && (
        <HostFailureMatrix mat={mat} selected={hosts} onToggle={toggle} active={detail && detail.hosts.length === 1 ? detail.hosts[0] : null}
          onOpen={h => (detail && detail.hosts.length === 1 && detail.hosts[0] === h) ? setDetail(null) : void open(t('vi_hf_detail_one', { host: h }), [h])} />
      )}
      {sel && chipHosts.length > 0 && (
        <div className="space-y-2 rounded border border-white/[0.06] p-3" data-testid="hf-multi">
          <div className="flex flex-wrap items-center gap-2" data-testid="hf-host-chips">
            <span className="text-xs text-slate-400 inline-flex items-center">{t('vi_hf_down_hosts')}<TermHint k="hf_hosts" /></span>
            {chipHosts.map(h => (
              <button key={h} type="button" data-testid={`hf-host-${h}`} aria-pressed={hosts.includes(h)} onClick={() => toggle(h)}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-mono ${hosts.includes(h)
                  ? 'border-red-500/60 bg-red-600/20 text-red-200' : 'border-white/[0.1] text-slate-400 hover:text-slate-200'}`}>{h}</button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" data-testid="hf-run-selected" disabled={noneSelected}
              onClick={() => void open(t('vi_hf_detail_multi', { n: hosts.length }), hosts)}
              className="rounded border border-blue-500/40 bg-blue-600/10 px-3 py-1.5 text-xs font-medium text-blue-200 hover:bg-blue-600/20 disabled:opacity-40 disabled:cursor-not-allowed">
              {t('vi_hf_run_selected')}
            </button>
            {noneSelected && <span className="text-xs text-amber-300" data-testid="hf-select-warning">{t('vi_hf_select_warn')}</span>}
          </div>
        </div>
      )}
      {detail && (
        <div className="rounded border border-white/[0.08] p-3 space-y-2" data-testid="hf-detail">
          <div className="text-xs font-medium text-slate-300">{detail.title}</div>
          {detail.busy && <div className="text-xs text-slate-500">{t('vi_hf_matrix_busy')}</div>}
          {detail.err && <div className="text-red-300 text-xs">{detail.err}</div>}
          {detail.res && <HostFailureResult res={detail.res} />}
        </div>
      )}
    </div>
  )
}
