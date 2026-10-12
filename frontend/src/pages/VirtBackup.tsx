import React, { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useT } from '../i18n/LocaleProvider'
import { API_BASE_URL } from '../config/api'
import { GhostButton, NEON, PageHeader, PrimaryButton, Tabs } from '../components/aiops/ui'
import { Bar, PageInfo, Panel, SimpleTable, Stat, apiSend, fmt, useInsights, useRole } from '../components/insights/insightsKit'
import { useCapabilities } from '../hooks/useCapabilities'

const BASE = 'virt-insights' as const

function ago(min?: number | null) {
  if (min == null) return '—'
  if (min < 90) return `${Math.round(min)} dk`
  if (min < 60 * 48) return `${(min / 60).toFixed(1)} sa`
  return `${(min / 1440).toFixed(1)} g`
}

function RpoBadge({ s }: { s: string }) {
  const t = useT()
  const map: Record<string, [string, string]> = {
    ok: ['bk_rpo_ok', 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10'],
    breach: ['bk_rpo_breach', 'text-red-300 border-red-500/30 bg-red-500/10'],
    no_target: ['bk_rpo_no_target', 'text-slate-300 border-dashed border-slate-500/40 bg-slate-500/5'],
  }
  const m = map[s]
  if (!m) return <span className="text-slate-500">—</span>
  return <span className={`text-[11px] px-2 py-0.5 rounded border ${m[1]}`}>{t(m[0] as any)}</span>
}

function Evidence({ syncAt }: { syncAt?: string | null }) {
  const t = useT()
  const ev = useInsights<any>(BASE, '/backup/evidence')
  const cor = useInsights<any>(BASE, '/backup/correlations')
  const [n, setN] = useState('20')
  const [gb, setGb] = useState('')
  const wi = useInsights<any>(BASE, `/backup/capacity-whatif?add_vms=${Number(n) || 0}${gb ? `&avg_vm_gb=${Number(gb)}` : ''}`)
  const st = (v: string) => v === 'ok' ? 'text-emerald-300' : v === 'eksik' ? 'text-red-300' : 'text-slate-400'
  const w = wi.data
  return (
    <div className="space-y-4">
      <Panel title={t('bk_ev_title')} method="bk.evidence" methodAt={syncAt}>
        <p className="text-xs text-slate-400 p-3">{t('bk_ev_hint')}</p>
        <SimpleTable rows={ev.data?.items || []} cols={[
          { key: 'control', label: t('bk_ev_control') },
          { key: 'item', label: t('bk_ev_item'), render: (r: any) => <span className="text-white">{r.item}</span> },
          { key: 'status', label: t('bk_ev_status'), render: (r: any) => <span className={st(r.status)}>{r.status === 'ok' ? t('bk_ev_ok') : r.status === 'eksik' ? t('bk_ev_missing') : t('bk_ev_unmeasured')}</span> },
          { key: 'value', label: t('bk_ev_value'), render: (r: any) => r.value ?? '—' },
        ]} />
        {(ev.data?.not_checked || []).length > 0 && (
          <p className="text-xs text-amber-200 p-3">{t('bk_ev_not_checked')}: {ev.data.not_checked.join(' · ')}</p>
        )}
      </Panel>
      <Panel title={t('bk_wi_title')} method="bk.whatif" methodAt={syncAt}>
        <div className="p-3 flex flex-wrap gap-3 items-end text-xs text-slate-400">
          <label className="flex flex-col gap-1">{t('bk_wi_add')}<input className="input-field text-sm w-28" type="number" min={0} value={n} onChange={e => setN(e.target.value)} /></label>
          <label className="flex flex-col gap-1">{t('bk_wi_gb')}<input className="input-field text-sm w-36" type="number" min={1} value={gb} placeholder={t('bk_wi_auto')} onChange={e => setGb(e.target.value)} /></label>
        </div>
        {w?.ok ? (
          <div className="px-3 pb-3 text-sm text-slate-200 space-y-1">
            <div>{t('bk_wi_result', { before: w.used_pct_before, after: w.used_pct_after, per: w.per_vm_gb })}</div>
            <div className={w.fits_below_warn ? 'text-emerald-300' : 'text-red-300'}>{w.fits_below_warn ? t('bk_wi_fits', { warn: w.warn_pct }) : t('bk_wi_over', { warn: w.warn_pct })}</div>
            {(w.assumptions || []).map((a: string, i: number) => <div key={i} className="text-xs text-slate-500">• {a}</div>)}
          </div>
        ) : <div className="px-3 pb-3 text-xs text-slate-500">{w?.reason || ''}</div>}
      </Panel>
      <Panel title={t('bk_cor_title')} method="bk.correlation" methodAt={syncAt}>
        <p className="text-xs text-slate-400 p-3">{t('bk_cor_hint')}</p>
        <SimpleTable rows={cor.data?.items || []} empty={t('bk_cor_none')} cols={[
          { key: 'job', label: t('bk_col_job'), render: (r: any) => <span className="text-white">{r.job}</span> },
          { key: 'first_failed_at', label: t('bk_cor_failed'), render: (r: any) => new Date(r.first_failed_at).toLocaleString() },
          { key: 'changes', label: t('bk_cor_changes'), render: (r: any) => <div className="text-xs space-y-0.5">{(r.changes || []).slice(0, 3).map((c: any, i: number) => <div key={i}>{c.title}</div>)}</div> },
        ]} />
      </Panel>
    </div>
  )
}

function Policies({ onChanged }: { onChanged: () => void }) {
  const t = useT()
  const { isAdmin } = useRole()
  const q = useInsights<any>(BASE, '/backup/policies')
  const [kind, setKind] = useState('all')
  const [ref, setRef] = useState('')
  const [rpo, setRpo] = useState('')
  const [rto, setRto] = useState('')
  const [msg, setMsg] = useState('')
  const save = async () => {
    setMsg('')
    try {
      await apiSend(BASE, '/backup/policies', 'POST', {
        scope_kind: kind, scope_ref: ref, target_rpo_min: rpo ? Number(rpo) : null, target_rto_min: rto ? Number(rto) : null,
      })
      setRpo(''); setRto(''); setRef('')
      q.refetch(); onChanged()
    } catch (e: any) { setMsg(e.message) }
  }
  const del = async (id: number) => { await apiSend(BASE, `/backup/policies/${id}`, 'DELETE'); q.refetch(); onChanged() }
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-400">{t('bk_policy_hint')}</p>
      <SimpleTable rows={q.data?.policies || []} empty={t('bk_policy_none')} cols={[
        { key: 'scope_kind', label: t('bk_policy_scope') },
        { key: 'scope_ref', label: t('bk_policy_ref'), render: (r: any) => r.scope_ref || '—' },
        { key: 'target_rpo_min', label: 'RPO (dk)', className: 'font-mono' },
        { key: 'target_rto_min', label: 'RTO (dk)', className: 'font-mono' },
        { key: 'x', label: '', render: (r: any) => isAdmin ? <button className="text-xs text-red-300 hover:text-red-200" onClick={() => del(r.id)}>{t('delete')}</button> : null },
      ]} />
      {isAdmin && (
        <div className="flex flex-wrap items-end gap-2 pt-2 border-t border-white/[0.06]">
          <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bk_policy_scope')}
            <select className="input-field text-sm" value={kind} onChange={e => setKind(e.target.value)}>
              <option value="all">{t('bk_policy_all')}</option><option value="cluster">cluster</option><option value="vm">VM</option>
            </select></label>
          {kind !== 'all' && <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bk_policy_ref')}
            <input className="input-field text-sm" value={ref} onChange={e => setRef(e.target.value)} /></label>}
          <label className="text-xs text-slate-400 flex flex-col gap-1">RPO (dk)
            <input className="input-field text-sm w-28" type="number" min={1} value={rpo} onChange={e => setRpo(e.target.value)} /></label>
          <label className="text-xs text-slate-400 flex flex-col gap-1">RTO (dk) <span className="text-[10px] text-slate-500">{t('bk_rto_note')}</span>
            <input className="input-field text-sm w-28" type="number" min={1} value={rto} onChange={e => setRto(e.target.value)} /></label>
          <PrimaryButton accent={NEON.blue} onClick={save}>{t('save')}</PrimaryButton>
          {msg && <span className="text-xs text-red-300">{msg}</span>}
        </div>
      )}
    </div>
  )
}

