import React, { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useT } from '../i18n/LocaleProvider'
import { API_BASE_URL } from '../config/api'
import { GhostButton, NEON, PageHeader, PrimaryButton } from '../components/aiops/ui'
import { Panel } from '../components/insights/insightsKit'

const EP = `${API_BASE_URL}/integrations/hardware`

async function call(path: string, method = 'GET', body?: unknown) {
  const r = await fetch(`${EP}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

const EMPTY = {
  id: 0, kind: 'dell_ome', label: '', endpoint: '', port: 443, username: '', password: '', verify_ssl: true,
  ca_bundle_path: '', mode: 'ovgd', appliances: [] as string[], login_domain: 'Local',
  alarm_interval_sec: 900, inventory_interval_sec: 86400, warranty_interval_sec: 86400,
  fetch_firmware: false, throttle_sec: 0,
  bmc_username: '', bmc_password: '', bmc_verify_tls: false, bmc_clear: false,
}

const SUPPORT_CLS: Record<string, string> = {
  verified: 'bg-emerald-500/15 text-emerald-300',
  compatible: 'bg-amber-500/15 text-amber-300',
  unsupported: 'bg-red-500/15 text-red-300',
}

export default function HardwareIntegrationPage() {
  const t = useT()
  const qc = useQueryClient()
  const q = useQuery<any>({ queryKey: ['hw-instances'], queryFn: () => call('/instances') })
  const [f, setF] = useState<any>(null)
  const [appText, setAppText] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string; details?: any } | null>(null)
  const [busy, setBusy] = useState(false)
  const [waitUntil, setWaitUntil] = useState(0)
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id) }, [])
  const wait = Math.max(0, Math.ceil((waitUntil - now) / 1000))
  const cooldown = q.data?.test_cooldown_sec ?? 30

  const reload = () => {
    qc.invalidateQueries({ queryKey: ['hw-instances'] })
    qc.invalidateQueries({ queryKey: ['capabilities'] })
    qc.invalidateQueries({ queryKey: ['hw-summary'] })
  }
  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setMsg(null)
    try { return await fn() } catch (e: any) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) }
  }
  const body = () => ({
    ...f, ca_bundle_path: f.ca_bundle_path || null, password: f.password || null,
    bmc_password: f.bmc_password || null,
    appliances: appText.split('\n').map((x: string) => x.trim()).filter(Boolean),
  })
  const test = () => run(async () => {
    setWaitUntil(Date.now() + cooldown * 1000)        // hesap kilidi koruması: sonuç ne olursa olsun bekleme
    const r = await call('/test', 'POST', { ...body(), instance_id: f.id || null })
    setMsg({ ok: r.ok, text: r.resumed ? `${r.message} — ${t('hwi_resumed')}` : r.needs_save ? `${r.message} — ${t('hwi_needs_save')}` : r.message, details: { ...(r.details || {}), hint: r.hint } })
    if (r.resumed || r.auth_halted) reload()
  })
  const save = () => run(async () => {
    if (f.id) await call(`/instances/${f.id}`, 'PUT', body()); else await call('/instances', 'POST', body())
    setF(null); reload()
  })
  const toggle = (i: any) => run(async () => {
    const r = await call(`/instances/${i.id}/enable`, 'POST', { enabled: !i.enabled })
    if (r.sync && !r.sync.ok) setMsg({ ok: false, text: r.sync.error || '' })
    reload()
  })
  const sync = (i: any) => run(async () => {
    const r = await call(`/instances/${i.id}/sync`, 'POST')
    setMsg({ ok: !!r.sync?.ok, text: r.sync?.ok ? t('hwi_sync_ok') : (r.sync?.error || '') }); reload()
  })
  const del = (i: any) => { if (window.confirm(t('hwi_del_confirm'))) run(async () => { await call(`/instances/${i.id}`, 'DELETE'); reload() }) }
  const edit = (i: any) => { setMsg(null); setAppText((i.appliances || []).join('\n')); setF({ ...EMPTY, ...i, password: '', bmc_username: i.bmc?.username || '', bmc_password: '', bmc_verify_tls: !!i.bmc?.verify_tls, bmc_clear: false }) }
  const add = (kind: string) => { setMsg(null); setAppText(''); setF({ ...EMPTY, kind }) }

  const inp = 'input-field text-sm w-full'
  const isHpe = f?.kind === 'hpe_oneview'
  const isDemo = f?.kind === 'hw_demo'
  const tool = f?.kind === 'dell_ome' ? 'dell_ome' : (f?.mode === 'oneview' ? 'oneview' : 'ovgd')
  const notes = q.data?.notes || {}

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      <PageHeader title={t('hwi_title')} subtitle={t('hwi_sub')} actions={<>
        <Link to="/integrations" className="text-xs text-slate-400 hover:text-white">← {t('int_title')}</Link>
        <PrimaryButton accent={NEON.blue} onClick={() => add('dell_ome')}>{t('hwi_add')}</PrimaryButton>
      </>} />
      <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-2 text-xs text-blue-200">{notes.account || t('hwi_account_note')}</div>
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-200" data-testid="hwi-auth-note">{notes.auth_protection || t('hwi_auth_note')}</div>
      {msg && !f && <div className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>}

      {(q.data?.instances || []).map((i: any) => (
        <Panel key={i.id}>
          <div className="p-4 space-y-3">
            <div className="flex flex-wrap items-start gap-4 justify-between">
              <div className="space-y-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-white font-semibold">{i.label}</span>
                  <span className="text-[11px] px-1.5 rounded-sm bg-slate-500/20 text-slate-300">{i.kind === 'dell_ome' ? 'Dell OME' : i.kind === 'hpe_oneview' ? (i.mode === 'ovgd' ? 'HPE OVGD' : 'HPE OneView') : 'DEMO'}</span>
                  {i.demo && <span className="px-1.5 text-[11px] rounded-sm bg-fuchsia-500/20 text-fuchsia-300">DEMO</span>}
                  {i.demo_inactive && <span className="px-1.5 text-[11px] rounded-sm bg-amber-500/15 text-amber-300">{t('hwi_demo_off')}</span>}
                  <span className={`text-[11px] px-1.5 rounded-sm ${i.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-500/15 text-slate-400'}`}>{i.enabled ? t('hwi_enabled') : t('hwi_disabled')}</span>
                  <span className={`text-[11px] px-1.5 rounded-sm ${i.last_status === 'ok' ? 'text-emerald-300' : i.last_status === 'never' ? 'text-slate-400' : 'bg-red-500/10 text-red-300'}`}>{i.last_status}</span>
                </div>
                {!i.demo && <div className="text-xs text-slate-400">{i.endpoint}:{i.port} · {i.username || '—'}{i.kind === 'hpe_oneview' && i.mode === 'oneview' && i.appliances?.length ? ` · +${i.appliances.length}` : ''}</div>}
                <div className="text-xs text-slate-500">{t('hwi_last_sync')}: {i.last_sync_at ? new Date(i.last_sync_at).toLocaleString() : '—'}
                  {i.counts && ` · ${t('hwi_counts', { s: i.counts.servers ?? '—', a: i.counts.alerts ?? '—' })}`}</div>
                {i.last_error && !i.auth_halted && <div className="text-xs text-red-300">{i.last_error}</div>}
                {i.breaker_until && <div className="text-xs text-amber-300">{t('hwi_breaker', { t: new Date(i.breaker_until).toLocaleTimeString() })}</div>}
                {(i.warnings || []).map((w: string, k: number) => <div key={k} className="text-xs text-amber-200">• {w}</div>)}
              </div>
              <div className="flex gap-2 flex-wrap">
                <GhostButton accent={i.enabled ? NEON.slate : NEON.green} onClick={() => toggle(i)} disabled={busy || (!i.enabled && i.auth_halted)}>{i.enabled ? t('hwi_disable') : t('hwi_enable')}</GhostButton>
                {i.enabled && <GhostButton accent={NEON.blue} onClick={() => sync(i)} disabled={busy || i.auth_halted}>{t('hwi_sync_now')}</GhostButton>}
                <GhostButton onClick={() => edit(i)}>{t('hwi_edit')}</GhostButton>
                <GhostButton accent={NEON.red} onClick={() => del(i)} disabled={busy}>{t('delete')}</GhostButton>
              </div>
            </div>
            {i.auth_halted && (
              <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 space-y-1" role="alert" data-testid="hwi-auth-halted">
                <div className="text-sm font-semibold text-red-200">{t('hwi_halt_title')}</div>
                <div className="text-xs text-red-200">{i.auth_halt?.message || i.last_error}</div>
                <div className="text-xs text-red-100/80">{t('hwi_halt_hint')}</div>
              </div>
            )}
            {(i.managers || []).length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] uppercase tracking-wide text-slate-500">{t('hwi_managers')}</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
                  {i.managers.map((m: any) => (
                    <div key={m.id} className="text-xs flex items-center gap-2 flex-wrap rounded-sm border border-white/[0.06] px-2 py-1">
                      <span className="text-slate-100">{m.name}</span>
                      <span className="text-slate-500">{m.version || (m.api_version ? `API ${m.api_version}` : '')}</span>
                      <span className={`px-1.5 rounded-sm ${SUPPORT_CLS[m.support_level] || ''}`}>{t(`hwi_support_${m.support_level}` as any)}</span>
                      {m.status !== 'ok' && <span className="text-red-300">{m.error || m.status}</span>}
                      {m.server_count != null && <span className="text-slate-500">{m.server_count}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(i.not_measurable || []).length > 0 && (
              <details className="text-xs text-slate-500">
                <summary className="cursor-pointer">{t('hwi_not_measurable')} ({i.not_measurable.length})</summary>
                {i.not_measurable.map((n: string, k: number) => <div key={k}>• {n}</div>)}
              </details>
            )}
          </div>
        </Panel>
      ))}
      {!q.isLoading && !(q.data?.instances || []).length && <Panel><div className="py-8 text-center text-sm text-slate-500">{t('hwi_none')}</div></Panel>}

      {f && (
        <Panel title={f.id ? t('hwi_edit') : (isDemo ? 'DEMO' : t('hwi_add'))}>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {isDemo ? (
              <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_kind')}
                <select className={inp} value={f.kind} disabled>
                  {(q.data?.kinds || []).map((k: any) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
                </select></label>
            ) : (
              <div className="text-xs text-slate-400 flex flex-col gap-1 md:col-span-2">
                <label className="flex flex-col gap-1">{t('hwi_tool')}
                  <select className={inp} data-testid="hwi-tool" value={tool} disabled={!!f.id}
                    onChange={e => { const v = e.target.value; setF({ ...f, kind: v === 'dell_ome' ? 'dell_ome' : 'hpe_oneview', mode: v === 'dell_ome' ? f.mode : v }) }}>
                    <option value="dell_ome">{t('hwi_tool_dell_ome')}</option>
                    <option value="ovgd">{t('hwi_tool_ovgd')}</option>
                    <option value="oneview">{t('hwi_tool_oneview')}</option>
                  </select></label>
                <span className="text-[11px] text-slate-500">{t(`hwi_tool_help_${tool}` as any)}</span>
              </div>
            )}
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_label')}
              <input className={inp} value={f.label} onChange={e => setF({ ...f, label: e.target.value })} /></label>
            {!isDemo && (
              <>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_server')}
                  <input className={inp} placeholder={isHpe ? 'ovgd.corp.local' : 'ome.corp.local'} value={f.endpoint} onChange={e => setF({ ...f, endpoint: e.target.value })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_port')}
                  <input className={inp} type="number" value={f.port} onChange={e => setF({ ...f, port: Number(e.target.value) })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_user')}
                  <input className={inp} autoComplete="off" value={f.username} onChange={e => setF({ ...f, username: e.target.value })} /></label>
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_pass')}
                  <input className={inp} type="password" autoComplete="new-password" placeholder={f.id ? t('hwi_pass_keep') : ''} value={f.password} onChange={e => setF({ ...f, password: e.target.value })} /></label>
                {isHpe && (
                  <>
                    <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_domain')}
                      <input className={inp} value={f.login_domain} onChange={e => setF({ ...f, login_domain: e.target.value })} /></label>
                    {f.mode === 'oneview' && (
                      <label className="text-xs text-slate-400 flex flex-col gap-1 md:col-span-2">{t('hwi_appliances')}
                        <textarea className={inp} rows={4} value={appText} onChange={e => setAppText(e.target.value)} /></label>
                    )}
                  </>
                )}
                <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_ca')}
                  <input className={inp} placeholder="/etc/ssl/certs/ca.pem" value={f.ca_bundle_path || ''} onChange={e => setF({ ...f, ca_bundle_path: e.target.value })} /></label>
                <label className="text-xs text-slate-300 flex items-center gap-2">
                  <input type="checkbox" checked={f.verify_ssl} onChange={e => setF({ ...f, verify_ssl: e.target.checked })} /> {t('hwi_verify')}</label>
                <div className="md:col-span-2 rounded-sm border border-white/[0.08] p-3 grid md:grid-cols-2 gap-3" data-testid="hwi-bmc">
                  <div className="md:col-span-2 text-xs text-slate-300">
                    <div className="font-medium text-slate-100">{t('hwi_bmc_title')}</div>
                    <div className="text-[11px] text-slate-500">{t('hwi_bmc_help')}</div>
                  </div>
                  <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwb_np_user')}
                    <input data-testid="hwi-bmc-user" className={inp} autoComplete="off" value={f.bmc_username} onChange={e => setF({ ...f, bmc_username: e.target.value, bmc_clear: false })} /></label>
                  <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwb_np_pass')}
                    <input data-testid="hwi-bmc-pass" className={inp} type="password" autoComplete="new-password" placeholder={f.bmc?.has_password ? t('hwi_pass_keep') : ''} value={f.bmc_password} onChange={e => setF({ ...f, bmc_password: e.target.value, bmc_clear: false })} /></label>
                  <label className="text-xs text-slate-300 flex items-center gap-2">
                    <input type="checkbox" checked={f.bmc_verify_tls} onChange={e => setF({ ...f, bmc_verify_tls: e.target.checked })} /> {t('hwb_np_tls')}</label>
                  {f.bmc?.configured && (
                    <label className="text-xs text-red-300 flex items-center gap-2">
                      <input data-testid="hwi-bmc-clear" type="checkbox" checked={f.bmc_clear} onChange={e => setF({ ...f, bmc_clear: e.target.checked })} /> {t('hwi_bmc_clear')}</label>
                  )}
                </div>
              </>
            )}
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_iv_alarm')}
              <input className={inp} type="number" min={300} value={f.alarm_interval_sec} onChange={e => setF({ ...f, alarm_interval_sec: Number(e.target.value) })} /></label>
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_iv_inv')}
              <input className={inp} type="number" min={3600} value={f.inventory_interval_sec} onChange={e => setF({ ...f, inventory_interval_sec: Number(e.target.value) })} /></label>
            <label className="text-xs text-slate-400 flex flex-col gap-1">{t('hwi_iv_war')}
              <input className={inp} type="number" min={3600} value={f.warranty_interval_sec} onChange={e => setF({ ...f, warranty_interval_sec: Number(e.target.value) })} /></label>
            {(f.kind === 'dell_ome' || (f.kind === 'hpe_oneview' && f.mode === 'oneview')) && (
              <label className="text-xs text-slate-300 flex items-center gap-2 md:col-span-2">
                <input type="checkbox" checked={!!f.fetch_firmware} onChange={e => setF({ ...f, fetch_firmware: e.target.checked })} /> {t('hwi_firmware')}</label>
            )}
          </div>
          {msg && (
            <div className="px-4 pb-3 space-y-1">
              <div className={`text-sm ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>
              {msg.details?.hint && <div className="text-xs text-amber-200">{msg.details.hint}</div>}
              {(msg.details?.appliances || []).length > 0 && (
                <div className="text-xs text-slate-300 space-y-0.5">
                  {msg.details.appliances.map((a: any, k: number) => (
                    <div key={k} className={a.ok ? 'text-emerald-300' : a.skipped ? 'text-slate-500' : 'text-red-300'}>{a.host}: {a.message}</div>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="px-4 pb-4 flex gap-2 justify-end">
            <GhostButton onClick={() => { setF(null); setMsg(null) }}>{t('cancel')}</GhostButton>
            <GhostButton accent={NEON.blue} onClick={test} disabled={busy || wait > 0}>{wait > 0 ? t('hwi_test_wait', { n: wait }) : t('hwi_test')}</GhostButton>
            <PrimaryButton accent={NEON.blue} onClick={save} disabled={busy}>{t('save')}</PrimaryButton>
          </div>
        </Panel>
      )}
    </div>
  )
}
