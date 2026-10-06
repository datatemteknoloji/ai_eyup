import React, { useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Upload } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, NEON, PageHeader, Select, Tabs } from '../components/aiops/ui'
import { FindingsTable, PageInfo, Panel, RunBar, SimpleTable, Stat, apiGet, apiSend, fmt, useInsights, useRole, type Finding } from '../components/insights/insightsKit'

const CATS = ['health', 'hardware', 'vuln', 'known_issue', 'upgrade', 'compliance'] as const

function FindingsTab({ category }: { category: string }) {
  const t = useT()
  const [platform, setPlatform] = useState('')
  const [result, setResult] = useState('fail')
  const [excepted, setExcepted] = useState(false)
  const qs = new URLSearchParams({ category, result, include_excepted: String(excepted) })
  if (platform) qs.set('platform', platform)
  const q = useInsights<{ findings: Finding[] }>('virt-insights', `/findings?${qs}`)
  const ref = useInsights<any>('virt-insights', '/reference', { enabled: ['vuln', 'known_issue', 'upgrade'].includes(category) })
  const kind = category === 'vuln' ? 'cve_feed' : category === 'known_issue' ? 'kb_feed' : category === 'upgrade' ? 'upgrade_matrix' : null
  const pkg = kind ? (ref.data?.packages || []).find((p: any) => p.kind === kind) : null
  return (
    <div className="space-y-3">
      {kind && pkg && !pkg.loaded && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-2 text-xs text-blue-200">{t('vi_ref_missing', { kind })}</div>
      )}
      {kind && pkg?.loaded && (
        <div className="text-xs text-slate-500">{t('vi_ref_loaded', { src: pkg.source || kind, n: pkg.item_count, at: pkg.uploaded_at ? new Date(pkg.uploaded_at).toLocaleString() : '—' })}</div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Select value={platform} onChange={setPlatform}>
          <option value="">{t('vi_all_platforms')}</option>
          <option value="vmware">VMware</option>
          <option value="olvm">OLVM</option>
          <option value="ocp_virt">OpenShift Virtualization</option>
        </Select>
        <Select value={result} onChange={setResult}>
          <option value="fail">{t('vi_res_fail')}</option>
          <option value="not_measurable">{t('vi_res_nm')}</option>
          <option value="pass">{t('vi_res_pass')}</option>
          <option value="all">{t('vi_all')}</option>
        </Select>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={excepted} onChange={e => setExcepted(e.target.checked)} />{t('vi_show_excepted')}
        </label>
      </div>
      <Panel>
        {q.isLoading ? <div className="p-6 text-sm text-slate-400">{t('loading')}</div>
          : q.error ? <div className="p-6 text-sm text-red-300">{(q.error as Error).message}</div>
            : <FindingsTable base="virt-insights" rows={q.data?.findings || []} />}
      </Panel>
    </div>
  )
}

function ComplianceTab() {
  const t = useT()
  const q = useInsights<any>('virt-insights', '/compliance')
  const [open, setOpen] = useState<string | null>(null)
  const download = async (format: 'csv' | 'json') => {
    const r = await fetch(`${API_BASE_URL}/virt-insights/compliance/export?format=${format}`)
    const blob = format === 'csv' ? await r.blob() : new Blob([JSON.stringify(await r.json(), null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `virt-compliance-${new Date().toISOString().slice(0, 10)}.${format}`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  const controls: any[] = q.data?.controls || []
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-xs text-slate-400">{q.data?.disclaimer}</div>
        <div className="flex gap-2">
          <GhostButton accent={NEON.blue} onClick={() => download('csv')}><span className="inline-flex items-center gap-1.5"><Download size={13} />CSV</span></GhostButton>
          <GhostButton accent={NEON.blue} onClick={() => download('json')}><span className="inline-flex items-center gap-1.5"><Download size={13} />JSON</span></GhostButton>
        </div>
      </div>
      <Panel>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
              <th className="px-3 py-2">{t('vi_cmp_control')}</th>
              <th className="px-3 py-2">{t('vi_res_pass')}</th>
              <th className="px-3 py-2">{t('vi_res_fail')}</th>
              <th className="px-3 py-2">{t('vi_res_nm')}</th>
              <th className="px-3 py-2">{t('vi_excepted')}</th>
              <th className="px-3 py-2">{t('vi_cmp_score')}</th>
            </tr>
          </thead>
          <tbody>
            {controls.map(c => (
              <React.Fragment key={c.control}>
                <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer" onClick={() => setOpen(open === c.control ? null : c.control)}>
                  <td className="px-3 py-2 text-white">{c.title}</td>
                  <td className="px-3 py-2 font-mono text-emerald-400">{c.counts.pass}</td>
                  <td className="px-3 py-2 font-mono text-red-400">{c.counts.fail}</td>
                  <td className="px-3 py-2 font-mono text-slate-400">{c.counts.not_measurable}</td>
                  <td className="px-3 py-2 font-mono text-slate-400">{c.counts.excepted}</td>
                  <td className="px-3 py-2 font-mono text-blue-300">{c.score_pct != null ? `%${fmt(c.score_pct)}` : '—'}</td>
                </tr>
                {open === c.control && (
                  <tr><td colSpan={6} className="bg-black/20"><FindingsTable base="virt-insights" rows={c.findings} /></td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </Panel>
      {(q.data?.manual_review || []).length > 0 && (
        <Panel title={t('vi_cmp_manual')}>
          <div className="p-4 space-y-2 text-xs">
            {q.data.manual_review.map((m: any, i: number) => (
              <div key={i}><span className="text-slate-300 font-medium">{m.title}</span> <span className="text-slate-500">({m.control})</span><div className="text-slate-500">{m.note}</div></div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  )
}

function ReferencePackages() {
  const t = useT()
  const qc = useQueryClient()
  const q = useInsights<any>('virt-insights', '/reference')
  const fileRef = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState('cve_feed')
  const [rag, setRag] = useState(true)
  const [msg, setMsg] = useState('')
  const pick = (k: string) => { setKind(k); setMsg(''); fileRef.current?.click() }
  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    try {
      const payload = JSON.parse(await f.text())
      const r = await apiSend<any>('virt-insights', `/reference/${kind}?ingest_rag=${kind === 'kb_feed' && rag}`, 'POST', payload)
      setMsg(t('vi_ref_ok', { n: r.item_count }))
      qc.invalidateQueries({ queryKey: ['virt-insights'] })
    } catch (err: any) { setMsg(err.message) }
  }
  const sample = async (k: string) => {
    const d = await apiGet('virt-insights', `/reference/${k}/sample`)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }))
    a.download = `${k}.sample.json`
    a.click()
  }
  const label: Record<string, string> = { cve_feed: t('vi_ref_cve'), kb_feed: t('vi_ref_kb'), upgrade_matrix: t('vi_ref_upg') }
  return (
    <Panel title={t('vi_ref_title')}>
      <div className="p-4 space-y-3">
        <div className="text-xs text-slate-400">{t('vi_ref_hint')}</div>
        <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={upload} />
        <SimpleTable rows={q.data?.packages || []} cols={[
          { key: 'kind', label: t('vi_ref_kind'), render: r => <span className="text-white">{label[r.kind] || r.kind}</span> },
          { key: 'loaded', label: t('vi_ref_state'), render: r => r.loaded ? <span className="text-emerald-400">{t('vi_ref_state_loaded', { n: r.item_count })}</span> : <span className="text-slate-500">{t('vi_ref_state_none')}</span> },
          { key: 'source', label: t('vi_ref_source'), className: 'text-xs text-slate-400' },
          { key: 'uploaded_at', label: t('vi_ref_uploaded'), render: r => r.uploaded_at ? `${new Date(r.uploaded_at).toLocaleString()} · ${r.uploaded_by}` : '—' },
          { key: 'act', label: '', render: r => (
            <div className="flex gap-2 justify-end">
              <GhostButton onClick={() => sample(r.kind)}>{t('vi_ref_sample')}</GhostButton>
              <GhostButton accent={NEON.blue} onClick={() => pick(r.kind)}><span className="inline-flex items-center gap-1.5"><Upload size={13} />{t('vi_ref_upload')}</span></GhostButton>
            </div>
          ) },
        ]} />
        <label className="flex items-center gap-1.5 text-xs text-slate-400"><input type="checkbox" checked={rag} onChange={e => setRag(e.target.checked)} />{t('vi_ref_rag')}</label>
        {msg && <div className="text-xs text-blue-300">{msg}</div>}
      </div>
    </Panel>
  )
}

function WriteCredentials() {
  const t = useT()
  const hvq = useQuery<any[]>({
    queryKey: ['virt-insights', 'hv-list'],
    queryFn: async () => { const r = await fetch(`${API_BASE_URL}/hypervisors/`); return r.ok ? r.json() : [] },
  })
  const vmware = useMemo(() => (Array.isArray(hvq.data) ? hvq.data : (hvq.data as any)?.items || []).filter((h: any) => String(h.type || h.hypervisor_type || '').toLowerCase().includes('vmware')), [hvq.data])
  return (
    <Panel title={t('vi_wc_title')}>
      <div className="p-4 space-y-3">
        <div className="text-xs text-slate-400">{t('vi_wc_hint')}</div>
        {vmware.length === 0 && <div className="text-xs text-slate-500">{t('vi_no_rows')}</div>}
        {vmware.map((h: any) => <WriteCredRow key={h.id} hv={h} />)}
      </div>
    </Panel>
  )
}

function WriteCredRow({ hv }: { hv: any }) {
  const t = useT()
  const qc = useQueryClient()
  const st = useInsights<any>('virt-insights', `/write-credential/${hv.id}`)
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [msg, setMsg] = useState('')
  const save = async () => {
    try { await apiSend('virt-insights', `/write-credential/${hv.id}`, 'PUT', { username: u, password: p }); setP(''); setMsg(t('vi_wc_saved')); qc.invalidateQueries({ queryKey: ['virt-insights', `/write-credential/${hv.id}`] }) } catch (e: any) { setMsg(e.message) }
  }
  const clear = async () => {
    await apiSend('virt-insights', `/write-credential/${hv.id}`, 'DELETE').catch(() => null)
    qc.invalidateQueries({ queryKey: ['virt-insights', `/write-credential/${hv.id}`] })
  }
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-white/[0.04] pt-3">
      <div className="w-48 text-sm text-white">{hv.name}</div>
      <div className="w-56 text-xs">{st.data?.configured ? <span className="text-emerald-400">{t('vi_wc_set', { u: st.data.username })}</span> : <span className="text-slate-500">{t('vi_wc_none')}</span>}</div>
      <input value={u} onChange={e => setU(e.target.value)} placeholder={t('vi_wc_user')} autoComplete="off" className="w-48 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white" />
      <input value={p} onChange={e => setP(e.target.value)} placeholder={t('vi_wc_pass')} type="password" autoComplete="new-password" className="w-40 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white" />
      <GhostButton accent={NEON.blue} onClick={save} disabled={!u || !p}>{t('save')}</GhostButton>
      {st.data?.configured && <GhostButton onClick={clear}>{t('vi_wc_clear')}</GhostButton>}
      {msg && <span className="text-xs text-blue-300">{msg}</span>}
    </div>
  )
}

export default function VirtHealthChecks() {
  const t = useT()
  const { isAdmin } = useRole()
  const [sp, setSp] = useSearchParams()
  const tab = sp.get('tab') || 'health'
  const sum = useInsights<any>('virt-insights', '/summary')
  const by = sum.data?.findings?.by_category || {}
  const label: Record<string, string> = {
    health: t('vi_cat_health'), hardware: t('vi_cat_hardware'), vuln: t('vi_cat_vuln'),
    known_issue: t('vi_cat_kb'), upgrade: t('vi_cat_upgrade'), compliance: t('vi_cat_compliance'),
  }
  const tabs = [
    ...CATS.map(c => ({ id: c, label: label[c], count: by[c]?.total ?? 0 })),
    ...(isAdmin ? [{ id: 'settings', label: t('vi_tab_settings') }] : []),
  ]
  const crit = Object.values(by).reduce((a: number, c: any) => a + (c.critical || 0), 0)
  const high = Object.values(by).reduce((a: number, c: any) => a + (c.high || 0), 0)
  return (
    <div className="space-y-5">
      <PageHeader title={t('vi_hc_page')} titleExtra={<PageInfo id="vi_hc" />} subtitle={t('vi_hc_sub')} actions={<RunBar base="virt-insights" lastRun={sum.data?.last_run} />} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label={t('vi_hc_critical')} value={crit} tone={crit ? 'text-red-400' : 'text-white'} />
        <Stat label={t('vi_hc_high')} value={high} tone={high ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('vi_res_nm')} value={sum.data?.findings?.not_measurable ?? 0} tone="text-slate-300" hint={t('vi_hc_nm_hint')} />
        <Stat label={t('vi_excepted')} value={sum.data?.findings?.excepted ?? 0} tone="text-slate-300" />
      </div>
      <Tabs tabs={tabs} active={tab} onChange={id => setSp({ tab: id })} />
      {tab === 'compliance' ? <ComplianceTab />
        : tab === 'settings' ? <div className="space-y-4"><ReferencePackages /><WriteCredentials /></div>
          : <FindingsTab key={tab} category={tab} />}
    </div>
  )
}
