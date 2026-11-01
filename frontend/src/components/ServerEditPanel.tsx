import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

/**
 * Linux sunucu çekmecesi › «Düzenle».
 *  - Genel alanlar → `PUT /servers/{id}` (yalnız DEĞİŞEN alanlar; `connection_config` ASLA gönderilmez — yanıttaki maskeli değer
 *    gerçek parolayı bozardı).
 *  - SSH kimlik bilgisi → `POST /servers/{id}/credentials` (boş parola/anahtar mevcut değeri korur; backend bağlantıyı dener).
 *  - BMC (iLO/iDRAC; yalnız admin + sanal olmayan) → `POST /hw/bmc/server-account` (parola geri doldurulmaz).
 * Kimlik reddedilirse BMC durur; yalnız başarılı «Bağlantıyı test et» sürdürür (hesap kilitlenmesin).
 */
export interface EditableServer {
  id: number
  name: string
  hostname?: string | null
  ip_address?: string | null
  server_type?: string | null
  cpu_cores?: number | null
  memory_gb?: number | null
  ssh_username?: string | null
  connection_config?: any
}

async function api(method: 'GET' | 'POST' | 'PUT', path: string, body?: unknown) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j?.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

const INPUT = 'w-full bg-slate-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-sm text-slate-100 focus:outline-hidden focus:border-blue-500'
const LABEL = 'block text-[10px] text-slate-500 uppercase tracking-wide mb-1'

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block"><span className={LABEL}>{label}</span>{children}</label>
)

