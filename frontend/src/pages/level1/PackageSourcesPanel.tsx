/**
 * Level 1 Paket Repo — keyword / NFS / Portal / Subscription.
 * Veri: Dropt package-repos API (L1 paket operasyonları).
 */
import { FormEvent, useCallback, useEffect, useState, type ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Package } from 'lucide-react'
import {
  createPkgLocalRepo,
  createPkgSubscription,
  deletePkgLocalRepo,
  deletePkgSubscription,
  getPackageReposOverview,
  type OsOption,
  type PkgLocalRepoRow,
  type PkgSubscriptionRow,
  updatePkgLocalRepo,
} from '@dropt/api'
import { ensureDroptSession } from './Level1Shell'

type SourceType = 'nfs' | 'portal_files' | 'subscription'

const inputClass =
  'w-full bg-[var(--bg-deep,#080d16)] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-sm text-[var(--text-primary,#e8edf5)] placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/50 transition-colors'
const labelClass = 'block text-xs font-medium text-slate-400 mb-1.5 tracking-wide'
const panelClass =
  'rounded-xl border border-white/[0.06] bg-cyber-card p-5'
const primaryBtn =
  'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:pointer-events-none shadow-[0_2px_10px_rgba(59,130,246,0.22)] transition-colors'
const ghostBtn =
  'inline-flex items-center justify-center px-3.5 py-2 rounded-lg text-sm font-medium text-slate-300 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white disabled:opacity-50 transition-colors'
const softBtn =
  'inline-flex items-center justify-center px-2.5 py-1 rounded-md text-xs font-medium text-blue-300 border border-blue-500/20 bg-blue-500/10 hover:bg-blue-500/20 transition-colors'
const dangerBtn =
  'inline-flex items-center justify-center px-2.5 py-1 rounded-md text-xs font-medium text-red-300/90 border border-red-500/20 bg-red-500/10 hover:bg-red-500/20 transition-colors'

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

function sourceLabel(st: string | undefined): string {
  if (st === 'portal_files') return 'Portal RPM'
  if (st === 'subscription') return 'Subscription'
  return 'NFS'
}

function sourceBadgeClass(st: string | undefined): string {
  if (st === 'portal_files') return 'border-cyan-500/25 bg-cyan-500/10 text-cyan-300'
  if (st === 'subscription') return 'border-blue-500/25 bg-blue-500/10 text-blue-300'
  return 'border-amber-500/25 bg-amber-500/10 text-amber-300'
}

