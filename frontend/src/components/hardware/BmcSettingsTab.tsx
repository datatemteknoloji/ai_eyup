import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

/**
 * Ayarlar → BMC: GLOBAL ve üretici (Dell / HPE) varsayılan BMC kimlikleri.
 * Çözüm sırası (sabit, «başarısız olursa sonrakini dene» YOK — hesap kilitlenmesin):
 *   manuel (host) > portal entegrasyonu > üretici (Dell/HPE) > global.
 * Parola hiçbir zaman geri gösterilmez; boş bırakılırsa mevcut korunur.
 */
async function call(path: string, method: 'GET' | 'POST' | 'DELETE', body?: unknown) {
  const r = await fetch(`${API_BASE_URL}/hw/bmc${path}`, {
    method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

type Slot = { id: string; scope: 'global' | 'vendor'; vendor?: 'dell' | 'hpe'; title: string }

const Card: React.FC<{ slot: Slot; profile: any | undefined; onDone: () => void }> = ({ slot, profile, onDone }) => {
  const t = useT()
  const [user, setUser] = useState<string>(profile?.username || '')
  const [pass, setPass] = useState('')
  const [tls, setTls] = useState<boolean>(!!profile?.verify_tls)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  React.useEffect(() => { setUser(profile?.username || ''); setTls(!!profile?.verify_tls) }, [profile?.id, profile?.username, profile?.verify_tls])
  const save = useMutation({
    mutationFn: () => call('/profiles', 'POST', {
      scope: slot.scope, vendor: slot.vendor, name: slot.title, username: user.trim(), password: pass, verify_tls: tls,
    }),
    onSuccess: () => { setErr(null); setOk(true); setPass(''); onDone() },
    onError: (e: any) => { setOk(false); setErr(e.message) },
  })
  const del = useMutation({
    mutationFn: () => call(`/profiles/${profile.id}`, 'DELETE'),
    onSuccess: () => { setErr(null); setOk(false); setPass(''); setUser(''); onDone() },
    onError: (e: any) => setErr(e.message),
  })
  const canSave = !!user.trim() && (!!pass || !!profile?.has_password)
  return (
    <div data-testid={`bmcset-${slot.id}`} className="rounded-lg border border-white/[0.08] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">{slot.title}</h3>
        {profile?.has_password && <span className="text-[11px] text-emerald-400">{t('set_pw_dot')}</span>}
      </div>
      <label className="block space-y-1">
        <span className="text-[11px] text-slate-400">{t('hwb_np_user')}</span>
        <input data-testid={`bmcset-${slot.id}-user`} autoComplete="off" value={user} onChange={e => setUser(e.target.value)}
          className="w-full bg-slate-900 border border-white/10 rounded-sm px-2 py-1.5 text-sm text-slate-100" />
      </label>
      <label className="block space-y-1">
        <span className="text-[11px] text-slate-400">{t('hwb_np_pass')}</span>
        <input data-testid={`bmcset-${slot.id}-pass`} type="password" autoComplete="new-password" value={pass} onChange={e => setPass(e.target.value)}
          placeholder={profile?.has_password ? t('hwi_pass_keep') : ''}
          className="w-full bg-slate-900 border border-white/10 rounded-sm px-2 py-1.5 text-sm text-slate-100" />
      </label>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input data-testid={`bmcset-${slot.id}-tls`} type="checkbox" checked={tls} onChange={e => setTls(e.target.checked)} />
        {t('hwb_np_tls')}
      </label>
      {!tls && <div className="text-[11px] text-amber-400">{t('bmcset_tls_warn')}</div>}
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      {ok && <div className="text-xs text-emerald-300">{t('bmcset_saved')}</div>}
      <div className="flex gap-2">
        <button type="button" data-testid={`bmcset-${slot.id}-save`} disabled={!canSave || save.isPending} onClick={() => save.mutate()}
          className="px-3 py-1.5 rounded-sm border border-blue-500/40 bg-blue-500/10 text-blue-200 text-xs disabled:opacity-40">{t('hwb_save')}</button>
        {profile && (
          <button type="button" data-testid={`bmcset-${slot.id}-del`} disabled={del.isPending}
            onClick={() => { if (window.confirm(t('hwb_del_profile'))) del.mutate() }}
            className="px-3 py-1.5 rounded-sm border border-white/[0.1] text-red-300 text-xs">{t('delete')}</button>
        )}
      </div>
    </div>
  )
}

export const BmcSettingsTab: React.FC = () => {
  const t = useT()
  const qc = useQueryClient()
  const q = useQuery<any>({ queryKey: ['hw-bmc-overview'], queryFn: () => call('/overview', 'GET') })
  const profiles: any[] = q.data?.profiles || []
  const find = (scope: string, vendor?: string) => profiles.find(p => p.scope === scope && (scope !== 'vendor' || p.vendor === vendor))
  const slots: Slot[] = [
    { id: 'global', scope: 'global', title: t('bmcset_global') },
    { id: 'dell', scope: 'vendor', vendor: 'dell', title: t('bmcset_dell') },
    { id: 'hpe', scope: 'vendor', vendor: 'hpe', title: t('bmcset_hpe') },
  ]
  return (
    <div data-testid="bmc-settings" className="max-w-4xl space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-white mb-1">{t('set_tab_bmc')}</h2>
        <p className="text-sm text-slate-400">{t('bmcset_intro')}</p>
      </div>
      <ol className="text-xs text-slate-300 list-decimal list-inside space-y-0.5" data-testid="bmcset-order">
        <li>{t('hwb_level_host')}</li>
        <li>{t('hwb_level_instance')}</li>
        <li>{t('hwb_level_vendor')}</li>
        <li>{t('hwb_level_global')}</li>
      </ol>
      <p className="text-xs text-slate-500">{t('bmcset_lockout')}</p>
      <p className="text-xs text-slate-500">{t('hwb_note')}</p>
      {q.data && (
        <div className="text-xs text-slate-400 flex flex-wrap gap-x-4" data-testid="bmcset-flags">
          <span>{t('hwb_flag_ipmi')}: <b className={q.data.flags?.ipmi_inband ? 'text-emerald-300' : 'text-slate-500'}>{q.data.flags?.ipmi_inband ? t('hwl_src_on') : t('hwl_src_off')}</b></span>
          <span>{t('hwb_flag_redfish')}: <b className={q.data.flags?.bmc_redfish ? 'text-emerald-300' : 'text-slate-500'}>{q.data.flags?.bmc_redfish ? t('hwl_src_on') : t('hwl_src_off')}</b></span>
          <span className="text-slate-500">{t('bmcset_flags_where')}</span>
        </div>
      )}
      {q.isError && <div role="alert" className="text-sm text-red-300">{t('hwb_load_err')}</div>}
      <div className="grid gap-4 md:grid-cols-3">
        {slots.map(s => (
          <Card key={s.id} slot={s} profile={find(s.scope, s.vendor)} onDone={() => qc.invalidateQueries({ queryKey: ['hw-bmc-overview'] })} />
        ))}
      </div>
    </div>
  )
}

export default BmcSettingsTab
