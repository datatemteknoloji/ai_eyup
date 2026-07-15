import React, { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface PlatformCapability {
  enabled: boolean
  feature_flag: boolean
  docker_sock_ok: boolean
  packaged_install: boolean
  install_dir: string
  data_dir: string
  updates_dir: string
  current_version: string
  max_upload_bytes: number
  reasons: string[]
  has_backup: boolean
  job?: {
    state?: string
    action?: string
    old_version?: string
    new_version?: string
    message?: string
    log_tail?: string
    updated_at?: string
  }
}

interface PlatformPackage {
  path: string
  name: string
  version: string
  kind: string
  has_images?: boolean
  size_bytes?: number
  newer_than_current?: boolean
}

interface PreparedInfo {
  ok: boolean
  current_version: string
  target_version: string
  prepared_path: string
  has_images: boolean
  newer_than_current: boolean
}

function fmtBytes(n?: number) {
  if (!n && n !== 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

async function readError(res: Response) {
  try {
    const j = await res.json()
    return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || j)
  } catch {
    return res.statusText || 'İstek başarısız'
  }
}

const UpgradeOverlay: React.FC<{
  expectedVersion: string
  onDone: () => void
  onFail: (msg: string) => void
}> = ({ expectedVersion, onDone, onFail }) => {
  const [msg, setMsg] = useState('Güncelleme sürüyor — servisler yeniden başlatılıyor…')
  const [elapsed, setElapsed] = useState(0)
  const started = useRef(Date.now())

  useEffect(() => {
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - started.current) / 1000)), 1000)
    let cancelled = false

    const poll = async () => {
      while (!cancelled) {
        try {
          const vr = await fetch(`${API_BASE_URL}/public/version`, { cache: 'no-store' })
          if (vr.ok) {
            const data = await vr.json()
            const v = String(data.version || '').replace(/^[vV]/, '')
            const expect = expectedVersion.replace(/^[vV]/, '')
            if (v && (v === expect || v.startsWith(expect))) {
              setMsg(`Tamamlandı: v${v}`)
              setTimeout(() => onDone(), 800)
              return
            }
            setMsg(`Bekleniyor… şu an v${v || '?'} (hedef v${expect})`)
          } else {
            setMsg('Backend yeniden başlıyor…')
          }
        } catch {
          setMsg('Bağlantı kesildi — güncelleme devam ediyor olabilir…')
        }
        await new Promise(r => setTimeout(r, 3000))
        if (Date.now() - started.current > 15 * 60 * 1000) {
          onFail('Zaman aşımı: 15 dk içinde yeni sürüm görünmedi. Sunucuda logları kontrol edin.')
          return
        }
      }
    }
    poll()
    return () => { cancelled = true; clearInterval(tick) }
  }, [expectedVersion, onDone, onFail])

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-md">
      <div className="bg-cyber-card border border-white/[0.08] rounded-2xl p-8 max-w-md w-full mx-4 text-center shadow-2xl">
        <div className="w-12 h-12 mx-auto mb-4 rounded-full border-2 border-blue-500/40 border-t-blue-400 animate-spin" />
        <h3 className="text-lg font-semibold text-white mb-2">Platform güncelleniyor</h3>
        <p className="text-sm text-slate-300 mb-1">{msg}</p>
        <p className="text-xs text-slate-500">Geçen süre: {elapsed}s — sayfayı kapatmayın</p>
      </div>
    </div>
  )
}

