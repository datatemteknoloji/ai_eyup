import { FormEvent, useCallback, useEffect, useState, type ReactNode } from 'react'
import { KeyRound, Mail, Shield, Package, CheckCircle2, AlertCircle } from 'lucide-react'
import { Level1Shell } from './Level1Shell'
import PackageSourcesPanel from './PackageSourcesPanel'
import { getToken } from '@dropt/session'
import {
  getAdminSettings,
  updateAdminSettings,
  type AdminSettings,
  CentrifyCredentialRow,
  createCentrifyCredential,
  deleteCentrifyCredential,
  listCentrifyCredentials,
  updateCentrifyCredential,
} from '@dropt/api'

type Tab = 'automation' | 'mail' | 'repos' | 'centrify'

const inputClass =
  'w-full bg-[var(--bg-deep,#080d16)] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-sm text-[var(--text-primary,#e8edf5)] placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/50 transition-colors'
const labelClass = 'block text-xs font-medium text-slate-400 mb-1.5 tracking-wide'
const panelClass =
  'rounded-xl border border-white/[0.06] bg-[color-mix(in_srgb,var(--bg-deep,#080d16)_55%,transparent)] p-5'
const primaryBtn =
  'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:pointer-events-none shadow-[0_2px_10px_rgba(59,130,246,0.22)] transition-colors'
const ghostBtn =
  'inline-flex items-center justify-center px-3.5 py-2 rounded-lg text-sm font-medium text-slate-300 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white disabled:opacity-50 transition-colors'
const dangerBtn =
  'inline-flex items-center justify-center px-2.5 py-1 rounded-md text-xs font-medium text-red-300/90 border border-red-500/20 bg-red-500/10 hover:bg-red-500/20 transition-colors'
const softBtn =
  'inline-flex items-center justify-center px-2.5 py-1 rounded-md text-xs font-medium text-blue-300 border border-blue-500/20 bg-blue-500/10 hover:bg-blue-500/20 transition-colors'