export default function VirtBackup() {
  const t = useT()
  const qc = useQueryClient()
  const { isAdmin } = useRole()
  const { hasBackup, isLoading: capLoading } = useCapabilities()
  const [tab, setTab] = useState('rpo')
  const [filter, setFilter] = useState('')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const on = hasBackup
  const sum = useInsights<any>(BASE, '/backup/summary', { enabled: on, refetch: 60_000 })
  const qs = new URLSearchParams()
  if (filter === 'unprotected' || filter === 'low_match') qs.set('state', filter)
  if (filter === 'breach' || filter === 'ok' || filter === 'no_target') qs.set('rpo_state', filter)
  if (q.trim()) qs.set('q', q.trim())
  const rpo = useInsights<any>(BASE, `/backup/rpo?${qs}`, { enabled: on && tab === 'rpo' })
  const jobs = useInsights<any>(BASE, '/backup/jobs', { enabled: on && tab === 'jobs' })
  const repos = useInsights<any>(BASE, '/backup/repositories', { enabled: on && tab === 'repos' })
  const unm = useInsights<any>(BASE, '/backup/unmatched', { enabled: on && tab === 'unmatched' })

  if (capLoading) return <div className="p-6 text-sm text-slate-400">{t('loading')}</div>
  if (!on) {
    return (
      <div className="space-y-4">
        <PageHeader title={t('bk_page')} subtitle={t('bk_sub')} />
        <Panel><div className="py-8 text-center text-sm text-slate-400 space-y-2">
          <div>{t('bk_not_cfg')}</div>
          <Link to="/integrations/backup" className="text-blue-300 hover:text-blue-200 text-sm">{t('bk_go_integration')}</Link>
        </div></Panel>
      </div>
    )
  }
  const s = sum.data || {}
  const providers: any[] = s.providers || []
  const demo = providers.some(p => p.demo)
  const syncAt: string | null = providers.map(p => p.last_sync_at).filter(Boolean).sort().pop() || null
  const syncNow = async () => {
    setBusy(true)
    try {
      for (const p of providers) {
        await fetch(`${API_BASE_URL}/integrations/backup/instances/${p.id}/sync`, { method: 'POST' })
      }
    } finally {
      setBusy(false)
      qc.invalidateQueries({ queryKey: [BASE] }); qc.invalidateQueries({ queryKey: ['capabilities'] })
    }
  }
  const refresh = () => qc.invalidateQueries({ queryKey: [BASE] })
  return (
    <div className="space-y-5">
      <PageHeader title={t('bk_page')} titleExtra={<PageInfo id="vi_bk" titleKey="bk_page" />} subtitle={t('bk_sub')}
        actions={isAdmin ? <GhostButton accent={NEON.blue} onClick={syncNow} disabled={busy}>{busy ? '…' : t('bk_sync_now')}</GhostButton> : undefined} />
      {demo && <div className="rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/10 px-4 py-2 text-xs text-fuchsia-300">{t('bk_demo_banner')}</div>}
      {providers.map(p => (
        <div key={p.id} className={`rounded-lg border px-4 py-2 text-xs flex flex-wrap gap-x-4 gap-y-1 items-center ${p.stale || p.last_status !== 'ok' ? 'border-amber-500/30 bg-amber-500/5 text-amber-200' : 'border-white/[0.08] bg-white/[0.02] text-slate-300'}`}>
          <span className="text-white font-medium">{p.label}</span>
          {p.demo && <span className="px-1.5 rounded bg-fuchsia-500/20 text-fuchsia-300">DEMO</span>}
          <span>{t('bk_last_sync')}: {p.last_sync_at ? new Date(p.last_sync_at).toLocaleString() : '—'}</span>
          {p.stale && <span className="font-semibold">{t('bk_stale')}</span>}
          {p.last_status !== 'ok' && <span className="text-red-300">{p.last_error || p.last_status}</span>}
        </div>
      ))}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <Stat label={t('bk_protected_pct')} value={s.protected_pct != null ? `%${fmt(s.protected_pct)}` : '—'} hint={`${s.protected ?? 0} / ${s.powered_on ?? 0}`} tone="text-blue-300" method="bk.summary" methodAt={syncAt} />
        <Stat label={t('bk_unprotected')} value={s.unprotected ?? 0} tone={(s.unprotected ?? 0) ? 'text-red-400' : 'text-white'} method="bk.vm.unprotected" methodAt={syncAt} />
        <Stat label={t('bk_rpo_ok')} value={s.rpo_ok ?? 0} tone="text-emerald-400" method="bk.rpo" methodAt={syncAt} />
        <Stat label={t('bk_rpo_breach')} value={s.rpo_breach ?? 0} tone={(s.rpo_breach ?? 0) ? 'text-red-400' : 'text-white'} method="bk.vm.rpo_breach" methodAt={syncAt} />
        <Stat label={t('bk_rpo_no_target')} value={s.rpo_no_target ?? 0} hint={t('bk_no_target_hint')} method="bk.rpo" methodAt={syncAt} />
        <Stat label={t('bk_jobs_failed')} value={s.jobs_failed ?? 0} tone={(s.jobs_failed ?? 0) ? 'text-amber-400' : 'text-white'} hint={`${s.jobs ?? 0} ${t('bk_jobs')}`} method="bk.jobs" methodAt={syncAt} />
      </div>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'rpo', label: t('bk_tab_rpo') }, { id: 'jobs', label: t('bk_tab_jobs'), count: s.jobs },
        { id: 'repos', label: t('bk_tab_repos'), count: s.repositories }, { id: 'unmatched', label: t('bk_tab_unmatched'), count: s.low_match },
        { id: 'policies', label: t('bk_tab_policies') }, { id: 'evidence', label: t('bk_tab_evidence') },
      ]} />
      {tab === 'rpo' && (
        <Panel method="bk.rpo" methodAt={syncAt}>
          <div className="flex flex-wrap gap-2 p-3 border-b border-white/[0.06]">
            <select className="input-field text-sm" value={filter} onChange={e => setFilter(e.target.value)}>
              <option value="">{t('vi_all')}</option><option value="unprotected">{t('bk_unprotected')}</option>
              <option value="breach">{t('bk_rpo_breach')}</option><option value="ok">{t('bk_rpo_ok')}</option>
              <option value="no_target">{t('bk_rpo_no_target')}</option><option value="low_match">{t('bk_low_match')}</option>
            </select>
            <input className="input-field text-sm" placeholder="VM" value={q} onChange={e => setQ(e.target.value)} />
          </div>
          <SimpleTable rows={rpo.data?.vms || []} cols={[
            { key: 'name', label: 'VM', render: (r: any) => <span className="text-white">{r.name}</span> },
            { key: 'cluster', label: 'Cluster' },
            { key: 'state', label: t('bk_col_state'), render: (r: any) => r.state === 'protected' ? <span className="text-emerald-300">{t('bk_protected')}</span> : r.state === 'low_match' ? <span className="text-amber-300">{t('bk_low_match')}</span> : (r.powered_on === false
              ? <span className="text-slate-400" title={t('bk_off_hint')}>{t('bk_unprotected_off')}</span>
              : <span className="text-red-300">{t('bk_unprotected')}</span>) },
            { key: 'rpo_age_min', label: t('bk_col_age'), render: (r: any) => <span className="font-mono">{ago(r.rpo_age_min)}</span> },
            { key: 'target_rpo_min', label: t('bk_col_target'), render: (r: any) => r.target_rpo_min ? <span className="font-mono">{ago(r.target_rpo_min)}</span> : <span className="text-slate-500">—</span> },
            { key: 'rpo_state', label: 'RPO', render: (r: any) => <RpoBadge s={r.rpo_state} /> },
            { key: 'match_confidence', label: t('bk_col_match') },
          ]} />
        </Panel>
      )}
      {tab === 'jobs' && (
        <Panel method="bk.jobs" methodAt={syncAt}><SimpleTable rows={jobs.data?.jobs || []} cols={[
          { key: 'name', label: t('bk_col_job'), render: (r: any) => <span className="text-white">{r.name}</span> },
          { key: 'type', label: t('vi_col_type') },
          { key: 'last_result', label: t('bk_col_result'), render: (r: any) => <span className={r.last_result === 'Failed' ? 'text-red-300' : r.last_result === 'Warning' ? 'text-amber-300' : 'text-emerald-300'}>{r.last_result || '—'}</span> },
          { key: 'last_run_at', label: t('bk_col_last_run'), render: (r: any) => r.last_run_at ? new Date(r.last_run_at).toLocaleString() : '—' },
          { key: 'repository', label: t('bk_col_repo') },
          { key: 'objects', label: t('bk_col_objects'), className: 'font-mono' },
        ]} /></Panel>
      )}
      {tab === 'repos' && (
        <Panel method="bk.repos" methodAt={syncAt}><SimpleTable rows={repos.data?.repositories || []} cols={[
          { key: 'name', label: t('bk_col_repo'), render: (r: any) => <span className="text-white">{r.name}</span> },
          { key: 'type', label: t('vi_col_type') },
          { key: 'used_pct', label: t('bk_col_used'), render: (r: any) => <div className="w-40"><Bar pct={r.used_pct} warn={r.warn_pct} crit={95} /></div> },
          { key: 'free_gb', label: t('bk_col_free'), render: (r: any) => r.free_gb != null ? `${fmt(r.free_gb, 0)} GB` : '—' },
          { key: 'online', label: t('bk_col_online'), render: (r: any) => r.online === false ? <span className="text-red-300">✗</span> : <span className="text-emerald-300">✓</span> },
        ]} /></Panel>
      )}
      {tab === 'unmatched' && (
        <Panel method="bk.match" methodAt={syncAt}>
          <p className="text-xs text-slate-400 p-3">{t('bk_unmatched_hint')}</p>
          <SimpleTable rows={unm.data?.objects || []} cols={[
            { key: 'name', label: t('bk_col_obj'), render: (r: any) => <span className="text-white">{r.name}</span> },
            { key: 'confidence', label: t('bk_col_match') }, { key: 'method', label: t('bk_col_method') },
            { key: 'last_restore_point_at', label: t('bk_col_last_rp'), render: (r: any) => r.last_restore_point_at ? new Date(r.last_restore_point_at).toLocaleString() : '—' },
          ]} />
        </Panel>
      )}
      {tab === 'evidence' && <Evidence syncAt={syncAt} />}
      {tab === 'policies' && <Panel><div className="p-4"><Policies onChanged={refresh} /></div></Panel>}
    </div>
  )
}
