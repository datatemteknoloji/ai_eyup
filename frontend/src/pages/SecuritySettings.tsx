/**
 * Uygulama geneli güvenlik: Kimlik/AD, Oturumlar, MFA, TLS, Politika
 */
import React, { useCallback, useEffect, useState } from 'react'
import { API_BASE_URL } from '../config/api'

type SubTab = 'identity' | 'sessions' | 'mfa' | 'tls' | 'policy'

async function api(method: string, path: string, body?: unknown) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail || e))
  }
  return r.json()
}

const subTabs: { id: SubTab; label: string }[] = [
  { id: 'identity', label: 'Kimlik / AD' },
  { id: 'sessions', label: 'Oturumlar' },
  { id: 'mfa', label: 'MFA' },
  { id: 'tls', label: 'TLS / HTTPS' },
  { id: 'policy', label: 'Politika' },
]

export default function SecuritySettings() {
  const [sub, setSub] = useState<SubTab>('identity')
  return (
    <div className="max-w-4xl">
      <h2 className="text-xl font-semibold text-white mb-1">Güvenlik</h2>
      <p className="text-sm text-slate-400 mb-6">
        Kimlik doğrulama, oturum, MFA, TLS ve parola politikası tüm modüller için geçerlidir.
      </p>
      <div className="flex flex-wrap gap-2 mb-6 border-b border-white/[0.06] pb-3">
        {subTabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setSub(t.id)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              sub === t.id
                ? 'bg-blue-600/30 text-blue-200 border border-blue-500/40'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {sub === 'identity' && <IdentityPanel />}
      {sub === 'sessions' && <SessionsPanel />}
      {sub === 'mfa' && <MfaPanel />}
      {sub === 'tls' && <TlsPanel />}
      {sub === 'policy' && <PolicyPanel />}
    </div>
  )
}

function Banner({ error, info }: { error?: string | null; info?: string | null }) {
  return (
    <>
      {error && (
        <div className="mb-4 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 whitespace-pre-wrap">
          {error}
        </div>
      )}
      {info && (
        <div className="mb-4 text-sm text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-2">
          {info}
        </div>
      )}
    </>
  )
}

function IdentityPanel() {
  const [form, setForm] = useState<Record<string, any> | null>(null)
  const [bindPw, setBindPw] = useState('')
  const [testUser, setTestUser] = useState({ username: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const load = useCallback(async () => {
    const data = await api('GET', '/identity')
    setForm(data)
  }, [])

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [load])

  if (!form) return <div className="text-slate-400 text-sm">Yükleniyor…</div>

  const set = (k: string, v: unknown) => setForm((f) => ({ ...f!, [k]: v }))

  const save = async () => {
    setBusy(true); setError(null); setInfo(null)
    try {
      const body: Record<string, unknown> = {
        ad_enabled: form.ad_enabled,
        ad_host: form.ad_host,
        ad_port: Number(form.ad_port) || 636,
        ad_use_ssl: form.ad_use_ssl,
        ad_tls_verify: form.ad_tls_verify,
        ad_domain: form.ad_domain,
        ad_base_dn: form.ad_base_dn,
        ad_bind_dn: form.ad_bind_dn,
        ad_user_filter: form.ad_user_filter,
        ad_admin_group: form.ad_admin_group,
        ad_operator_group: form.ad_operator_group,
        ad_viewer_group: form.ad_viewer_group,
        ad_jit_enabled: form.ad_jit_enabled,
        sso_enabled: form.sso_enabled,
        sso_mode: form.sso_mode || 'oidc',
        sso_issuer: form.sso_issuer,
        sso_client_id: form.sso_client_id,
        sso_redirect_uri: form.sso_redirect_uri,
        sso_scopes: form.sso_scopes,
        sso_admin_group: form.sso_admin_group,
        sso_operator_group: form.sso_operator_group,
        sso_viewer_group: form.sso_viewer_group,
        sso_frontend_redirect: form.sso_frontend_redirect,
      }
      if (form.ad_ca_cert_pem) body.ad_ca_cert_pem = form.ad_ca_cert_pem
      if (bindPw) body.ad_bind_password = bindPw
      const saved = await api('PUT', '/identity', body)
      setForm(saved)
      setBindPw('')
      setInfo('Kimlik ayarları kaydedildi')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const testAd = async () => {
    setBusy(true); setError(null); setInfo(null)
    try {
      const r = await api('POST', '/identity/test-ad', {
        username: testUser.username || undefined,
        password: testUser.password || undefined,
      })
      setInfo(r.ok ? r.message : `Başarısız: ${r.message}`)
      if (!r.ok) setError(r.message)
      else setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const syncAd = async () => {
    setBusy(true); setError(null); setInfo(null)
    try {
      const r = await api('POST', '/identity/sync-ad')
      setInfo(
        `Sync tamam: tarandı=${r.scanned}, getirilen=${r.matched}, yeni=${r.created}, güncellenen=${r.updated}, local atlandı=${r.skipped_local}, pasif=${r.deactivated}`,
      )
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <Banner error={error} info={info} />
      <section className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-white font-medium">Active Directory</h3>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={!!form.ad_enabled} onChange={(e) => set('ad_enabled', e.target.checked)} />
            Etkin
          </label>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Host" value={form.ad_host} onChange={(v) => set('ad_host', v)} />
          <Field label="Port" value={String(form.ad_port ?? 636)} onChange={(v) => set('ad_port', v)} />
          <Field label="Domain" value={form.ad_domain} onChange={(v) => set('ad_domain', v)} />
          <Field label="Base DN" value={form.ad_base_dn} onChange={(v) => set('ad_base_dn', v)} />
          <Field label="Bind DN" value={form.ad_bind_dn} onChange={(v) => set('ad_bind_dn', v)} />
          <Field
            label={form.ad_bind_password_set ? 'Bind şifre (kayıtlı — değiştirmek için yazın)' : 'Bind şifre'}
            value={bindPw}
            onChange={setBindPw}
            type="password"
          />
          <Field label="Admin grubu (opsiyonel)" value={form.ad_admin_group} onChange={(v) => set('ad_admin_group', v)} />
          <Field label="Operator grubu (opsiyonel)" value={form.ad_operator_group} onChange={(v) => set('ad_operator_group', v)} />
          <Field label="Viewer grubu (opsiyonel)" value={form.ad_viewer_group} onChange={(v) => set('ad_viewer_group', v)} />
          <Field label="Kullanıcı filtresi" value={form.ad_user_filter} onChange={(v) => set('ad_user_filter', v)} />
        </div>
        <p className="text-xs text-slate-500">
          AD Sync, Base DN altındaki kullanıcıları Kullanıcı Yönetimi’ne getirir. Rol ve modül yetkisi
          orada verilir. Grup alanları zorunlu değildir; doluysa yalnızca yeni kullanıcılara varsayılan rol önerir.
        </p>
        <div className="flex flex-wrap gap-4 text-sm text-slate-300">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!form.ad_use_ssl} onChange={(e) => set('ad_use_ssl', e.target.checked)} />
            LDAPS / SSL
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!form.ad_tls_verify} onChange={(e) => set('ad_tls_verify', e.target.checked)} />
            TLS doğrula
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!form.ad_jit_enabled} onChange={(e) => set('ad_jit_enabled', e.target.checked)} />
            JIT (ilk login’de oluştur)
          </label>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">CA sertifika PEM (opsiyonel)</label>
          <textarea
            value={form.ad_ca_cert_pem || ''}
            onChange={(e) => set('ad_ca_cert_pem', e.target.value)}
            rows={3}
            className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-xs font-mono"
            placeholder="-----BEGIN CERTIFICATE-----"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={save} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50">
            Kaydet
          </button>
          <button type="button" disabled={busy} onClick={syncAd} className="px-4 py-2 rounded-lg bg-emerald-700 text-white text-sm disabled:opacity-50">
            AD Sync
          </button>
        </div>
        <div className="border-t border-white/[0.06] pt-4 space-y-2">
          <p className="text-xs text-slate-400">Bağlantı testi (kullanıcı boşsa sadece bind)</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Test kullanıcı" value={testUser.username} onChange={(v) => setTestUser((t) => ({ ...t, username: v }))} />
            <Field label="Test parola" value={testUser.password} onChange={(v) => setTestUser((t) => ({ ...t, password: v }))} type="password" />
          </div>
          <button type="button" disabled={busy} onClick={testAd} className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-200 text-sm">
            Test et
          </button>
        </div>
      </section>

      <section className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-white font-medium">SSO / OIDC</h3>
            <p className="text-xs text-slate-500 mt-1">Yapılandırma saklanır; OIDC login akışı sonraki adımda etkinleştirilir.</p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={!!form.sso_enabled} onChange={(e) => set('sso_enabled', e.target.checked)} />
            Etkin (yapılandırma)
          </label>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Issuer" value={form.sso_issuer} onChange={(v) => set('sso_issuer', v)} />
          <Field label="Client ID" value={form.sso_client_id} onChange={(v) => set('sso_client_id', v)} />
          <Field label="Redirect URI" value={form.sso_redirect_uri} onChange={(v) => set('sso_redirect_uri', v)} />
          <Field label="Scopes" value={form.sso_scopes} onChange={(v) => set('sso_scopes', v)} />
        </div>
        <button type="button" disabled={busy} onClick={save} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50">
          Kaydet
        </button>
      </section>
    </div>
  )
}

function Field({
  label, value, onChange, type = 'text',
}: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <input
        type={type}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"
      />
    </div>
  )
}

function SessionsPanel() {
  const [rows, setRows] = useState<any[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const load = useCallback(async () => {
    const data = await api('GET', '/security/sessions?active_only=true')
    setRows(data.sessions || [])
  }, [])

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [load])

  const revoke = async (id: number, username: string) => {
    if (!window.confirm(`${username} oturumu iptal edilsin mi?`)) return
    setError(null)
    try {
      await api('DELETE', `/security/sessions/${id}`)
      setInfo('Oturum iptal edildi')
      await load()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const revokeOthers = async () => {
    if (!window.confirm('Diğer oturumlarınız iptal edilsin mi?')) return
    try {
      const r = await api('POST', '/security/sessions/revoke-others')
      setInfo(`${r.revoked} oturum iptal edildi`)
      await load()
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div>
      <Banner error={error} info={info} />
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-white font-medium">Aktif oturumlar</h3>
        <div className="flex gap-2">
          <button type="button" onClick={() => load()} className="text-sm text-slate-300 px-3 py-1 border border-slate-600 rounded-lg">Yenile</button>
          <button type="button" onClick={revokeOthers} className="text-sm text-amber-200 px-3 py-1 border border-amber-500/40 rounded-lg">Diğerlerimi iptal et</button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-[10px] border border-white/[0.06]">
        <table className="w-full text-sm">
          <thead className="bg-cyber-deep/80 text-slate-400 text-left">
            <tr>
              <th className="px-3 py-2">Kullanıcı</th>
              <th className="px-3 py-2">Kaynak</th>
              <th className="px-3 py-2">IP</th>
              <th className="px-3 py-2">Son görülme</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-white/[0.04] text-slate-200">
                <td className="px-3 py-2">{r.username}</td>
                <td className="px-3 py-2">{r.auth_source}</td>
                <td className="px-3 py-2">{r.client_ip || '—'}</td>
                <td className="px-3 py-2">{r.last_seen_at ? new Date(r.last_seen_at).toLocaleString() : '—'}</td>
                <td className="px-3 py-2 text-right">
                  <button type="button" onClick={() => revoke(r.id, r.username)} className="text-red-300 text-xs hover:underline">İptal</button>
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500">Aktif oturum yok</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MfaPanel() {
  const [policy, setPolicy] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  const load = useCallback(async () => {
    const [p, u] = await Promise.all([
      api('GET', '/security/policy'),
      api('GET', '/security/mfa/users'),
    ])
    setPolicy(p)
    setUsers(u.users || [])
  }, [])

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [load])

  const toggle = async (enabled: boolean) => {
    setError(null)
    try {
      const p = await api('PATCH', '/security/policy', { mfa_enabled: enabled })
      setPolicy(p)
      setInfo(enabled ? 'MFA etkinleştirildi' : 'MFA kapatıldı')
    } catch (e: any) {
      setError(e.message)
    }
  }

  const reset = async (userId: number, username: string) => {
    if (!window.confirm(`${username} MFA sıfırlansın mı?`)) return
    try {
      await api('POST', `/security/mfa/users/${userId}/reset`)
      setInfo(`${username} MFA sıfırlandı`)
      await load()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const filtered = users.filter((u) => {
    const q = filter.trim().toLowerCase()
    if (!q) return true
    return u.username.toLowerCase().includes(q) || (u.auth_source || '').includes(q)
  })

  return (
    <div className="space-y-4">
      <Banner error={error} info={info} />
      <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 flex items-center justify-between">
        <div>
          <h3 className="text-white font-medium">TOTP MFA</h3>
          <p className="text-xs text-slate-400 mt-1">Açıkken tüm kullanıcılar girişte MFA doğrular / kaydeder.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={!!policy?.mfa_enabled}
            onChange={(e) => toggle(e.target.checked)}
          />
          Etkin
        </label>
      </div>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Kullanıcı ara…"
        className="w-full max-w-xs bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"
      />
      <div className="overflow-x-auto rounded-[10px] border border-white/[0.06]">
        <table className="w-full text-sm">
          <thead className="bg-cyber-deep/80 text-slate-400 text-left">
            <tr>
              <th className="px-3 py-2">Kullanıcı</th>
              <th className="px-3 py-2">Kaynak</th>
              <th className="px-3 py-2">Durum</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.user_id} className="border-t border-white/[0.04] text-slate-200">
                <td className="px-3 py-2">{u.username}</td>
                <td className="px-3 py-2">{u.auth_source}</td>
                <td className="px-3 py-2">{u.status}</td>
                <td className="px-3 py-2 text-right">
                  {u.status !== 'disabled' && (
                    <button type="button" onClick={() => reset(u.user_id, u.username)} className="text-amber-300 text-xs hover:underline">
                      Sıfırla
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TlsPanel() {
  const [st, setSt] = useState<any>(null)
  const [cert, setCert] = useState('')
  const [key, setKey] = useState('')
  const [chain, setChain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setSt(await api('GET', '/security/tls'))
  }, [])

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [load])

  const upload = async () => {
    setBusy(true); setError(null); setInfo(null)
    try {
      const r = await api('POST', '/security/tls/upload', { cert_pem: cert, key_pem: key, chain_pem: chain })
      setSt(r.status)
      setInfo(r.reload?.ok ? 'Sertifika yüklendi, nginx reload OK' : `Sertifika yazıldı. Reload: ${r.reload?.error || r.reload?.hint || 'manuel restart gerekebilir'}`)
      setCert(''); setKey(''); setChain('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const regen = async () => {
    if (!window.confirm('Yeni self-signed sertifika üretilsin mi? Tarayıcı uyarısı yenilenebilir.')) return
    setBusy(true); setError(null); setInfo(null)
    try {
      const r = await api('POST', '/security/tls/self-signed', {})
      setSt(r.status)
      setInfo(r.reload?.ok ? 'Self-signed üretildi, nginx reload OK' : 'Self-signed üretildi — frontend restart gerekebilir')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Banner error={error} info={info} />
      <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 space-y-2 text-sm text-slate-300">
        <h3 className="text-white font-medium mb-2">Mevcut sertifika</h3>
        <p>Dizin: <span className="text-slate-400 font-mono text-xs">{st?.certs_dir || '—'}</span></p>
        <p>Kaynak: {st?.source || '—'}</p>
        <p>Subject: {st?.subject || '—'}</p>
        <p>Bitiş: {st?.not_after || '—'}</p>
        <p className="break-all">SHA256: {st?.fingerprint_sha256 || '—'}</p>
        <p>Yazılabilir: {st?.writable ? 'evet' : 'hayır'}</p>
        <button type="button" disabled={busy} onClick={regen} className="mt-2 px-3 py-1.5 rounded-lg border border-slate-600 text-sm">
          Self-signed yenile
        </button>
      </div>
      <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 space-y-3">
        <h3 className="text-white font-medium">Kurumsal sertifika yükle</h3>
        <textarea value={cert} onChange={(e) => setCert(e.target.value)} rows={4} placeholder="Certificate PEM" className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-xs font-mono text-white" />
        <textarea value={key} onChange={(e) => setKey(e.target.value)} rows={4} placeholder="Private key PEM" className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-xs font-mono text-white" />
        <textarea value={chain} onChange={(e) => setChain(e.target.value)} rows={3} placeholder="Chain PEM (opsiyonel)" className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-xs font-mono text-white" />
        <button type="button" disabled={busy || !cert || !key} onClick={upload} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50">
          Yükle ve uygula
        </button>
      </div>
    </div>
  )
}

function PolicyPanel() {
  const [p, setP] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api('GET', '/security/policy').then(setP).catch((e) => setError(e.message))
  }, [])

  if (!p) return <div className="text-slate-400 text-sm">Yükleniyor…</div>

  const save = async () => {
    setBusy(true); setError(null); setInfo(null)
    try {
      const saved = await api('PATCH', '/security/policy', {
        session_idle_minutes: Number(p.session_idle_minutes),
        session_absolute_minutes: Number(p.session_absolute_minutes),
        session_max_concurrent: Number(p.session_max_concurrent),
        lockout_enabled: !!p.lockout_enabled,
        lockout_max_attempts: Number(p.lockout_max_attempts),
        lockout_window_minutes: Number(p.lockout_window_minutes),
        lockout_duration_minutes: Number(p.lockout_duration_minutes),
        password_min_length: Number(p.password_min_length),
      })
      setP(saved)
      setInfo('Politika kaydedildi')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const num = (key: string, label: string) => (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <input
        type="number"
        value={p[key]}
        onChange={(e) => setP({ ...p, [key]: e.target.value })}
        className="w-full bg-cyber-deep border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"
      />
    </div>
  )

  return (
    <div className="space-y-4">
      <Banner error={error} info={info} />
      <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5 grid grid-cols-1 md:grid-cols-2 gap-3">
        {num('session_idle_minutes', 'Idle timeout (dk)')}
        {num('session_absolute_minutes', 'Mutlak oturum süresi (dk)')}
        {num('session_max_concurrent', 'Max eşzamanlı oturum')}
        {num('password_min_length', 'Min parola uzunluğu (local)')}
        {num('lockout_max_attempts', 'Kilit max deneme')}
        {num('lockout_window_minutes', 'Kilit penceresi (dk)')}
        {num('lockout_duration_minutes', 'Kilit süresi (dk)')}
        <label className="flex items-center gap-2 text-sm text-slate-300 md:col-span-2 mt-2">
          <input type="checkbox" checked={!!p.lockout_enabled} onChange={(e) => setP({ ...p, lockout_enabled: e.target.checked })} />
          Hesap kilidi etkin
        </label>
      </div>
      <button type="button" disabled={busy} onClick={save} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50">
        Kaydet
      </button>
    </div>
  )
}