function Flash({ kind, children }: { kind: 'ok' | 'err'; children: ReactNode }) {
  const ok = kind === 'ok'
  return (
    <div
      className={`mb-4 flex items-start gap-2 rounded-lg border px-3.5 py-2.5 text-sm ${
        ok
          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
          : 'border-red-500/25 bg-red-500/10 text-red-300'
      }`}
    >
      {ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
      <span className="whitespace-pre-wrap leading-snug">{children}</span>
    </div>
  )
}

function SectionHead({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-5">
      <h2 className="text-xl font-semibold tracking-tight" style={{ color: 'var(--text-primary)' }}>{title}</h2>
      <p className="mt-1 text-sm leading-relaxed max-w-2xl" style={{ color: 'var(--text-secondary)' }}>{subtitle}</p>
    </div>
  )
}

export default function Level1Settings() {
  const [tab, setTab] = useState<Tab>('automation')
  const [s, setS] = useState<AdminSettings | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [username, setUsername] = useState('root')
  const [kind, setKind] = useState<'root' | 'local' | 'ad'>('root')
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const token = getToken()!
    const data = await getAdminSettings(token)
    setS(data)
    setUsername(data.automation_username || 'root')
    const k = data.automation_user_kind
    setKind(k === 'local' || k === 'ad' ? k : 'root')
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [load])

  const saveAutomation = async () => {
    setMsg(null)
    setErr(null)
    setSaving(true)
    try {
      const token = getToken()!
      const body: Record<string, unknown> = {
        automation_username: username.trim() === 'root' ? 'root' : username,
        automation_user_kind: username.trim() === 'root' ? 'root' : kind,
      }
      if (password.trim()) body.automation_password = password.trim()
      const updated = await updateAdminSettings(token, body as any)
      setS(updated)
      setPassword('')
      setMsg('Otomasyon ayarları kaydedildi')
      setTimeout(() => setMsg(null), 3000)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const tabs: { id: Tab; name: string; icon: ReactNode; hint: string }[] = [
    { id: 'automation', name: 'Otomasyon', icon: <KeyRound size={15} strokeWidth={2} />, hint: 'SSH operasyon kullanıcısı' },
    { id: 'mail', name: 'Mail', icon: <Mail size={15} strokeWidth={2} />, hint: 'SMTP bildirimleri' },
    { id: 'repos', name: 'Paket Repo', icon: <Package size={15} strokeWidth={2} />, hint: 'Keyword / NFS / Subscription' },
    { id: 'centrify', name: 'Centrify', icon: <Shield size={15} strokeWidth={2} />, hint: 'AD leave / join' },
  ]

  return (
    <Level1Shell>
      <div className="flex gap-5 h-[calc(100vh-140px)] min-h-0">
        {/* Sol menü — ana Ayarlar ile aynı dil */}
        <aside className="w-64 shrink-0 rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden flex flex-col">
          <div className="px-4 py-4 border-b border-white/[0.06]">
            <h2 className="text-base font-semibold tracking-tight" style={{ color: 'var(--text-primary)' }}>Ayarlar</h2>
            <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>İşletim Level 1</p>
          </div>
          <nav className="p-2.5 flex-1 space-y-0.5">
            {tabs.map((t) => {
              const active = tab === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    setTab(t.id)
                    setMsg(null)
                    setErr(null)
                  }}
                  className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                    active
                      ? 'bg-blue-600/15 text-blue-300 border border-blue-500/30'
                      : 'text-slate-400 hover:text-white hover:bg-white/[0.04] border border-transparent'
                  }`}
                >
                  <span className={`mt-0.5 ${active ? 'text-blue-400' : 'text-slate-500'}`}>{t.icon}</span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium leading-tight">{t.name}</span>
                    <span className={`block text-[11px] mt-0.5 leading-snug ${active ? 'text-blue-400/70' : 'text-slate-600'}`}>
                      {t.hint}
                    </span>
                  </span>
                </button>
              )
            })}
          </nav>
          <div className="px-4 py-3 border-t border-white/[0.06]">
            <p className="text-[10px] leading-relaxed text-slate-600">
              Paket Repo yalnızca Level 1 operasyonları içindir (admin).
            </p>
          </div>
        </aside>

        {/* İçerik */}
        <section className="flex-1 min-w-0 rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto overflow-x-hidden p-6">
            {loading && (
              <div className="flex items-center gap-3 text-slate-400 text-sm py-16 justify-center">
                <span className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
                Ayarlar yükleniyor…
              </div>
            )}

            {!loading && msg && <Flash kind="ok">{msg}</Flash>}
            {!loading && err && <Flash kind="err">{err}</Flash>}

            {!loading && tab === 'automation' && (
              <div className="max-w-2xl">
                <SectionHead
                  title="Otomasyon SSH"
                  subtitle="Operasyonel SSH kullanıcısı (ainew global credential’dan bağımsız). root: doğrudan · local: sudo -n · ad: dzdo -n"
                />
                <div className={panelClass}>
                  <div className="flex flex-wrap items-center gap-2 mb-5">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Durum</span>
                    <span
                      className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-md border ${
                        s?.automation_password_set
                          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                          : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                      }`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          s?.automation_password_set ? 'bg-emerald-400' : 'bg-amber-400'
                        }`}
                      />
                      {s?.automation_password_set ? 'Şifre kayıtlı' : 'Şifre yok'}
                    </span>
                    <span className="inline-flex items-center text-[11px] font-mono px-2 py-0.5 rounded-md border border-white/[0.08] bg-white/[0.03] text-slate-300">
                      {username.trim() === 'root' ? 'root' : `${kind}:${username || '—'}`}
                    </span>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <label className={labelClass}>Kullanıcı tipi</label>
                      <select
                        className={inputClass}
                        value={username.trim() === 'root' ? 'root' : kind}
                        onChange={(e) => {
                          const v = e.target.value as 'root' | 'local' | 'ad'
                          if (v === 'root') {
                            setKind('root')
                            setUsername('root')
                          } else {
                            setKind(v)
                            if (username.trim() === 'root') setUsername('')
                          }
                        }}
                      >
                        <option value="root">root (doğrudan)</option>
                        <option value="local">local (sudo)</option>
                        <option value="ad">ad (dzdo)</option>
                      </select>
                    </div>
                    {username.trim() !== 'root' && (
                      <div>
                        <label className={labelClass}>Kullanıcı adı</label>
                        <input
                          className={`${inputClass} font-mono`}
                          value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          placeholder="örn. opsadmin"
                          autoComplete="off"
                        />
                      </div>
                    )}
                    <div>
                      <label className={labelClass}>
                        Şifre
                        {s?.automation_password_set ? (
                          <span className="font-normal text-slate-500"> — kayıtlı; değiştirmek için yazın</span>
                        ) : null}
                      </label>
                      <input
                        type="password"
                        className={`${inputClass} font-mono`}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                        autoComplete="new-password"
                      />
                    </div>
                    <div className="flex items-center gap-3 pt-2 border-t border-white/[0.05]">
                      <button type="button" onClick={saveAutomation} disabled={saving} className={primaryBtn}>
                        {saving ? 'Kaydediliyor…' : 'Kaydet'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {!loading && tab === 'mail' && s && (
              <MailPanel settings={s} onSaved={setS} />
            )}

            {!loading && tab === 'repos' && (
              <div className="max-w-4xl">
                <PackageSourcesPanel />
              </div>
            )}

            {!loading && tab === 'centrify' && <CentrifyPanel />}
          </div>
        </section>
      </div>
    </Level1Shell>
  )
}

function MailPanel({ settings, onSaved }: { settings: AdminSettings; onSaved: (s: AdminSettings) => void }) {
  const [host, setHost] = useState(settings.smtp_host || '')
  const [testMail, setTestMail] = useState(settings.smtp_test_mail || '')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setHost(settings.smtp_host || '')
    setTestMail(settings.smtp_test_mail || '')
  }, [settings.smtp_host, settings.smtp_test_mail])

  const save = async () => {
    setErr(null)
    setSaving(true)
    try {
      const token = getToken()!
      const updated = await updateAdminSettings(token, {
        smtp_host: host,
        smtp_test_mail: testMail,
      } as any)
      onSaved(updated)
      setMsg('Mail ayarları kaydedildi')
      setTimeout(() => setMsg(null), 3000)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <SectionHead
        title="Mail"
        subtitle="SMTP host ve test adresi — Level 1 operasyon bildirimleri için kullanılır."
      />
      {msg && <Flash kind="ok">{msg}</Flash>}
      {err && <Flash kind="err">{err}</Flash>}
      <div className={panelClass}>
        <div className="space-y-4">
          <div>
            <label className={labelClass}>SMTP host</label>
            <input
              className={`${inputClass} font-mono`}
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="smtp.ornek.com"
            />
          </div>
          <div>
            <label className={labelClass}>Test mail</label>
            <input
              className={`${inputClass} font-mono`}
              value={testMail}
              onChange={(e) => setTestMail(e.target.value)}
              placeholder="test@ornek.com"
            />
          </div>
          <div className="flex items-center gap-3 pt-2 border-t border-white/[0.05]">
            <button type="button" onClick={save} disabled={saving} className={primaryBtn}>
              {saving ? 'Kaydediliyor…' : 'Kaydet'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function CentrifyPanel() {
  const token = getToken()!
  const [rows, setRows] = useState<CentrifyCredentialRow[]>([])
  const [username, setUsername] = useState('')
  const [domain, setDomain] = useState('')
  const [password, setPassword] = useState('')
  const [label, setLabel] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const data = await listCentrifyCredentials(token)
    setRows(data.credentials || [])
  }, [token])

  useEffect(() => {
    setLoading(true)
    reload()
      .catch((e) => setError(e instanceof Error ? e.message : 'Yüklenemedi'))
      .finally(() => setLoading(false))
  }, [reload])

  function resetForm() {
    setUsername('')
    setDomain('')
    setPassword('')
    setLabel('')
    setEditingId(null)
  }

  function startEdit(r: CentrifyCredentialRow) {
    setEditingId(r.id)
    setUsername(r.username)
    setDomain(r.domain)
    setLabel(r.label || '')
    setPassword('')
    setMsg(null)
    setError(null)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setMsg(null)
    try {
      const body = {
        username: username.trim(),
        domain: domain.trim().toLowerCase(),
        password: password.trim() || undefined,
        label: label.trim() || domain.trim().toLowerCase(),
        enabled: true,
      }
      if (editingId != null) {
        await updateCentrifyCredential(token, editingId, body)
        setMsg(`Güncellendi: ${body.domain}`)
      } else {
        if (!body.password) throw new Error('Yeni kayıt için şifre zorunlu')
        await createCentrifyCredential(token, { ...body, password: body.password })
        setMsg(`Eklendi: ${body.domain}`)
      }
      resetForm()
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Hata')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl">
      <SectionHead
        title="Centrify"
        subtitle="Hostname değişikliğinde sunucudaki Current DC domain’i ile eşleşen hesap kullanılır. Leave: adleave -f · Join: adjoin."
      />
      {msg && <Flash kind="ok">{msg}</Flash>}
      {error && <Flash kind="err">{error}</Flash>}

      <div className={`${panelClass} mb-5`}>
        <div className="flex items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-semibold text-white">
            {editingId != null ? 'Kaydı düzenle' : 'Yeni kimlik bilgisi'}
          </h3>
          {editingId != null && (
            <button type="button" className={ghostBtn} onClick={resetForm}>
              İptal
            </button>
          )}
        </div>
        <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Kullanıcı</label>
            <input
              className={`${inputClass} font-mono`}
              placeholder="service_centrify"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelClass}>Domain</label>
            <input
              className={`${inputClass} font-mono`}
              placeholder="kfs.local"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              required
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelClass}>
              Şifre
              {editingId != null ? (
                <span className="font-normal text-slate-500"> — boş bırakılırsa korunur</span>
              ) : null}
            </label>
            <input
              className={`${inputClass} font-mono`}
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={editingId == null}
              autoComplete="new-password"
            />
          </div>
          <div>
            <label className={labelClass}>Etiket (opsiyonel)</label>
            <input
              className={inputClass}
              placeholder="Üretim AD"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div className="sm:col-span-2 flex items-center gap-3 pt-2 border-t border-white/[0.05]">
            <button type="submit" disabled={busy} className={primaryBtn}>
              {busy ? 'Kaydediliyor…' : editingId != null ? 'Güncelle' : 'Ekle'}
            </button>
          </div>
        </form>
      </div>

      <div className={panelClass}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Kayıtlı hesaplar</h3>
          <span className="text-[11px] text-slate-500 font-mono">{rows.length}</span>
        </div>

        {loading ? (
          <p className="text-sm text-slate-500 py-6 text-center">Yükleniyor…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center border border-dashed border-white/[0.08] rounded-lg">
            Henüz Centrify kaydı yok
          </p>
        ) : (
          <ul className="divide-y divide-white/[0.05]">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-white truncate">
                      {r.label || r.domain}
                    </span>
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border ${
                        r.password_set
                          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
                          : 'border-amber-500/20 bg-amber-500/10 text-amber-300'
                      }`}
                    >
                      {r.password_set ? 'pass' : 'no pass'}
                    </span>
                    {!r.enabled && (
                      <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border border-slate-500/30 text-slate-400">
                        disabled
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs font-mono text-slate-500 truncate">
                    {r.username}@{r.domain}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button type="button" className={softBtn} onClick={() => startEdit(r)}>
                    Düzenle
                  </button>
                  <button
                    type="button"
                    className={dangerBtn}
                    onClick={() =>
                      void deleteCentrifyCredential(token, r.id)
                        .then(reload)
                        .catch((e) => setError(e instanceof Error ? e.message : 'Silinemedi'))
                    }
                  >
                    Sil
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
