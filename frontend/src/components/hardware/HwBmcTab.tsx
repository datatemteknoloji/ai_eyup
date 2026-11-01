import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'
import { EmptyState, Select } from '../aiops/ui'
import { Panel } from '../insights/insightsKit'

/**
 * Faz 3b — «BMC» sekmesi: her fiziksel makinenin iLO/iDRAC adresi, hangi kimlik profilinin kullanılacağı ve durumu.
 * Okuma: `hardware` modülü. YAZMA (IP, profil, aç/kapa, test): yalnız admin (sunucu da zorlar).
 * Parola hiçbir yerde gösterilmez. Kimlik reddedilirse BMC durur; yalnız başarılı «Bağlantıyı test et» sürdürür.
 */
const STATUS_CLS: Record<string, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  auth_halted: 'bg-red-500/15 text-red-300 border-red-500/30',
  auth_failed: 'bg-red-500/15 text-red-300 border-red-500/30',
  unreachable: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  unsupported: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  no_cred: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  no_ip: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  never: 'bg-slate-500/15 text-slate-400 border-slate-500/20',
}

async function call(path: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', body?: unknown) {
  const r = await fetch(`${API_BASE_URL}/hw/bmc${path}`, {
    method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

const IpCell: React.FC<{ e: any; canEdit: boolean; onSave: (ip: string) => void }> = ({ e, canEdit, onSave }) => {
  const t = useT()
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(e.bmc_ip || '')
  if (edit) {
    return (
      <span className="inline-flex items-center gap-1">
        <input data-testid="hwb-ip-input" value={v} onChange={ev => setV(ev.target.value)} placeholder="10.0.0.5"
          className="w-36 bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-xs text-slate-100" />
        <button type="button" data-testid="hwb-ip-save" className="text-[11px] text-emerald-300" onClick={() => { onSave(v.trim()); setEdit(false) }}>{t('hwb_save')}</button>
        {e.ip_source === 'manual' && <button type="button" data-testid="hwb-ip-clear" className="text-[11px] text-slate-400" onClick={() => { onSave(''); setEdit(false) }}>{t('hwb_clear_ip')}</button>}
        <button type="button" className="text-[11px] text-slate-500" onClick={() => setEdit(false)}>✕</button>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-xs text-slate-200">{e.bmc_ip || <span className="text-slate-500">—</span>}</span>
      {e.bmc_ip && <span className="text-[10px] text-slate-500 border border-white/10 rounded-sm px-1">{t(`hwb_ip_${e.ip_source}` as any)}</span>}
      {canEdit && <button type="button" data-testid="hwb-ip-edit" className="text-[11px] text-blue-300 hover:text-blue-200" onClick={() => { setV(e.bmc_ip || ''); setEdit(true) }}>{t('hwb_edit_ip')}</button>}
    </span>
  )
}

/** Bu makineye ÖZEL BMC hesabı (arkada 1:1 host profili). Parola geri doldurulmaz; boş bırakılırsa mevcut korunur. */
const AccountCell: React.FC<{ e: any; canEdit: boolean; onSave: (b: any) => void; busy: boolean }> = ({ e, canEdit, onSave, busy }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [tls, setTls] = useState(false)
  const acct = e.account
  const begin = () => { setUser(acct?.username || ''); setPass(''); setTls(!!acct?.verify_tls); setOpen(true) }
  const canSave = !!user.trim() && (!!pass || !!acct?.has_password)
  const level = e.resolved ? (e.resolved.private ? t('hwb_level_private') : t(`hwb_level_${e.resolved.level}` as any)) : ''
  return (
    <div data-testid="hwb-cred">
      {e.resolved
        ? <>{e.resolved.username} <span className="text-[10px] text-slate-500 border border-white/10 rounded-sm px-1">{level}</span></>
        : <span className="text-amber-300">{t('hwb_no_cred')}</span>}
      {canEdit && !open && (
        <button type="button" data-testid="hwb-acct-edit" className="ml-2 text-[11px] text-blue-300 hover:text-blue-200" onClick={begin}>{t('hwb_acct')}</button>
      )}
      {open && (
        <div data-testid="hwb-acct-form" className="mt-2 space-y-1.5 rounded-sm border border-white/[0.08] p-2 max-w-[260px]">
          <input data-testid="hwb-acct-user" autoComplete="off" placeholder={t('hwb_np_user')} value={user} onChange={ev => setUser(ev.target.value)}
            className="w-full bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-xs text-slate-100" />
          <input data-testid="hwb-acct-pass" type="password" autoComplete="new-password" value={pass} onChange={ev => setPass(ev.target.value)}
            placeholder={acct?.has_password ? t('hwi_pass_keep') : t('hwb_np_pass')}
            className="w-full bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-xs text-slate-100" />
          <label className="flex items-center gap-1 text-[11px] text-slate-300"><input type="checkbox" checked={tls} onChange={ev => setTls(ev.target.checked)} />{t('hwb_np_tls')}</label>
          <div className="flex gap-2 text-[11px]">
            <button type="button" data-testid="hwb-acct-save" disabled={!canSave || busy} className="text-emerald-300 disabled:opacity-40"
              onClick={() => { onSave({ username: user.trim(), password: pass, verify_tls: tls }); setOpen(false) }}>{t('hwb_save')}</button>
            {acct && <button type="button" data-testid="hwb-acct-clear" className="text-red-300"
              onClick={() => { if (window.confirm(t('hwb_acct_clear_confirm'))) { onSave({ clear: true }); setOpen(false) } }}>{t('hwb_acct_clear')}</button>}
            <button type="button" className="text-slate-500" onClick={() => setOpen(false)}>✕</button>
          </div>
        </div>
      )}
    </div>
  )
}

export const HwBmcTab: React.FC = () => {
  const t = useT()
  const auth = useAuth() as any
  const isAdmin = auth?.user?.role === 'admin'
  const qc = useQueryClient()
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [msg, setMsg] = useState<Record<number, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const [bulkProfile, setBulkProfile] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [np, setNp] = useState({ name: '', username: '', password: '', verify_tls: false })

  const q = useQuery<any>({ queryKey: ['hw-bmc-overview'], queryFn: () => call('/overview', 'GET'), refetchInterval: 60_000 })
  const refresh = () => qc.invalidateQueries({ queryKey: ['hw-bmc-overview'] })
  const onErr = (e: any) => setErr(e.message || String(e))
  const patch = useMutation({
    mutationFn: (v: { id: number; body: any }) => call(`/endpoints/${v.id}`, 'PUT', v.body),
    onSuccess: () => { setErr(null); refresh() }, onError: onErr,
  })
  const account = useMutation({
    mutationFn: (v: { id: number; body: any }) => call(`/endpoints/${v.id}/account`, 'PUT', v.body),
    onSuccess: () => { setErr(null); refresh() }, onError: onErr,
  })
  const bulk = useMutation({
    mutationFn: (body: any) => call('/endpoints/bulk', 'POST', body),
    onSuccess: () => { setErr(null); setSel(new Set()); refresh() }, onError: onErr,
  })
  const test = useMutation({
    mutationFn: (id: number) => call(`/endpoints/${id}/test`, 'POST'),
    onSuccess: (r: any, id: number) => {
      setMsg(m => ({ ...m, [id]: r.ok ? t('hwb_test_ok') : (r.message || t(`hwb_status_${r.status}` as any)) }))
      refresh()
    },
    onError: (e: any, id: number) => setMsg(m => ({ ...m, [id]: e.message })),
  })
  const addProfile = useMutation({
    mutationFn: () => call('/profiles', 'POST', { scope: 'host', ...np }),
    onSuccess: () => { setErr(null); setNp({ name: '', username: '', password: '', verify_tls: false }); refresh() }, onError: onErr,
  })
  const delProfile = useMutation({ mutationFn: (id: number) => call(`/profiles/${id}`, 'DELETE'), onSuccess: refresh, onError: onErr })

  const d = q.data
  const all: any[] = d?.endpoints || []
  const statusOf = (e: any) => (e.auth_halted ? 'auth_halted' : e.status || 'never')
  const rows = useMemo(() => all.filter(e => !fStatus || statusOf(e) === fStatus), [all, fStatus])
  const hostProfiles: any[] = (d?.profiles || []).filter((p: any) => p.scope === 'host')
  const byStatus: Record<string, number> = d?.counts?.by_status || {}
  const toggle = (id: number) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  if (q.isLoading) return <div className="text-sm text-slate-500">{t('hw_loading')}</div>
  if (q.isError) return <div role="alert" className="text-sm text-red-300">{t('hwb_load_err')}</div>

  return (
    <div data-testid="hw-bmc-tab" className="space-y-3">
      <Panel>
        <div className="p-3 space-y-2 text-xs text-slate-400">
          <div className="flex flex-wrap gap-x-4 gap-y-1" data-testid="hwb-flags">
            <span>{t('hwb_flag_ipmi')}: <b data-testid="hwb-flag-ipmi" className={d.flags?.ipmi_inband ? 'text-emerald-300' : 'text-slate-500'}>{d.flags?.ipmi_inband ? t('hwl_src_on') : t('hwl_src_off')}</b></span>
            <span>{t('hwb_flag_redfish')}: <b data-testid="hwb-flag-redfish" className={d.flags?.bmc_redfish ? 'text-emerald-300' : 'text-slate-500'}>{d.flags?.bmc_redfish ? t('hwl_src_on') : t('hwl_src_off')}</b></span>
            <Link to="/settings" className="text-blue-300 hover:text-blue-200">{t('hwb_flags_link')}</Link>
          </div>
          <div>{t('hwb_note')}</div>
          <div className="flex flex-wrap gap-1.5" data-testid="hwb-status-chips">
            <button type="button" data-testid="hwb-status-all" aria-pressed={fStatus === ''} onClick={() => setFStatus('')}
              className={`px-2 py-0.5 rounded-full border text-[11px] ${fStatus === '' ? 'bg-blue-600 border-blue-500 text-white' : 'border-white/[0.1] text-slate-300'}`}>
              {t('hw_filter_all')} {d.counts?.total ?? 0}
            </button>
            {Object.keys(byStatus).map(s => (
              <button key={s} type="button" data-testid={`hwb-status-${s}`} aria-pressed={fStatus === s} onClick={() => setFStatus(fStatus === s ? '' : s)}
                className={`px-2 py-0.5 rounded-full border text-[11px] ${fStatus === s ? 'bg-blue-600 border-blue-500 text-white' : 'border-white/[0.1] text-slate-300'}`}>
                {t(`hwb_status_${s}` as any)} {byStatus[s]}
              </button>
            ))}
          </div>
          {err && <div role="alert" className="text-red-300">{err}</div>}
        </div>
      </Panel>

      {isAdmin && sel.size > 0 && (
        <Panel>
          <div data-testid="hwb-bulk" className="p-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-300">{t('hwb_selected', { n: sel.size })}</span>
            <Select value={bulkProfile} onChange={setBulkProfile}>
              <option value="">{t('hwb_pick_profile')}</option>
              <option value="__clear">{t('hwb_clear_profile')}</option>
              {hostProfiles.map((p: any) => <option key={p.id} value={String(p.id)}>{p.name} ({p.username})</option>)}
            </Select>
            <button type="button" data-testid="hwb-bulk-apply" disabled={!bulkProfile || bulk.isPending}
              onClick={() => bulk.mutate({ ids: [...sel], profile_id: bulkProfile === '__clear' ? null : Number(bulkProfile) })}
              className="px-2 py-1 rounded-sm border border-blue-500/40 bg-blue-500/10 text-blue-200 disabled:opacity-40">{t('hwb_apply')}</button>
            <button type="button" onClick={() => bulk.mutate({ ids: [...sel], enabled: true })} className="px-2 py-1 rounded-sm border border-white/[0.1] text-slate-300">{t('hwb_enable')}</button>
            <button type="button" onClick={() => bulk.mutate({ ids: [...sel], enabled: false })} className="px-2 py-1 rounded-sm border border-white/[0.1] text-slate-300">{t('hwb_disable')}</button>
          </div>
        </Panel>
      )}

      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                {isAdmin && <th className="px-3 py-2 w-6" />}
                {['hwb_col_host', 'hwb_col_vendor', 'hwb_col_ip', 'hwb_col_cred', 'hwb_col_status', 'hwb_col_ipmi', 'hwb_col_last', 'hwb_col_on'].map(k => <th key={k} className="px-3 py-2 font-medium">{t(k as any)}</th>)}
                {isAdmin && <th className="px-3 py-2" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((e: any) => {
                const st = statusOf(e)
                return (
                  <tr key={e.id} data-testid="hwb-row" className="border-t border-white/[0.05] align-top">
                    {isAdmin && <td className="px-3 py-2"><input type="checkbox" data-testid="hwb-check" checked={sel.has(e.id)} onChange={() => toggle(e.id)} /></td>}
                    <td className="px-3 py-2 text-sm text-white">
                      {e.target?.name}
                      <span className="ml-2 text-[10px] text-slate-400 border border-white/10 rounded-sm px-1 align-middle">{t(`hw_class_${e.host_class}` as any)}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-300 uppercase">{e.vendor || '—'}</td>
                    <td className="px-3 py-2"><IpCell e={e} canEdit={isAdmin} onSave={ip => patch.mutate({ id: e.id, body: { bmc_ip: ip } })} /></td>
                    <td className="px-3 py-2 text-xs text-slate-300">
                      <AccountCell e={e} canEdit={isAdmin} busy={account.isPending} onSave={b => account.mutate({ id: e.id, body: b })} />
                    </td>
                    <td className="px-3 py-2">
                      <span data-testid={`hwb-status-badge-${st}`} className={`text-[11px] px-1.5 py-0.5 rounded-sm border ${STATUS_CLS[st] || STATUS_CLS.never}`}>{t(`hwb_status_${st}` as any)}</span>
                      {e.last_error && st !== 'ok' && <div className="text-[10px] text-slate-500 mt-0.5 max-w-xs wrap-break-word">{e.last_error}</div>}
                      {msg[e.id] && <div data-testid="hwb-test-msg" className="text-[10px] text-slate-400 mt-0.5 max-w-xs wrap-break-word">{msg[e.id]}</div>}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-300">{e.ipmi_status ? t(`hwb_ipmi_${e.ipmi_status}` as any) : '—'}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{fmt(e.last_run_at)}</td>
                    <td className="px-3 py-2 text-xs">
                      <input type="checkbox" data-testid="hwb-enabled" checked={!!e.enabled} disabled={!isAdmin}
                        onChange={ev => patch.mutate({ id: e.id, body: { enabled: ev.target.checked } })} />
                    </td>
                    {isAdmin && (
                      <td className="px-3 py-2">
                        <button type="button" data-testid="hwb-test" disabled={test.isPending || !e.bmc_ip || !e.resolved}
                          onClick={() => test.mutate(e.id)}
                          className="text-[11px] px-2 py-0.5 rounded-sm border border-white/[0.12] text-slate-200 hover:bg-white/[0.05] disabled:opacity-40">{t('hwb_test')}</button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div data-testid="hwb-empty"><EmptyState text={t('hwb_none')} /></div>}
        </div>
      </Panel>

      <Panel title={t('hwb_profiles')}>
        <div className="p-3 space-y-2 text-xs" data-testid="hwb-profiles">
          {(d.profiles || []).map((p: any) => (
            <div key={p.id} className="flex flex-wrap items-center gap-2 text-slate-300">
              <span className="text-slate-100">{p.name}</span>
              <span className="text-[10px] text-slate-500 border border-white/10 rounded-sm px-1">{t(`hwb_scope_${p.scope}` as any)}{p.vendor ? ` · ${p.vendor}` : ''}{p.instance_label ? ` · ${p.instance_label}` : ''}</span>
              <span>{p.username}</span>
              <span className="text-emerald-400">{p.has_password ? t('set_pw_dot') : ''}</span>
              {!p.verify_tls && <span className="text-[10px] text-amber-400">{t('hwb_tls_off')}</span>}
              {isAdmin && p.scope === 'host' && (
                <button type="button" className="text-[11px] text-red-300" onClick={() => { if (window.confirm(t('hwb_del_profile'))) delProfile.mutate(p.id) }}>{t('delete')}</button>
              )}
            </div>
          ))}
          {!(d.profiles || []).length && <div className="text-slate-500">{t('hwb_no_profiles')}</div>}
          {isAdmin && (
            <div className="pt-2 border-t border-white/[0.06] flex flex-wrap items-end gap-2" data-testid="hwb-new-profile">
              <label className="space-y-0.5"><div className="text-[10px] text-slate-500">{t('hwb_np_name')}</div>
                <input className="bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-slate-100" value={np.name} onChange={ev => setNp({ ...np, name: ev.target.value })} /></label>
              <label className="space-y-0.5"><div className="text-[10px] text-slate-500">{t('hwb_np_user')}</div>
                <input className="bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-slate-100" autoComplete="off" value={np.username} onChange={ev => setNp({ ...np, username: ev.target.value })} /></label>
              <label className="space-y-0.5"><div className="text-[10px] text-slate-500">{t('hwb_np_pass')}</div>
                <input type="password" autoComplete="new-password" className="bg-slate-900 border border-white/10 rounded-sm px-1.5 py-0.5 text-slate-100" value={np.password} onChange={ev => setNp({ ...np, password: ev.target.value })} /></label>
              <label className="flex items-center gap-1 text-slate-300"><input type="checkbox" checked={np.verify_tls} onChange={ev => setNp({ ...np, verify_tls: ev.target.checked })} />{t('hwb_np_tls')}</label>
              <button type="button" data-testid="hwb-np-save" disabled={!np.name.trim() || !np.username.trim() || !np.password || addProfile.isPending}
                onClick={() => addProfile.mutate()}
                className="px-2 py-1 rounded-sm border border-blue-500/40 bg-blue-500/10 text-blue-200 disabled:opacity-40">{t('hwb_np_add')}</button>
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}

export default HwBmcTab
