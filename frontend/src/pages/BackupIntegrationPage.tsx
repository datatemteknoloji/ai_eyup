import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useT } from '../i18n/LocaleProvider'
import { API_BASE_URL } from '../config/api'
import { GhostButton, NEON, PageHeader, PrimaryButton } from '../components/aiops/ui'
import { Panel } from '../components/insights/insightsKit'

const EP = `${API_BASE_URL}/integrations/backup`

async function call(path: string, method = 'GET', body?: unknown) {
  const r = await fetch(`${EP}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

const EMPTY = {
  id: 0, kind: 'veeam_vbr', label: '', endpoint: '', port: 9419, username: '', password: '', verify_ssl: true,
  ca_bundle_path: '', api_revision: '1.3-rev1', sync_interval_sec: 3600, lookback_days: 30,
}

export default function BackupIntegrationPage() {
  const t = useT()
  const qc = useQueryClient()
  const q = useQuery<any>({ queryKey: ['backup-instances'], queryFn: () => call('/instances') })
  const [f, setF] = useState<any>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string; details?: any } | null>(null)
  const [busy, setBusy] = useState(false)
  const reload = () => { qc.invalidateQueries({ queryKey: ['backup-instances'] }); qc.invalidateQueries({ queryKey: ['capabilities'] }); qc.invalidateQueries({ queryKey: ['virt-insights'] }) }
  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setMsg(null)
    try { return await fn() } catch (e: any) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) }
  }
  const body = () => ({ ...f, ca_bundle_path: f.ca_bundle_path || null, password: f.password || null })
  const test = () => run(async () => {
    const r = await call('/test', 'POST', { ...body(), instance_id: f.id || null })
    setMsg({ ok: r.ok, text: r.message, details: r.details })
  })
  const save = () => run(async () => {
    if (f.id) await call(`/instances/${f.id}`, 'PUT', body()); else await call('/instances', 'POST', body())
    setF(null); reload()
  })
  const toggle = (i: any) => run(async () => {
    const r = await call(`/instances/${i.id}/enable`, 'POST', { enabled: !i.enabled })
    if (r.sync && !r.sync.ok) setMsg({ ok: false, text: r.sync.error || t('bki_sync_failed') })
    reload()
  })
  const sync = (i: any) => run(async () => { const r = await call(`/instances/${i.id}/sync`, 'POST'); setMsg({ ok: !!r.sync?.ok, text: r.sync?.ok ? t('bki_sync_ok') : (r.sync?.error || '') }); reload() })
  const del = (i: any) => { if (window.confirm(t('bki_del_confirm'))) run(async () => { await call(`/instances/${i.id}`, 'DELETE'); reload() }) }
  const edit = (i: any) => setF({ ...EMPTY, ...i, password: '' })
  const revs: any[] = q.data?.revisions || []
  const llmRemote: boolean = !!q.data?.llm_remote
  const isDemo = f?.kind === 'veeam_demo'
  const inp = 'input-field text-sm w-full'
  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <PageHeader title={t('bki_title')} subtitle={t('bki_sub')} actions={<><Link to="/integrations" className="text-xs text-slate-400 hover:text-white">← {t('int_title')}</Link>
        <PrimaryButton accent={NEON.blue} onClick={() => { setMsg(null); setF({ ...EMPTY }) }}>{t('bki_add')}</PrimaryButton></>} />
      <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-2 text-xs text-blue-200">{t('bki_role_note')}</div>
      {llmRemote && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-200" data-testid="bki-llm-warn">{t('bki_llm_remote_warn')}</div>}
      {msg && !f && <div className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>}
      {(q.data?.instances || []).map((i: any) => (
        <Panel key={i.id}>
          <div className="p-4 flex flex-wrap items-start gap-4 justify-between">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-white font-semibold">{i.label}</span>
                {i.demo && <span className="px-1.5 text-[11px] rounded bg-fuchsia-500/20 text-fuchsia-300">DEMO</span>}
                {i.demo_inactive && <span className="px-1.5 text-[11px] rounded bg-amber-500/15 text-amber-300">{t('bki_demo_inactive')}</span>}
                <span className={`text-[11px] px-1.5 rounded ${i.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-500/15 text-slate-400'}`}>{i.enabled ? t('bki_enabled') : t('bki_disabled')}</span>
                <span className={`text-[11px] px-1.5 rounded ${i.last_status === 'ok' ? 'text-emerald-300' : i.last_status === 'never' ? 'text-slate-400' : 'bg-red-500/10 text-red-300'}`}>{i.last_status}</span>
              </div>
              <div className="text-xs text-slate-400">{i.demo ? t('bki_demo_desc') : `${i.endpoint}:${i.port} · API ${i.api_revision} · ${i.username || '—'}`}</div>
              <div className="text-xs text-slate-500">{t('bk_last_sync')}: {i.last_sync_at ? new Date(i.last_sync_at).toLocaleString() : '—'}
                {i.server?.build && ` · VBR ${i.server.build}`}
                {i.counts && ` · ${i.counts.jobs} iş · ${i.counts.objects} nesne`}</div>
              {i.last_error && <div className="text-xs text-red-300">{i.last_error}</div>}
              {i.breaker_until && <div className="text-xs text-amber-300">{t('bki_breaker')}: {new Date(i.breaker_until).toLocaleTimeString()}</div>}
              {(i.warnings || []).map((w: string, k: number) => <div key={k} className="text-xs text-amber-200">• {w}</div>)}
            </div>
            <div className="flex gap-2 flex-wrap">
              <GhostButton accent={i.enabled ? NEON.slate : NEON.green} onClick={() => toggle(i)} disabled={busy}>{i.enabled ? t('bki_disable') : t('bki_enable')}</GhostButton>
              {i.enabled && <GhostButton accent={NEON.blue} onClick={() => sync(i)} disabled={busy}>{t('bk_sync_now')}</GhostButton>}
              <GhostButton onClick={() => edit(i)}>{t('edit')}</GhostButton>
              <GhostButton accent={NEON.red} onClick={() => del(i)} disabled={busy}>{t('delete')}</GhostButton>
            </div>
          </div>
        </Panel>
      ))}
      {!q.isLoading && !(q.data?.instances || []).length && <Panel><div className="py-8 text-center text-sm text-slate-500">{t('bki_none')}</div></Panel>}
      {f && (
        <Panel title={f.id ? t('bki_edit') : t('bki_add')}>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_kind')}
              <select className={inp} value={f.kind} disabled={!!f.id} onChange={e => setF({ ...f, kind: e.target.value })}>
                {(q.data?.kinds || []).map((k: any) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
              </select></label>
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_label')}
              <input className={inp} value={f.label} onChange={e => setF({ ...f, label: e.target.value })} /></label>
            {isDemo ? <div className="md:col-span-2 text-xs text-fuchsia-300 rounded border border-fuchsia-500/30 bg-fuchsia-500/10 p-3">{t('bki_demo_desc')}</div> : (
              <>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_server')}
                  <input className={inp} placeholder="vbr01.corp.local" value={f.endpoint} onChange={e => setF({ ...f, endpoint: e.target.value })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_port')}
                  <input className={inp} type="number" value={f.port} onChange={e => setF({ ...f, port: Number(e.target.value) })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_user')}
                  <input className={inp} autoComplete="off" value={f.username} onChange={e => setF({ ...f, username: e.target.value })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_pass')}
                  <input className={inp} type="password" autoComplete="new-password" placeholder={f.id ? t('bki_pass_keep') : ''} value={f.password} onChange={e => setF({ ...f, password: e.target.value })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_revision')}
                  <select className={inp} value={f.api_revision} onChange={e => setF({ ...f, api_revision: e.target.value })}>
                    {revs.map(r => <option key={r.revision} value={r.revision}>{r.revision} — VBR {r.build} ({r.status})</option>)}
                  </select>
                  {f.api_revision !== (q.data?.doc_verified_revision || '1.3-rev1') && (
                    <span className="text-[11px] text-amber-400" data-testid="bki-rev-warn">{t('bki_rev_unverified', { rev: q.data?.doc_verified_revision || '1.3-rev1' })}</span>
                  )}</label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_ca')}
                  <input className={inp} placeholder="/etc/ssl/certs/vbr-ca.pem" value={f.ca_bundle_path || ''} onChange={e => setF({ ...f, ca_bundle_path: e.target.value })} /></label>
                <label className="text-xs text-slate-300 flex items-center gap-2">
                  <input type="checkbox" checked={f.verify_ssl} onChange={e => setF({ ...f, verify_ssl: e.target.checked })} /> {t('bki_verify')}</label>
              </>
            )}
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_interval')}
              <input className={inp} type="number" min={300} value={f.sync_interval_sec} onChange={e => setF({ ...f, sync_interval_sec: Number(e.target.value) })} /></label>
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('bki_lookback')}
              <input className={inp} type="number" min={1} value={f.lookback_days} onChange={e => setF({ ...f, lookback_days: Number(e.target.value) })} /></label>
          </div>
          {msg && (
            <div className="px-4 pb-3 space-y-1">
              <div className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>
              {msg.details && msg.ok && (
                <div className="text-xs text-slate-300 space-y-0.5">
                  {msg.details.server_name && <div>VBR: {msg.details.server_name} · {msg.details.build}</div>}
                  {msg.details.version_note && <div className="text-amber-200">{msg.details.version_note}</div>}
                  <div>API {msg.details.api_revision} · {t('bki_jobs_n', { n: msg.details.jobs ?? '—' })} · {t('bki_repos_n', { n: msg.details.repositories ?? '—' })}</div>
                  {(msg.details.sample_vms || []).length > 0 && <div>{t('bki_sample')}: {msg.details.sample_vms.join(', ')}</div>}
                </div>
              )}
            </div>
          )}
          <div className="px-4 pb-4 flex gap-2 justify-end">
            <GhostButton onClick={() => { setF(null); setMsg(null) }}>{t('cancel')}</GhostButton>
            <GhostButton accent={NEON.blue} onClick={test} disabled={busy}>{t('bki_test')}</GhostButton>
            <PrimaryButton accent={NEON.blue} onClick={save} disabled={busy}>{t('save')}</PrimaryButton>
          </div>
        </Panel>
      )}
    </div>
  )
}