const BmcSection: React.FC<{ serverId: number }> = ({ serverId }) => {
  const t = useT()
  const qc = useQueryClient()
  const key = ['hw-bmc-server-account', serverId]
  const q = useQuery<any>({ queryKey: key, queryFn: () => api('GET', `/hw/bmc/server-account/${serverId}`), retry: false })
  const d = q.data
  const [ip, setIp] = useState<string | null>(null)
  const [user, setUser] = useState<string | null>(null)
  const [pass, setPass] = useState('')
  const [tls, setTls] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  if (q.isLoading) return null
  if (q.isError) return <div role="alert" className="text-xs text-red-300">{(q.error as Error).message}</div>

  const curIp = d?.bmc_ip || ''
  const curUser = d?.account?.username || ''
  const hasAcct = !!d?.account
  const vIp = ip ?? curIp
  const vUser = user ?? curUser
  const vTls = tls ?? !!d?.account?.verify_tls
  const manualIp = d?.ip_source === 'manual'
  const dirty = vIp.trim() !== curIp || vUser.trim() !== curUser || !!pass || vTls !== !!d?.account?.verify_tls

  const refresh = () => { setIp(null); setUser(null); setPass(''); setTls(null); qc.invalidateQueries({ queryKey: key }) }

  const save = async () => {
    setMsg(null)
    if (!hasAcct && !!vUser.trim() !== !!pass) { setMsg({ ok: false, text: t('ph_bmc_pair') }); return }
    setBusy(true)
    try {
      const wantsAcct = !!vUser.trim() || !!pass
      if (d?.endpoint_id && manualIp && !vIp.trim() && curIp) {
        await api('PUT', `/hw/bmc/endpoints/${d.endpoint_id}`, { bmc_ip: '' })   // elle girişi kaldır → keşfe dön
      }
      if (vIp.trim() || wantsAcct) {
        await api('POST', '/hw/bmc/server-account', {
          server_id: serverId, bmc_ip: vIp.trim() || null,
          username: vUser.trim(), password: pass || null, verify_tls: vTls,
        })
      }
      setMsg({ ok: true, text: t('se_bmc_saved') })
      refresh()
    } catch (e: any) {
      setMsg({ ok: false, text: t('se_save_err', { e: e.message }) })
    } finally { setBusy(false) }
  }

  const test = async () => {
    if (!d?.endpoint_id) return
    setBusy(true); setMsg(null)
    try {
      const r = await api('POST', `/hw/bmc/endpoints/${d.endpoint_id}/test`)
      setMsg({ ok: !!r.ok, text: r.ok ? t('hwb_test_ok') : (r.message || t(`hwb_status_${r.status}` as any)) })
      qc.invalidateQueries({ queryKey: key })
    } catch (e: any) {
      setMsg({ ok: false, text: e.message })
    } finally { setBusy(false) }
  }

  const clearAcct = async () => {
    if (!d?.endpoint_id || !window.confirm(t('se_bmc_clear_confirm'))) return
    setBusy(true); setMsg(null)
    try { await api('PUT', `/hw/bmc/endpoints/${d.endpoint_id}/account`, { clear: true }); refresh() }
    catch (e: any) { setMsg({ ok: false, text: t('se_save_err', { e: e.message }) }) }
    finally { setBusy(false) }
  }

  return (
    <section data-testid="se-bmc" className="space-y-3 border-t border-white/[0.06] pt-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-200">{t('se_bmc_section')}</h3>
        <p className="text-xs text-slate-500 mt-1">{t('se_bmc_help')}</p>
      </div>
      <p className="text-xs text-slate-400" data-testid="se-bmc-current">
        {t('se_bmc_current')}: {d?.resolved ? <b className="text-slate-200">{d.resolved.username}</b> : <span className="text-amber-300">{t('se_bmc_none')}</span>}
      </p>
      {d?.auth_halted && <div role="alert" data-testid="se-bmc-halted" className="text-xs text-red-300">{t('se_bmc_halted')}</div>}
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('ph_bmc_ip')}>
          <input data-testid="se-bmc-ip" className={INPUT} placeholder="10.0.0.5" value={vIp} onChange={e => setIp(e.target.value)} />
        </Field>
        <Field label={t('ph_bmc_user')}>
          <input data-testid="se-bmc-user" autoComplete="off" className={INPUT} value={vUser} onChange={e => setUser(e.target.value)} />
        </Field>
        <Field label={t('ph_bmc_pass')}>
          <input data-testid="se-bmc-pass" type="password" autoComplete="new-password" className={INPUT} value={pass}
            placeholder={hasAcct ? t('hwi_pass_keep') : ''} onChange={e => setPass(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-xs text-slate-300 self-end pb-2">
          <input type="checkbox" checked={vTls} onChange={e => setTls(e.target.checked)} />{t('hwb_np_tls')}
        </label>
      </div>
      {msg && <div role={msg.ok ? 'status' : 'alert'} data-testid="se-bmc-msg" className={`text-xs ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>}
      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="se-bmc-save" disabled={busy || !dirty} onClick={save}
          className="px-3 py-1.5 text-xs rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40">{t('save')}</button>
        {d?.endpoint_id && (
          <button type="button" data-testid="se-bmc-test" disabled={busy || dirty} onClick={test}
            className="px-3 py-1.5 text-xs rounded-lg border border-white/10 text-slate-200 hover:bg-white/[0.06] disabled:opacity-40">{t('hwb_test')}</button>
        )}
        {hasAcct && (
          <button type="button" data-testid="se-bmc-clear" disabled={busy} onClick={clearAcct}
            className="px-3 py-1.5 text-xs rounded-lg border border-red-500/30 text-red-300 hover:bg-red-500/10 disabled:opacity-40">{t('se_bmc_clear')}</button>
        )}
      </div>
    </section>
  )
}

export const ServerEditPanel: React.FC<{
  server: EditableServer
  isAdmin: boolean
  onSaved: (patch: Partial<EditableServer>) => void
  onClose: () => void
}> = ({ server, isAdmin, onSaved, onClose }) => {
  const t = useT()
  const cfg = server.connection_config || {}
  const curUser = server.ssh_username || cfg.username || ''
  const curPort = cfg.port ? String(cfg.port) : '22'
  const [f, setF] = useState({
    name: server.name || '',
    hostname: server.hostname || '',
    ip_address: server.ip_address || '',
    server_type: (server.server_type || '').toUpperCase(),
    cpu_cores: server.cpu_cores != null ? String(server.cpu_cores) : '',
    memory_gb: server.memory_gb != null ? String(server.memory_gb) : '',
    ssh_user: curUser, ssh_port: curPort, ssh_pass: '', ssh_sudo: '', ssh_key: '',
  })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF(p => ({ ...p, [k]: e.target.value }))
  const physical = f.server_type !== 'VIRTUAL'

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg(null)
    if (!f.name.trim()) { setMsg({ ok: false, text: t('se_name_required') }); return }
    const patch: Record<string, any> = {}
    if (f.name.trim() !== (server.name || '')) patch.name = f.name.trim()
    if (f.hostname.trim() !== (server.hostname || '')) patch.hostname = f.hostname.trim()
    if (f.ip_address.trim() !== (server.ip_address || '')) patch.ip_address = f.ip_address.trim()
    if (f.server_type && f.server_type !== (server.server_type || '').toUpperCase()) patch.server_type = f.server_type
    const cpu = parseInt(f.cpu_cores, 10)
    if (!Number.isNaN(cpu) && cpu !== server.cpu_cores) patch.cpu_cores = cpu
    const mem = parseInt(f.memory_gb, 10)
    if (!Number.isNaN(mem) && mem !== server.memory_gb) patch.memory_gb = mem

    const cred: Record<string, any> = {}
    if (f.ssh_user.trim() && f.ssh_user.trim() !== curUser) cred.username = f.ssh_user.trim()
    if (f.ssh_pass) cred.password = f.ssh_pass
    if (f.ssh_sudo) cred.sudo_password = f.ssh_sudo
    if (f.ssh_key.trim()) cred.private_key = f.ssh_key
    const port = parseInt(f.ssh_port, 10)
    if (!Number.isNaN(port) && String(port) !== curPort) cred.port = port

    if (!Object.keys(patch).length && !Object.keys(cred).length) { setMsg({ ok: true, text: t('se_no_changes') }); return }
    setBusy(true)
    try {
      if (Object.keys(patch).length) await api('PUT', `/servers/${server.id}`, patch)
      let text = t('se_saved')
      let ok = true
      const done: Partial<EditableServer> = { ...patch }
      if (Object.keys(cred).length) {
        const r = await api('POST', `/servers/${server.id}/credentials`, cred)
        if (cred.username) done.ssh_username = cred.username
        text = r.ai_ready ? t('se_ssh_ok') : t('se_ssh_fail')
        ok = !!r.ai_ready
      }
      setF(p => ({ ...p, ssh_pass: '', ssh_sudo: '', ssh_key: '' }))
      setMsg({ ok, text })
      onSaved(done)
    } catch (err: any) {
      setMsg({ ok: false, text: t('se_save_err', { e: err.message }) })
    } finally { setBusy(false) }
  }

  return (
    <div data-testid="server-edit-panel" className="space-y-4">
      <form onSubmit={save} className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">{t('se_title')}</h3>
          <button type="button" onClick={onClose} className="text-xs text-slate-400 hover:text-white">{t('cancel')}</button>
        </div>

        <section className="space-y-3">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">{t('se_general')}</h4>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('label_server_name')}><input data-testid="se-name" className={INPUT} value={f.name} onChange={set('name')} /></Field>
            <Field label={t('se_hostname')}><input data-testid="se-hostname" className={INPUT} value={f.hostname} onChange={set('hostname')} /></Field>
            <Field label={t('label_ip')}><input data-testid="se-ip" className={INPUT} value={f.ip_address} onChange={set('ip_address')} /></Field>
            <Field label={t('label_type')}>
              <select data-testid="se-type" className={INPUT} value={f.server_type} onChange={set('server_type')}>
                {f.server_type && !['PHYSICAL', 'VIRTUAL'].includes(f.server_type) && <option value={f.server_type}>{f.server_type}</option>}
                <option value="PHYSICAL">PHYSICAL</option>
                <option value="VIRTUAL">VIRTUAL</option>
              </select>
            </Field>
            <Field label={t('se_cpu')}><input data-testid="se-cpu" type="number" min={0} className={INPUT} value={f.cpu_cores} onChange={set('cpu_cores')} /></Field>
            <Field label={t('se_memory_gb')}><input data-testid="se-mem" type="number" min={0} className={INPUT} value={f.memory_gb} onChange={set('memory_gb')} /></Field>
          </div>
          <p className="text-[11px] text-slate-500">{t('se_ip_note')}</p>
        </section>

        <section className="space-y-3 border-t border-white/[0.06] pt-4">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">{t('se_ssh_section')}</h4>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('label_ssh_user')}><input data-testid="se-ssh-user" autoComplete="off" className={INPUT} value={f.ssh_user} onChange={set('ssh_user')} /></Field>
            <Field label={t('se_ssh_port')}><input data-testid="se-ssh-port" type="number" min={1} max={65535} className={INPUT} value={f.ssh_port} onChange={set('ssh_port')} /></Field>
            <Field label={t('hwb_np_pass')}>
              <input data-testid="se-ssh-pass" type="password" autoComplete="new-password" className={INPUT} placeholder={t('hwi_pass_keep')} value={f.ssh_pass} onChange={set('ssh_pass')} />
            </Field>
            <Field label={t('se_ssh_sudo')}>
              <input data-testid="se-ssh-sudo" type="password" autoComplete="new-password" className={INPUT} placeholder={t('hwi_pass_keep')} value={f.ssh_sudo} onChange={set('ssh_sudo')} />
            </Field>
          </div>
          <Field label={t('se_ssh_key')}>
            <textarea data-testid="se-ssh-key" rows={3} autoComplete="off" spellCheck={false} className={`${INPUT} font-mono text-xs`} placeholder={t('hwi_pass_keep')} value={f.ssh_key} onChange={set('ssh_key')} />
          </Field>
          <p className="text-[11px] text-slate-500">{t('se_ssh_help')}</p>
        </section>

        {msg && <div role={msg.ok ? 'status' : 'alert'} data-testid="se-msg" className={`text-xs ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>}
        <div className="flex gap-2">
          <button type="submit" data-testid="se-save" disabled={busy}
            className="px-4 py-1.5 text-sm rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40">{t('save')}</button>
        </div>
      </form>

      {physical && (isAdmin
        ? <BmcSection serverId={server.id} />
        : <p className="text-[11px] text-slate-500 border-t border-white/[0.06] pt-3" data-testid="se-bmc-admin-only">{t('se_bmc_admin_only')}</p>)}
    </div>
  )
}

export default ServerEditPanel