export const PlatformUpdateTab: React.FC = () => {
  const [file, setFile] = useState<File | null>(null)
  const [prepared, setPrepared] = useState<PreparedInfo | null>(null)
  const [confirmVer, setConfirmVer] = useState('')
  const [overlayVer, setOverlayVer] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const { data: status, refetch: refetchStatus } = useQuery<PlatformCapability>({
    queryKey: ['platform-update-status'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/platform-update/status`)
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    refetchInterval: (q) => (q.state.data?.job?.state === 'running' ? 3000 : 15000),
  })

  const { data: packagesData, refetch: refetchPackages } = useQuery<{ packages: PlatformPackage[] }>({
    queryKey: ['platform-update-packages'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/platform-update/packages`)
      if (!r.ok) {
        if (r.status === 400) return { packages: [] }
        throw new Error(await readError(r))
      }
      return r.json()
    },
    enabled: !!status?.enabled,
  })

  const uploadMut = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Dosya seçin')
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${API_BASE_URL}/platform-update/upload`, { method: 'POST', body: fd })
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    onSuccess: () => {
      setFile(null)
      refetchPackages()
      refetchStatus()
      setErr(null)
    },
    onError: (e) => setErr(e instanceof Error ? e.message : 'Yükleme hatası'),
  })

  const prepareMut = useMutation({
    mutationFn: async (path: string) => {
      const r = await fetch(`${API_BASE_URL}/platform-update/prepare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, allow_downgrade: false }),
      })
      if (!r.ok) throw new Error(await readError(r))
      return r.json() as Promise<PreparedInfo>
    },
    onSuccess: (d) => {
      setPrepared(d)
      setConfirmVer('')
      setErr(null)
    },
    onError: (e) => setErr(e instanceof Error ? e.message : 'Hazırlama hatası'),
  })

  const applyMut = useMutation({
    mutationFn: async () => {
      if (!prepared) throw new Error('Önce paket hazırlayın')
      const r = await fetch(`${API_BASE_URL}/platform-update/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prepared_path: prepared.prepared_path,
          confirm_version: confirmVer.trim(),
        }),
      })
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    onSuccess: (d) => {
      sessionStorage.setItem('ainew_upgrade_expect', d.new_version || prepared?.target_version || '')
      setOverlayVer(d.new_version || prepared?.target_version || '')
    },
    onError: (e) => setErr(e instanceof Error ? e.message : 'Uygulama hatası'),
  })

  const rollbackMut = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/platform-update/rollback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      })
      if (!r.ok) throw new Error(await readError(r))
      return r.json()
    },
    onSuccess: () => {
      setOverlayVer(status?.current_version || 'rollback')
      sessionStorage.setItem('ainew_upgrade_expect', 'rollback')
    },
    onError: (e) => setErr(e instanceof Error ? e.message : 'Geri alma hatası'),
  })

  useEffect(() => {
    const expect = sessionStorage.getItem('ainew_upgrade_expect')
    if (expect && expect !== 'rollback') setOverlayVer(expect)
  }, [])

  const packages = packagesData?.packages || []
  const maxMb = Math.round((status?.max_upload_bytes || 0) / (1024 ** 2))

  return (
    <div>
      {overlayVer && overlayVer !== 'rollback' && (
        <UpgradeOverlay
          expectedVersion={overlayVer}
          onDone={() => {
            sessionStorage.removeItem('ainew_upgrade_expect')
            window.location.reload()
          }}
          onFail={(m) => {
            setErr(m)
            setOverlayVer(null)
            sessionStorage.removeItem('ainew_upgrade_expect')
            refetchStatus()
          }}
        />
      )}

      <h2 className="text-xl font-semibold text-white mb-2">Platform Güncelleme</h2>
      <p className="text-slate-400 text-sm mb-6">
        Dağıtım paketini (.tar.gz) yükleyin veya sunucuda{' '}
        <code className="text-slate-300 bg-cyber-deep px-1 rounded">$DATA_DIR/updates/</code>
        {' '}klasörüne bırakın; ardından GUI üzerinden uygulayın.
      </p>

      {err && (
        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">{err}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Mevcut sürüm</p>
          <p className="text-2xl font-semibold text-white">v{status?.current_version || '—'}</p>
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Kurulum</p>
          <p className="text-sm text-white font-mono break-all">{status?.install_dir || '—'}</p>
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Özellik</p>
          <p className={`text-lg font-semibold ${status?.enabled ? 'text-emerald-400' : 'text-amber-400'}`}>
            {status?.enabled ? 'Aktif' : 'Kapalı'}
          </p>
        </div>
      </div>

      {!status?.enabled && (
        <div className="mb-6 p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-100 text-sm space-y-1">
          <p className="font-medium">Platform güncelleme bu kurulumda kullanılamıyor.</p>
          {(status?.reasons || []).map((r) => (
            <p key={r} className="text-amber-200/80 text-xs">• {r}</p>
          ))}
          <p className="text-xs text-amber-200/70 mt-2">
            Prod paket kurulumunda <code>PLATFORM_UPDATE_ENABLED=true</code> ve docker.sock mount gerekir.
            Geliştirme (volume-mount) ortamında CLI <code>update-rhel.sh</code> kullanın.
          </p>
        </div>
      )}

      {status?.job && status.job.state && status.job.state !== 'idle' && (
        <div className="mb-6 p-4 rounded-xl border border-white/[0.08] bg-cyber-deep/40">
          <p className="text-sm text-slate-300 mb-1">
            Son işlem: <span className="text-white font-medium">{status.job.action || '—'}</span>
            {' · '}
            <span className={
              status.job.state === 'success' ? 'text-emerald-400'
                : status.job.state === 'failed' ? 'text-red-400'
                  : status.job.state === 'running' ? 'text-blue-400'
                    : 'text-slate-300'
            }>
              {status.job.state}
            </span>
          </p>
          <p className="text-xs text-slate-500">{status.job.message}</p>
          {status.job.log_tail && (
            <pre className="mt-3 max-h-40 overflow-auto text-[11px] text-slate-400 bg-black/30 p-3 rounded-lg whitespace-pre-wrap">
              {status.job.log_tail}
            </pre>
          )}
        </div>
      )}

      {status?.enabled && (
        <>
          <div className="mb-6 p-5 bg-cyber-deep/70 rounded-xl border border-emerald-500/30">
            <h3 className="text-base font-semibold text-white mb-1">Paket yükle</h3>
            <p className="text-slate-400 text-xs mb-4">
              Büyük imaj paketleri ({`>`}{maxMb || 8192} MB limit) için SCP önerilir:
              {' '}<code className="text-slate-300">scp ainew-*.tar.gz host:{status.data_dir}/updates/</code>
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <input
                type="file"
                accept=".tar,.tar.gz,.tgz"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block text-sm text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-emerald-600 file:text-white"
              />
              <button
                type="button"
                disabled={!file || uploadMut.isPending}
                onClick={() => uploadMut.mutate()}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
              >
                {uploadMut.isPending ? 'Yükleniyor…' : 'Yükle'}
              </button>
              <button
                type="button"
                onClick={() => { refetchPackages(); refetchStatus() }}
                className="px-4 py-2 bg-slate-600 hover:bg-slate-500 text-white rounded-lg text-sm"
              >
                Yenile
              </button>
            </div>
            {file && <p className="text-emerald-400 text-xs mt-2">Seçili: {file.name} ({fmtBytes(file.size)})</p>}
          </div>

          <div className="mb-6 p-5 bg-cyber-deep/50 rounded-xl border border-white/[0.06]">
            <h3 className="text-base font-semibold text-white mb-3">Bulunan paketler</h3>
            {packages.length === 0 ? (
              <p className="text-slate-500 text-sm">Henüz paket yok. Yükleyin veya sunucuya bırakın.</p>
            ) : (
              <ul className="space-y-2">
                {packages.map((pkg) => (
                  <li
                    key={pkg.path}
                    className="flex flex-wrap items-center justify-between gap-2 py-2 px-3 rounded-lg bg-cyber-card/50 border border-white/[0.06]"
                  >
                    <div className="min-w-0">
                      <p className="text-white font-medium truncate">{pkg.name}</p>
                      <p className="text-xs text-slate-500">
                        v{pkg.version} · {pkg.kind}
                        {pkg.size_bytes != null ? ` · ${fmtBytes(pkg.size_bytes)}` : ''}
                        {pkg.has_images ? ' · images' : ''}
                        {pkg.newer_than_current ? ' · güncel değil' : ''}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={prepareMut.isPending}
                      onClick={() => prepareMut.mutate(pkg.path)}
                      className="px-3 py-1.5 text-xs bg-blue-600/20 text-blue-300 border border-blue-500/40 rounded-lg hover:bg-blue-600/30"
                    >
                      Hazırla
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {prepared && (
            <div className="mb-6 p-5 rounded-xl border-2 border-blue-500/40 bg-blue-500/5">
              <h3 className="text-base font-semibold text-white mb-2">Uygulamaya hazır</h3>
              <p className="text-slate-300 text-sm mb-3">
                <span className="text-white font-mono">v{prepared.current_version}</span>
                {' → '}
                <span className="text-emerald-400 font-mono">v{prepared.target_version}</span>
              </p>
              <p className="text-xs text-slate-500 mb-4">
                Güncelleme öncesi otomatik yedek alınır. Onay için hedef sürümü yazın.
              </p>
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Onay sürümü</label>
                  <input
                    value={confirmVer}
                    onChange={(e) => setConfirmVer(e.target.value)}
                    placeholder={prepared.target_version}
                    className="w-40 bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"
                  />
                </div>
                <button
                  type="button"
                  disabled={applyMut.isPending || confirmVer.trim() !== prepared.target_version}
                  onClick={() => {
                    if (!window.confirm(`${prepared.current_version} → ${prepared.target_version} uygulansın mı?`)) return
                    applyMut.mutate()
                  }}
                  className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold"
                >
                  {applyMut.isPending ? 'Başlatılıyor…' : 'Güncellemeyi Uygula'}
                </button>
              </div>
            </div>
          )}

          <div className="p-4 rounded-xl border border-white/[0.06] bg-cyber-deep/30">
            <h4 className="text-sm font-medium text-slate-300 mb-2">Geri al</h4>
            <p className="text-xs text-slate-500 mb-3">
              Son güncelleme yedeğindeki imaj etiketlerine döner (DB dump restore edilmez).
            </p>
            <button
              type="button"
              disabled={!status.has_backup || rollbackMut.isPending}
              onClick={() => {
                if (!window.confirm('Son yedekten geri alma başlatılsın mı?')) return
                rollbackMut.mutate()
              }}
              className="px-4 py-2 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded-lg text-sm"
            >
              {rollbackMut.isPending ? 'Başlatılıyor…' : 'Son yedekten geri al'}
            </button>
            {!status.has_backup && (
              <p className="text-xs text-slate-600 mt-2">Henüz pre-update yedeği yok.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default PlatformUpdateTab