export default function PackageSourcesPanel() {
  const [ready, setReady] = useState(false)
  const [sessionErr, setSessionErr] = useState<string | null>(null)
  const [token, setToken] = useState<string>('')

  const [osOptions, setOsOptions] = useState<OsOption[]>([])
  const [subs, setSubs] = useState<PkgSubscriptionRow[]>([])
  const [repos, setRepos] = useState<PkgLocalRepoRow[]>([])
  const [portalRoot, setPortalRoot] = useState('/var/lib/dropt/rpms')
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const [subOs, setSubOs] = useState('')
  const [org, setOrg] = useState('')
  const [actKey, setActKey] = useState('')

  const [editingId, setEditingId] = useState<number | null>(null)
  const [kw, setKw] = useState('')
  const [repoOs, setRepoOs] = useState('')
  const [sourceType, setSourceType] = useState<SourceType>('nfs')
  const [nfs, setNfs] = useState('')
  const [mount, setMount] = useState('')
  const [portalPath, setPortalPath] = useState('')
  const [fileGlob, setFileGlob] = useState('*.rpm')
  const [needsFs, setNeedsFs] = useState(false)
  const [postCmd, setPostCmd] = useState('')

  const resetRepoForm = useCallback((fallbackOs = '') => {
    setEditingId(null)
    setKw('')
    setRepoOs(fallbackOs)
    setSourceType('nfs')
    setNfs('')
    setMount('')
    setPortalPath('')
    setFileGlob('*.rpm')
    setNeedsFs(false)
    setPostCmd('')
  }, [])

  const reload = useCallback(async (tok: string) => {
    const o = await getPackageReposOverview(tok)
    setOsOptions(o.os_options)
    setSubs(o.subscriptions)
    setRepos(o.local_repos)
    if ((o as { portal_rpm_root?: string }).portal_rpm_root) {
      setPortalRoot((o as { portal_rpm_root: string }).portal_rpm_root)
    }
    setSubOs((prev) => prev || o.os_options[0]?.value || '')
    setRepoOs((prev) => prev || o.os_options[0]?.value || '')
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const tok = await ensureDroptSession()
        if (cancelled) return
        setToken(tok)
        setReady(true)
        setLoading(true)
        await reload(tok)
      } catch (e) {
        if (!cancelled) setSessionErr(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [reload])

  function startEdit(r: PkgLocalRepoRow) {
    setEditingId(r.id)
    setKw(r.keyword)
    setRepoOs(r.os_value)
    const st = (r.source_type || 'nfs') as SourceType
    setSourceType(st === 'portal_files' || st === 'subscription' ? st : 'nfs')
    setNfs(r.nfs_path || '')
    setMount(r.mount_point || '')
    setPortalPath(r.portal_path || '')
    setFileGlob(r.file_glob || '*.rpm')
    setNeedsFs(Boolean(r.needs_data_mount))
    setPostCmd(r.post_commands || '')
    setMsg(null)
    setError(null)
  }

  async function onAddSub(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setMsg(null)
    try {
      await createPkgSubscription(token, {
        os_value: subOs,
        org: org.trim(),
        activation_key: actKey.trim() || undefined,
        label: subOs,
      })
      setActKey('')
      setMsg('Subscription eklendi (key boşsa operasyonlarda wipe/register atlanır)')
      await reload(token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Hata')
    } finally {
      setBusy(false)
    }
  }

  async function onSaveRepo(e: FormEvent) {
    e.preventDefault()
    if (!kw.trim()) {
      setError('Keyword zorunlu')
      return
    }
    setBusy(true)
    setError(null)
    setMsg(null)
    const body = {
      keyword: kw.trim(),
      label: kw.trim(),
      os_value: repoOs,
      source_type: sourceType,
      nfs_path: sourceType === 'nfs' ? nfs.trim() : '',
      mount_point: sourceType === 'nfs' ? mount.trim() || `/mnt/dropt-repo-${kw.trim()}` : '',
      portal_path: sourceType === 'portal_files' ? portalPath.trim() : '',
      file_glob: sourceType === 'portal_files' ? fileGlob.trim() || '*.rpm' : '*.rpm',
      needs_data_mount: sourceType === 'nfs' || sourceType === 'subscription' ? needsFs : false,
      post_commands: postCmd,
      repo_id: `dropt-${kw.trim()}`,
    }
    try {
      if (editingId != null) {
        await updatePkgLocalRepo(token, editingId, body)
        setMsg(`Keyword reçetesi güncellendi: ${kw} @ ${repoOs}`)
      } else {
        await createPkgLocalRepo(token, body)
        setMsg(`Keyword reçetesi eklendi: ${kw} @ ${repoOs} (${sourceType})`)
      }
      resetRepoForm(repoOs || osOptions[0]?.value || '')
      await reload(token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Hata')
    } finally {
      setBusy(false)
    }
  }

  if (sessionErr) {
    return (
      <div className={`${panelClass} max-w-2xl`}>
        <Flash kind="err">{sessionErr}</Flash>
        <p className="text-sm text-slate-400">
          Paket kaynakları Dropt oturumu gerektirir. Bridge / Level 1 servisini kontrol edin.
        </p>
        <button type="button" className={`${primaryBtn} mt-4`} onClick={() => window.location.reload()}>
          Yeniden dene
        </button>
      </div>
    )
  }

  if (!ready || loading) {
    return (
      <div className="flex items-center justify-center py-20 text-slate-400 text-sm gap-3">
        <span className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
        Paket kaynakları yükleniyor…
      </div>
    )
  }

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-semibold text-white tracking-tight flex items-center gap-2">
            <Package size={20} className="text-blue-400" />
            Paket kaynakları
          </h2>
          <p className="mt-1 text-sm text-slate-400 leading-relaxed">
            Level 1 Operasyon Merkezi paket işlerinin kullandığı keyword reçeteleri (NFS, Portal RPM,
            Subscription). Aynı kayıtlar L1 paket wizard’ında chip olarak görünür. Portal kök:{' '}
            <span className="font-mono text-slate-300">{portalRoot}/…</span>
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <span className="px-2 py-1 rounded-md border border-white/[0.08] bg-white/[0.03] font-mono">
            {repos.length} reçete
          </span>
          <span className="px-2 py-1 rounded-md border border-white/[0.08] bg-white/[0.03] font-mono">
            {subs.length} sub
          </span>
        </div>
      </div>

      {msg && <Flash kind="ok">{msg}</Flash>}
      {error && <Flash kind="err">{error}</Flash>}

      {/* Subscriptions */}
      <div className={panelClass}>
        <h3 className="text-sm font-semibold text-white mb-1">Subscription (OS activation key)</h3>
        <p className="text-xs text-slate-500 mb-4">
          Satellite / subscription-manager için org + activation key. Keyword kaynağı “Subscription”
          seçildiğinde bu kayıtlar kullanılır.
        </p>
        <form onSubmit={onAddSub} className="grid gap-3 sm:grid-cols-4">
          <div>
            <label className={labelClass}>OS</label>
            <select className={inputClass} value={subOs} onChange={(e) => setSubOs(e.target.value)} required>
              <option value="" disabled>
                Seçin
              </option>
              {osOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                  {o.count ? ` (${o.count})` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass}>Org</label>
            <input
              className={`${inputClass} font-mono`}
              value={org}
              onChange={(e) => setOrg(e.target.value)}
              placeholder="org"
            />
          </div>
          <div>
            <label className={labelClass}>Activation key</label>
            <input
              className={`${inputClass} font-mono`}
              type="password"
              value={actKey}
              onChange={(e) => setActKey(e.target.value)}
              placeholder="opsiyonel"
              autoComplete="new-password"
            />
          </div>
          <div className="flex items-end">
            <button type="submit" className={`${primaryBtn} w-full`} disabled={busy || !subOs}>
              Ekle
            </button>
          </div>
        </form>

        {subs.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500 text-center py-6 border border-dashed border-white/[0.08] rounded-lg">
            Henüz subscription yok
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-white/[0.05]">
            {subs.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-white">{s.label || s.os_value}</span>
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border ${
                        s.activation_key_set
                          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
                          : 'border-amber-500/20 bg-amber-500/10 text-amber-300'
                      }`}
                    >
                      {s.activation_key_set ? 'key set' : 'no key'}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs font-mono text-slate-500">
                    {s.os_value} · org={s.org || '—'}
                  </p>
                </div>
                <button
                  type="button"
                  className={dangerBtn}
                  onClick={() =>
                    void deletePkgSubscription(token, s.id)
                      .then(() => reload(token))
                      .catch((e) => setError(e instanceof Error ? e.message : 'Silinemedi'))
                  }
                >
                  Sil
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Keyword recipe form */}
      <div className={panelClass}>
        <div className="flex items-center justify-between gap-3 mb-4">
          <div>
            <h3 className="text-sm font-semibold text-white">
              Keyword reçetesi
              {editingId != null ? (
                <span className="ml-2 text-xs font-mono text-blue-400">#{editingId}</span>
              ) : null}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Package ekranında chip olur · NFS / Portal / Subscription + post komutlar
            </p>
          </div>
          {editingId != null && (
            <button
              type="button"
              className={ghostBtn}
              onClick={() => resetRepoForm(osOptions[0]?.value || '')}
            >
              İptal
            </button>
          )}
        </div>

        <form onSubmit={onSaveRepo} className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Keyword</label>
            <input
              className={`${inputClass} font-mono`}
              placeholder="docker / snowlinux"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
              required
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelClass}>OS</label>
            <select
              className={inputClass}
              value={repoOs}
              onChange={(e) => setRepoOs(e.target.value)}
              required
            >
              <option value="" disabled>
                Seçin
              </option>
              {osOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="sm:col-span-2">
            <label className={labelClass}>Kaynak tipi</label>
            <select
              className={inputClass}
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as SourceType)}
            >
              <option value="nfs">NFS local repo</option>
              <option value="portal_files">Portal dosya (RPM → /tmp + localinstall)</option>
              <option value="subscription">Subscription (Satellite / dnf + post)</option>
            </select>
          </div>

          {sourceType === 'nfs' && (
            <>
              <div className="sm:col-span-2">
                <label className={labelClass}>NFS path</label>
                <input
                  className={`${inputClass} font-mono`}
                  placeholder="host:/export/…"
                  value={nfs}
                  onChange={(e) => setNfs(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className={labelClass}>Mount point</label>
                <input
                  className={`${inputClass} font-mono`}
                  placeholder="/mnt/dropt-repo-xxx"
                  value={mount}
                  onChange={(e) => setMount(e.target.value)}
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                  <input
                    type="checkbox"
                    className="rounded border-slate-600"
                    checked={needsFs}
                    onChange={(e) => setNeedsFs(e.target.checked)}
                  />
                  Data mount (FS) seçimi gerekli
                </label>
              </div>
            </>
          )}

          {sourceType === 'portal_files' && (
            <>
              <div className="sm:col-span-2">
                <label className={labelClass}>Portal path</label>
                <input
                  className={`${inputClass} font-mono`}
                  placeholder={`${portalRoot}/snowlinux/el8`}
                  value={portalPath}
                  onChange={(e) => setPortalPath(e.target.value)}
                  required
                />
              </div>
              <div className="sm:col-span-2">
                <label className={labelClass}>File glob</label>
                <input
                  className={`${inputClass} font-mono`}
                  placeholder="snowlinux*.rpm"
                  value={fileGlob}
                  onChange={(e) => setFileGlob(e.target.value)}
                />
              </div>
            </>
          )}

          {sourceType === 'subscription' && (
            <div className="sm:col-span-2 space-y-3 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
              <p className="text-xs text-slate-400 leading-relaxed">
                Paketler Satellite/dnf üzerinden kurulur (yukarıdaki OS subscription key). Post komutlar
                ve data dizini NFS ile aynı placeholder’ları kullanır (
                <span className="font-mono text-slate-300">{'{{docker_pkgs}}'}</span>,{' '}
                <span className="font-mono text-slate-300">{'{{docker_dir}}'}</span>, …).
              </p>
              <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded border-slate-600"
                  checked={needsFs}
                  onChange={(e) => setNeedsFs(e.target.checked)}
                />
                Data mount (FS) seçimi gerekli
              </label>
            </div>
          )}

          <div className="sm:col-span-2">
            <label className={labelClass}>Kurulum sonrası komutlar (opsiyonel)</label>
            <textarea
              className={`${inputClass} min-h-[8rem] font-mono text-xs leading-relaxed`}
              value={postCmd}
              onChange={(e) => setPostCmd(e.target.value)}
              placeholder="{{data_mount}} {{docker_dir}} {{docker_pkgs}} …"
            />
          </div>

          <div className="sm:col-span-2 flex items-center gap-3 pt-2 border-t border-white/[0.05]">
            <button
              type="submit"
              className={primaryBtn}
              disabled={busy || !repoOs || !kw.trim()}
            >
              {busy ? 'Kaydediliyor…' : editingId != null ? 'Güncelle' : 'Reçete ekle'}
            </button>
          </div>
        </form>
      </div>

      {/* Recipe list */}
      <div className={panelClass}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Kayıtlı reçeteler</h3>
          <span className="text-[11px] text-slate-500 font-mono">{repos.length}</span>
        </div>
        {repos.length === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center border border-dashed border-white/[0.08] rounded-lg">
            Henüz keyword reçetesi yok
          </p>
        ) : (
          <ul className="divide-y divide-white/[0.05]">
            {repos.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-white font-mono">[{r.keyword}]</span>
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border ${sourceBadgeClass(r.source_type)}`}
                    >
                      {sourceLabel(r.source_type)}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">{r.os_value}</span>
                    {r.needs_data_mount && (
                      <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md border border-white/[0.1] text-slate-400">
                        FS
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs font-mono text-slate-500 break-all">
                    {r.source_type === 'portal_files'
                      ? `${r.portal_path}/${r.file_glob || '*.rpm'}`
                      : r.source_type === 'subscription'
                        ? 'Satellite/dnf + post'
                        : r.nfs_path}
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
                      void deletePkgLocalRepo(token, r.id)
                        .then(() => {
                          if (editingId === r.id) resetRepoForm(osOptions[0]?.value || '')
                          return reload(token)
                        })
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
