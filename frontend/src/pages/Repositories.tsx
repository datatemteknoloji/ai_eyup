import React, { useState, useEffect, useCallback } from 'react'

// ─── Types ──────────────────────────────────────────────────────────────────
interface RepoSource {
  id: number
  name: string
  display_name: string
  repo_type: string
  os_version: string | null
  arch: string
  base_url: string
  auth_type: string
  enabled: boolean
  sync_status: 'never' | 'syncing' | 'synced' | 'failed' | 'partial'
  last_sync: string | null
  package_count: number
  total_size_mb: number
  local_path: string | null
  has_ssl_cert?: boolean
  // RHSM sync
  sync_method?: 'http' | 'rhsm'
  rhsm_repo_id?: string | null
  mirror_host?: string
  mirror_port?: number
  mirror_username?: string | null
  mirror_download_path?: string
}

interface SyncJob {
  id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'partial'
  total_packages: number
  synced_packages: number
  skipped_packages: number
  failed_packages: number
  started_at: string | null
  completed_at: string | null
  created_at?: string | null
  log: string | null
}

interface Package {
  id: number
  name: string
  version: string
  release: string
  epoch: string
  arch: string
  summary: string
  size_bytes: number
  downloaded: boolean
  location: string
}

interface ProductChannel {
  key: string
  label: string
  default: boolean
  url_template: string
}

interface VersionOption {
  label: string
  value: string
  is_latest?: boolean
}

interface ProductTemplate {
  product: string
  repo_type: string
  os_version: string
  auth_type: string
  arch: string
  icon: string
  version_options: VersionOption[]
  channels: ProductChannel[]
  format_note?: string    // 'apt' → Ubuntu/Debian uyarısı
  url_versioned?: boolean // false → URL sabit, versiyon sadece isimde
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
const API = '/api/v1/repos'
const fmtDate = (s: string | null) => s ? new Date(s).toLocaleString('tr-TR') : '—'
const fmtSize = (mb: number) => mb > 1024 ? `${(mb/1024).toFixed(1)} GB` : `${mb} MB`
const fmtPkg  = (n: number) => n.toLocaleString('tr-TR')

const SYNC_COLOR: Record<string, string> = {
  never:     'text-slate-400',
  syncing:   'text-blue-400 animate-pulse',
  synced:    'text-green-400',
  failed:    'text-red-400',
  partial:   'text-orange-400',
  cancelled: 'text-yellow-400',
}
const SYNC_LABEL: Record<string, string> = {
  never:     'Hiç sync edilmedi',
  syncing:   'Sync ediliyor...',
  synced:    'Güncel',
  failed:    'Hata',
  partial:   'Kısmi',
  cancelled: 'İptal edildi',
}

const TYPE_BADGE: Record<string, string> = {
  rhel:   'bg-red-500/20 text-red-300 border-red-500/40',
  oel:    'bg-red-700/20 text-orange-300 border-orange-500/40',
  rocky:  'bg-green-500/20 text-green-300 border-green-500/40',
  alma:   'bg-blue-500/20 text-blue-300 border-blue-500/40',
  centos: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
  custom: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
}

const TYPE_ICON: Record<string, string> = {
  rhel:   '🔴',
  oel:    '🟠',
  rocky:  '🟢',
  ubuntu: '🟠',
  custom: '⚙️',
}

const JOB_STATUS_COLOR: Record<string, string> = {
  pending:   'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  running:   'bg-blue-500/20 text-blue-300 border-blue-500/30',
  completed: 'bg-green-500/20 text-green-300 border-green-500/30',
  failed:    'bg-red-500/20 text-red-300 border-red-500/30',
  partial:   'bg-orange-500/20 text-orange-300 border-orange-500/30',
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const StatCard = ({ label, value, sub }: { label: string; value: string; sub?: string }) => (
  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
    <div className="text-xs text-slate-400 mb-1">{label}</div>
    <div className="text-xl font-bold text-white">{value}</div>
    {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
  </div>
)

// ─── Add Repo Modal ───────────────────────────────────────────────────────────
interface AddRepoModalProps {
  products: ProductTemplate[]
  onClose: () => void
  onCreated: (count: number) => void
}

const AddRepoModal: React.FC<AddRepoModalProps> = ({ products, onClose, onCreated }) => {
  const [mode, setMode] = useState<'product' | 'custom'>('product')
  const [selectedProduct, setSelectedProduct] = useState<ProductTemplate | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<string>('')
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set())
  const [snapshotLabel, setSnapshotLabel] = useState<string>(
    new Date().toISOString().slice(0, 10)  // default: bugünün tarihi YYYY-MM-DD
  )
  const [snapshotMode, setSnapshotMode] = useState<'date' | 'monthly' | 'custom' | 'none'>('date')
  const [credentials, setCredentials] = useState({ username: '', password: '', ssl_cert: '', ssl_key: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Custom form
  const [customForm, setCustomForm] = useState({
    name: '', display_name: '', repo_type: 'custom',
    os_version: '', arch: 'x86_64', base_url: '',
    auth_type: 'none', username: '', password: '',
    ssl_cert: '', ssl_key: '',
  })

  const today = new Date()
  const applySnapshotMode = (mode: typeof snapshotMode) => {
    setSnapshotMode(mode)
    if (mode === 'date')    setSnapshotLabel(today.toISOString().slice(0, 10))
    if (mode === 'monthly') setSnapshotLabel(`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`)
    if (mode === 'none')    setSnapshotLabel('')
  }

  // Versiyona göre URL oluştur
  const resolveUrl = (template: string, version: string): string => {
    if (version === 'latest') return template  // URL template'de {version} yok, sabit
    return template.replace('{version}', version)
  }

  // Versiyon + kanal → repo slug
  const makeSlug = (product: ProductTemplate, version: string, channelKey: string): string => {
    const productSlug = product.product.toLowerCase().replace(/\s+/g, '-')
    const versionSlug = version === 'latest' ? '' : `-${version.replace('.', '_')}`
    return `${productSlug}${versionSlug}-${channelKey}`
  }

  const selectProduct = (p: ProductTemplate) => {
    setSelectedProduct(p)
    const defaultVer = p.version_options[0]?.value || 'latest'
    setSelectedVersion(defaultVer)
    setSelectedChannels(new Set(p.channels.filter(c => c.default).map(c => c.key)))
    setCredentials({ username: '', password: '', ssl_cert: '', ssl_key: '' })
    setError('')
  }

  const toggleChannel = (key: string) => {
    setSelectedChannels(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const saveBatch = async () => {
    if (!selectedProduct) return
    if (selectedChannels.size === 0) { setError('En az bir kanal seçin'); return }
    setSaving(true); setError('')
    try {
      const channels = selectedProduct.channels
        .filter(c => selectedChannels.has(c.key))
        .map(c => ({
          key: makeSlug(selectedProduct, selectedVersion, c.key).split('-').pop()!,
          // slug için sadece kanal key'i yeterli (batch endpoint name'i kendisi oluşturuyor)
          // ama base_url tam URL olmalı
          base_url: resolveUrl(c.url_template, selectedVersion),
          // repo name override: full slug
          name_override: makeSlug(selectedProduct, selectedVersion, c.key),
          display_name_override: `${selectedProduct.product} ${selectedVersion !== 'latest' ? selectedVersion + ' ' : ''}${c.label}`,
        }))

      // product label version'ı içersin
        const productLabel = selectedVersion !== 'latest'
        ? `${selectedProduct.product} ${selectedVersion}`
        : selectedProduct.product

      const body = {
        product: productLabel,
        repo_type: selectedProduct.repo_type,
        os_version: selectedVersion !== 'latest' ? selectedVersion : selectedProduct.os_version,
        arch: selectedProduct.arch,
        auth_type: selectedProduct.auth_type === 'none' ? 'none' : 'basic',
        username: credentials.username || undefined,
        password: credentials.password || undefined,
        snapshot_label: snapshotLabel || undefined,
        channels,
      }
      const r = await fetch(`${API}/batch`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Hata')
      const d = await r.json()
      onCreated(d.created.length)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const saveCustom = async () => {
    if (!customForm.name || !customForm.display_name || !customForm.base_url) {
      setError('Ad, görünen ad ve URL zorunludur'); return
    }
    setSaving(true); setError('')
    try {
      const r = await fetch(API, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(customForm),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Hata')
      onCreated(1)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">Repo Ekle</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl leading-none">×</button>
        </div>

        {/* Mode tabs */}
        <div className="px-6 pt-4 flex gap-2">
          <button onClick={() => setMode('product')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === 'product' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-700'}`}>
            Ürün Seç
          </button>
          <button onClick={() => setMode('custom')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === 'custom' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-slate-700'}`}>
            Özel URL
          </button>
        </div>

        <div className="p-6 space-y-4">

          {/* ── Product mode ─────────────────────────────────────────── */}
          {mode === 'product' && (
            <div className="space-y-4">
              {/* Product grid — RPM grubu */}
              {(() => {
                const rpmTypes = ['rhel','oel','rocky','alma','centos','sles','opensuse','fedora','epel','amzn']
                const aptTypes = ['ubuntu','debian']
                const rpm = products.filter(p => rpmTypes.includes(p.repo_type))
                const apt = products.filter(p => aptTypes.includes(p.repo_type))
                return (
                  <div className="space-y-4 max-h-72 overflow-y-auto pr-1">
                    {/* RPM */}
                    <div>
                      <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-2">RPM Tabanlı</div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                        {rpm.map(p => (
                          <button
                            key={p.product}
                            onClick={() => selectProduct(p)}
                            className={`text-left p-3 rounded-xl border transition-all ${
                              selectedProduct?.product === p.product
                                ? 'border-blue-500 bg-blue-600/15'
                                : 'border-slate-600 bg-slate-700/30 hover:border-slate-500 hover:bg-slate-700/50'
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <span className="text-xl">{TYPE_ICON[p.icon] || TYPE_ICON[p.repo_type] || '📦'}</span>
                              <div>
                                <div className="text-sm font-semibold text-white leading-tight">{p.product}</div>
                                <div className="text-xs text-slate-400 mt-0.5">{p.arch}</div>
                              </div>
                            </div>
                            {p.auth_type !== 'none' && (
                              <div className="mt-1.5 text-xs text-orange-400">🔑 Kimlik gerekli</div>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* APT (Debian/Ubuntu) */}
                    {apt.length > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-2">APT Tabanlı (Metadata)</div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {apt.map(p => (
                            <button
                              key={p.product}
                              onClick={() => selectProduct(p)}
                              className={`text-left p-3 rounded-xl border transition-all ${
                                selectedProduct?.product === p.product
                                  ? 'border-purple-500 bg-purple-600/15'
                                  : 'border-slate-600 bg-slate-700/30 hover:border-slate-500 hover:bg-slate-700/50'
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-xl">{TYPE_ICON[p.repo_type] || '📦'}</span>
                                <div>
                                  <div className="text-sm font-semibold text-white leading-tight">{p.product}</div>
                                  <div className="text-xs text-slate-400 mt-0.5">{p.arch}</div>
                                </div>
                              </div>
                              <div className="mt-1.5 text-xs text-purple-400">📋 Sadece katalog</div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* Channels + credentials */}
              {selectedProduct && (
                <div className="space-y-4 pt-2 border-t border-slate-700">

                  {/* Version selector */}
                  <div>
                    <label className="text-xs text-slate-400 block mb-2">
                      Versiyon
                      {selectedProduct.url_versioned === false && (
                        <span className="ml-2 text-yellow-400">— sadece isimde kullanılır, URL değişmez</span>
                      )}
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {selectedProduct.version_options.map(v => (
                        <button
                          key={v.value}
                          onClick={() => setSelectedVersion(v.value)}
                          className={`px-3 py-1.5 text-sm rounded-lg border transition-all font-medium ${
                            selectedVersion === v.value
                              ? 'bg-blue-600 border-blue-500 text-white'
                              : 'border-slate-600 text-slate-300 hover:border-slate-500 hover:bg-slate-700'
                          }`}
                        >
                          {v.label}
                        </button>
                      ))}
                    </div>

                    {/* Preview: first selected channel slug + URL */}
                    {selectedChannels.size > 0 && selectedVersion && (() => {
                      const firstCh = selectedProduct.channels.find(c => selectedChannels.has(c.key))
                      if (!firstCh) return null
                      const slug = makeSlug(selectedProduct, selectedVersion, firstCh.key)
                      const url  = resolveUrl(firstCh.url_template, selectedVersion)
                      return (
                        <div className="mt-2 bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono space-y-1">
                          <div><span className="text-slate-500">slug: </span><span className="text-blue-300">{slug}</span></div>
                          <div className="text-slate-400 truncate">{url}</div>
                        </div>
                      )
                    })()}
                  </div>

                  <div>
                    <div className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                      <span>{TYPE_ICON[selectedProduct.repo_type] || '📦'}</span>
                      {selectedProduct.product} {selectedVersion !== 'latest' ? selectedVersion : ''} — Kanallar
                      <span className="text-xs text-slate-400 font-normal ml-1">
                        ({selectedChannels.size} seçili)
                      </span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {selectedProduct.channels.map(ch => (
                        <label
                          key={ch.key}
                          className={`flex items-center gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-all ${
                            selectedChannels.has(ch.key)
                              ? 'border-blue-500 bg-blue-600/15'
                              : 'border-slate-600 bg-slate-700/30 hover:border-slate-500'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={selectedChannels.has(ch.key)}
                            onChange={() => toggleChannel(ch.key)}
                            className="accent-blue-500 w-4 h-4 flex-shrink-0"
                          />
                          <span className="text-sm text-white font-medium">{ch.label}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Snapshot / Versiyon Etiketi */}
                  <div className="bg-slate-700/40 border border-slate-600 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm font-semibold text-white">Snapshot Etiketi</div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          Aynı repo'yu farklı tarihlerde sync edebilmek için isimde kullanılır
                        </div>
                      </div>
                    </div>

                    {/* Mode seçici */}
                    <div className="flex gap-2 flex-wrap">
                      {([
                        { key: 'date',    label: '📅 Günlük',  example: today.toISOString().slice(0,10) },
                        { key: 'monthly', label: '📆 Aylık',   example: `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}` },
                        { key: 'custom',  label: '✏️ Özel',    example: '' },
                        { key: 'none',    label: '🚫 Etiket yok', example: '' },
                      ] as const).map(m => (
                        <button
                          key={m.key}
                          onClick={() => applySnapshotMode(m.key)}
                          className={`px-3 py-1.5 text-xs rounded-lg border transition-all font-medium ${
                            snapshotMode === m.key
                              ? 'bg-blue-600 border-blue-500 text-white'
                              : 'border-slate-600 text-slate-300 hover:border-slate-500 hover:bg-slate-700'
                          }`}
                        >
                          {m.label}
                          {m.example && snapshotMode !== m.key && (
                            <span className="ml-1 text-slate-500 font-normal">{m.example}</span>
                          )}
                        </button>
                      ))}
                    </div>

                    {/* Label input */}
                    {snapshotMode !== 'none' && (
                      <div className="flex items-center gap-3">
                        <input
                          value={snapshotLabel}
                          onChange={e => { setSnapshotMode('custom'); setSnapshotLabel(e.target.value) }}
                          placeholder="2026-05-12"
                          className="flex-1 bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
                        />
                        {snapshotLabel && (
                          <div className="text-xs text-slate-400 whitespace-nowrap">
                            örnek: <span className="text-blue-300 font-mono">oel-9-9_5-baseos-{snapshotLabel}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {snapshotMode === 'none' && (
                      <div className="text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2">
                        ⚠️ Etiket olmadan aynı ürün tekrar eklenirse çakışma hatası alırsınız
                      </div>
                    )}
                  </div>

                  {/* Ubuntu/apt uyarısı */}
                  {selectedProduct.format_note === 'apt' && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-3 text-xs text-yellow-300 space-y-1">
                      <div className="font-semibold">⚠️ apt Repo Formatı</div>
                      <div>Ubuntu depo metadata kaydı oluşturulur ancak paket indirme (sync) özelliği şu an sadece RPM (repomd.xml) formatını desteklemektedir. apt desteği yakında eklenecek.</div>
                    </div>
                  )}

                  {/* Credentials (RHEL / kimlik gereken repolar) */}
                  {selectedProduct.auth_type !== 'none' && (
                    <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl p-4 space-y-3">
                      <p className="text-xs text-orange-300">
                        <strong>{selectedProduct.product}</strong> erişimi için Red Hat hesabı gereklidir.
                        Kullanıcı adı/şifre girildiğinde RHSM sertifikası otomatik alınır.
                      </p>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-xs text-slate-400 block mb-1">Red Hat Kullanıcı Adı</label>
                          <input
                            value={credentials.username}
                            onChange={e => setCredentials(p => ({...p, username: e.target.value}))}
                            placeholder="kullanici@example.com"
                            className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                          />
                        </div>
                        <div>
                          <label className="text-xs text-slate-400 block mb-1">Şifre</label>
                          <input
                            type="password"
                            value={credentials.password}
                            onChange={e => setCredentials(p => ({...p, password: e.target.value}))}
                            className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {error && (
                    <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{error}</div>
                  )}

                  <button
                    onClick={saveBatch}
                    disabled={saving || selectedChannels.size === 0}
                    className="w-full py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-40 flex items-center justify-center gap-2"
                  >
                    {saving
                      ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Ekleniyor...</>
                      : `${selectedChannels.size} Kanal Ekle`
                    }
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Custom mode ───────────────────────────────────────────── */}
          {mode === 'custom' && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Slug (benzersiz)</label>
                  <input value={customForm.name}
                    onChange={e => setCustomForm(p => ({...p, name: e.target.value.toLowerCase().replace(/\s+/g,'-')}))}
                    placeholder="custom-repo" className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Görünen Ad</label>
                  <input value={customForm.display_name}
                    onChange={e => setCustomForm(p => ({...p, display_name: e.target.value}))}
                    placeholder="Custom Repo" className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">Base URL</label>
                <input value={customForm.base_url}
                  onChange={e => setCustomForm(p => ({...p, base_url: e.target.value}))}
                  placeholder="https://..." className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Tip</label>
                  <select value={customForm.repo_type} onChange={e => setCustomForm(p => ({...p, repo_type: e.target.value}))}
                    className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
                    {['oel','rhel','rocky','alma','centos','custom'].map(t => (
                      <option key={t} value={t}>{t.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">OS Ver.</label>
                  <input value={customForm.os_version} onChange={e => setCustomForm(p => ({...p, os_version: e.target.value}))}
                    placeholder="9" className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Auth</label>
                  <select value={customForm.auth_type} onChange={e => setCustomForm(p => ({...p, auth_type: e.target.value}))}
                    className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
                    <option value="none">Yok</option>
                    <option value="basic">Basic</option>
                    <option value="ssl_cert">SSL Cert</option>
                  </select>
                </div>
              </div>
              {customForm.auth_type === 'basic' && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">Kullanıcı</label>
                    <input value={customForm.username} onChange={e => setCustomForm(p => ({...p, username: e.target.value}))}
                      className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">Şifre</label>
                    <input type="password" value={customForm.password} onChange={e => setCustomForm(p => ({...p, password: e.target.value}))}
                      className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                </div>
              )}
              {error && <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{error}</div>}
              <button onClick={saveCustom} disabled={saving}
                className="w-full py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-40 flex items-center justify-center gap-2">
                {saving ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Kaydediliyor...</> : 'Ekle'}
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

// ─── Package Browser Modal ────────────────────────────────────────────────────
const PackageBrowser: React.FC<{ repo: RepoSource; onClose: () => void }> = ({ repo, onClose }) => {
  const [search, setSearch] = useState('')
  const [arch, setArch] = useState('')
  const [downloaded, setDownloaded] = useState<'all' | 'yes' | 'no'>('all')
  const [packages, setPackages] = useState<Package[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)
  const limit = 100

  const load = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({
      skip: String(page * limit),
      limit: String(limit),
      ...(search && { search }),
      ...(arch && { arch }),
      ...(downloaded !== 'all' && { downloaded: downloaded === 'yes' ? 'true' : 'false' }),
    })
    const r = await fetch(`${API}/${repo.id}/packages?${params}`)
    if (r.ok) { const d = await r.json(); setPackages(d.packages); setTotal(d.total) }
    setLoading(false)
  }, [repo.id, search, arch, downloaded, page])

  useEffect(() => { load() }, [load])

  const fmtEvr = (p: Package) => {
    let s = p.version
    if (p.release) s += `-${p.release}`
    if (p.epoch && p.epoch !== '0') s = `${p.epoch}:${s}`
    return s
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-white">{repo.display_name}</h2>
            <p className="text-xs text-slate-400">{total.toLocaleString('tr-TR')} paket</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        {/* Filters */}
        <div className="px-6 py-3 border-b border-slate-700 flex flex-wrap gap-3 flex-shrink-0">
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(0) }}
            placeholder="Paket ara..." className="flex-1 min-w-[180px] bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
          <input value={arch} onChange={e => { setArch(e.target.value); setPage(0) }}
            placeholder="arch (x86_64)" className="w-32 bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
          <select value={downloaded} onChange={e => { setDownloaded(e.target.value as any); setPage(0) }}
            className="bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
            <option value="all">Tümü</option>
            <option value="yes">İndirilmiş</option>
            <option value="no">İndirilmemiş</option>
          </select>
        </div>

        {/* Package list */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : packages.length === 0 ? (
            <div className="text-center py-12 text-slate-500">Paket bulunamadı</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-700/50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium">Paket</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium">Versiyon</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-20">Arch</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-24">Boyut</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-24">Durum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {packages.map(p => (
                  <tr key={p.id} className="hover:bg-slate-700/20 transition-colors">
                    <td className="px-4 py-2">
                      <div className="font-medium text-white">{p.name}</div>
                      <div className="text-xs text-slate-400 truncate max-w-xs">{p.summary}</div>
                    </td>
                    <td className="px-4 py-2 text-slate-300 font-mono text-xs">{fmtEvr(p)}</td>
                    <td className="px-4 py-2 text-slate-400 text-xs">{p.arch}</td>
                    <td className="px-4 py-2 text-slate-400 text-xs">{p.size_bytes > 0 ? (p.size_bytes/1024/1024).toFixed(1)+' MB' : '—'}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${p.downloaded ? 'text-green-300 bg-green-500/10 border-green-500/30' : 'text-slate-400 bg-slate-700/50 border-slate-600'}`}>
                        {p.downloaded ? '✓ Yerel' : 'Metadata'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {total > limit && (
          <div className="px-6 py-3 border-t border-slate-700 flex items-center justify-between flex-shrink-0">
            <span className="text-xs text-slate-400">{page * limit + 1}–{Math.min((page+1)*limit, total)} / {total}</span>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p-1))} disabled={page === 0}
                className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded-lg disabled:opacity-40">← Önceki</button>
              <button onClick={() => setPage(p => p+1)} disabled={(page+1)*limit >= total}
                className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-white rounded-lg disabled:opacity-40">Sonraki →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Client Config Modal ──────────────────────────────────────────────────────
const ClientConfigModal: React.FC<{ repo: RepoSource; onClose: () => void }> = ({ repo, onClose }) => {
  const [serverIp, setServerIp] = useState('')
  const [port, setPort] = useState('8000')
  const [repoContent, setRepoContent] = useState('')
  const [servers, setServers] = useState<any[]>([])
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [pushing, setPushing] = useState(false)
  const [pushResults, setPushResults] = useState<Record<string, any>>({})

  useEffect(() => {
    fetch('/api/v1/servers').then(r => r.json()).then(setServers).catch(() => {})
  }, [])

  const generateConfig = async () => {
    if (!serverIp) return
    const r = await fetch(`${API}/${repo.id}/client-config?server_ip=${serverIp}&port=${port}`)
    if (r.ok) { const d = await r.json(); setRepoContent(d.content) }
  }

  const pushConfig = async () => {
    if (!repoContent || selectedServers.length === 0) return
    setPushing(true)
    const r = await fetch(`${API}/${repo.id}/push-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server_ids: selectedServers, server_ip: serverIp, port: parseInt(port) }),
    })
    if (r.ok) { const d = await r.json(); setPushResults(d.results) }
    setPushing(false)
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">İstemci Yapılandırması — {repo.display_name}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="p-6 space-y-5">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-3 text-xs text-blue-300">
            Sunucular bu repo'yu <code>/etc/yum.repos.d/{repo.name}.repo</code> dosyası ile kullanır.
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-slate-400 block mb-1">Yönetim Sunucusu IP</label>
              <input value={serverIp} onChange={e => setServerIp(e.target.value)}
                placeholder="192.168.1.100" className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <div className="w-24">
              <label className="text-xs text-slate-400 block mb-1">Port</label>
              <input value={port} onChange={e => setPort(e.target.value)}
                className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <div className="flex items-end">
              <button onClick={generateConfig}
                className="px-4 py-2 bg-purple-700 hover:bg-purple-600 text-white text-sm rounded-lg transition-colors">
                Oluştur
              </button>
            </div>
          </div>

          {repoContent && (
            <>
              <div>
                <label className="text-xs text-slate-400 block mb-1">.repo dosyası içeriği</label>
                <pre className="bg-slate-900 text-green-300 text-xs p-4 rounded-xl font-mono whitespace-pre overflow-x-auto border border-slate-700">{repoContent}</pre>
                <button
                  onClick={() => navigator.clipboard.writeText(repoContent)}
                  className="mt-2 text-xs text-blue-400 hover:text-blue-300"
                >
                  Kopyala
                </button>
              </div>

              <div>
                <label className="text-xs text-slate-400 block mb-2">SSH ile sunuculara gönder</label>
                <div className="max-h-40 overflow-y-auto border border-slate-700 rounded-xl divide-y divide-slate-700/50">
                  {servers.map((srv: any) => (
                    <label key={srv.id} className={`flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-slate-700/30 ${selectedServers.includes(srv.id) ? 'bg-blue-600/10' : ''}`}>
                      <input type="checkbox" checked={selectedServers.includes(srv.id)}
                        onChange={() => setSelectedServers(p => p.includes(srv.id) ? p.filter(x => x !== srv.id) : [...p, srv.id])}
                        className="accent-blue-500 w-4 h-4" />
                      <span className={`w-2 h-2 rounded-full ${srv.status === 'ONLINE' ? 'bg-green-400' : 'bg-slate-500'}`} />
                      <span className="text-sm text-white">{srv.name}</span>
                      <span className="text-xs text-slate-400 ml-auto">{srv.ip_address}</span>
                    </label>
                  ))}
                </div>

                <button onClick={pushConfig} disabled={pushing || selectedServers.length === 0}
                  className="mt-3 w-full py-2.5 bg-green-700 hover:bg-green-600 text-white text-sm font-medium rounded-xl transition-all disabled:opacity-40 flex items-center justify-center gap-2">
                  {pushing ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Gönderiliyor...</> : `${selectedServers.length} Sunucuya Gönder`}
                </button>

                {Object.keys(pushResults).length > 0 && (
                  <div className="mt-3 space-y-1">
                    {Object.entries(pushResults).map(([sid, res]: [string, any]) => (
                      <div key={sid} className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg ${res.status === 'success' ? 'bg-green-500/10 text-green-300' : 'bg-red-500/10 text-red-300'}`}>
                        <span>{res.status === 'success' ? '✓' : '✗'}</span>
                        <span className="font-medium">{res.server_name}</span>
                        <span className="text-slate-400">{res.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Sync Log Modal ───────────────────────────────────────────────────────────
const SyncLogModal: React.FC<{ repo: RepoSource; onClose: () => void }> = ({ repo, onClose }) => {
  const [jobs, setJobs] = useState<SyncJob[]>([])
  const [selectedJob, setSelectedJob] = useState<SyncJob | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const r = await fetch(`${API}/${repo.id}/jobs`)
    if (r.ok) setJobs(await r.json())
    setLoading(false)
  }, [repo.id])

  useEffect(() => { load() }, [load])

  // Auto-refresh if any job is running
  useEffect(() => {
    const hasRunning = jobs.some(j => j.status === 'running' || j.status === 'pending')
    if (!hasRunning) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [jobs, load])

  useEffect(() => {
    if (!selectedJob) return
    if (jobs.length > 0) {
      const updated = jobs.find(j => j.id === selectedJob.id)
      if (updated) setSelectedJob(updated)
    }
  }, [jobs, selectedJob])

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
          <h2 className="text-lg font-semibold text-white">Sync Geçmişi — {repo.display_name}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="flex-1 overflow-hidden flex gap-0">
          {/* Job list */}
          <div className="w-72 border-r border-slate-700 overflow-y-auto flex-shrink-0">
            {loading ? (
              <div className="p-6 text-center"><div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" /></div>
            ) : jobs.length === 0 ? (
              <div className="p-6 text-center text-slate-500 text-sm">Henüz sync yapılmadı</div>
            ) : (
              jobs.map(j => (
                <button key={j.id} onClick={() => setSelectedJob(j)}
                  className={`w-full text-left px-4 py-3 hover:bg-slate-700/30 transition-colors border-b border-slate-700/50 ${selectedJob?.id === j.id ? 'bg-blue-600/10' : ''}`}>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${JOB_STATUS_COLOR[j.status]}`}>{j.status}</span>
                    {(j.status === 'running' || j.status === 'pending') && <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />}
                  </div>
                  <div className="text-xs text-slate-400 mt-1">{fmtDate(j.started_at ?? j.created_at ?? null)}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{j.synced_packages}/{j.total_packages} paket</div>
                </button>
              ))
            )}
          </div>

          {/* Job detail */}
          <div className="flex-1 overflow-y-auto p-5">
            {selectedJob ? (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div className="bg-slate-700/50 rounded-lg p-3">
                    <div className="text-slate-400">Toplam</div>
                    <div className="text-white font-bold text-lg">{selectedJob.total_packages.toLocaleString('tr-TR')}</div>
                  </div>
                  <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3">
                    <div className="text-slate-400">Synced</div>
                    <div className="text-green-300 font-bold text-lg">{selectedJob.synced_packages.toLocaleString('tr-TR')}</div>
                  </div>
                  <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                    <div className="text-slate-400">Hatalı</div>
                    <div className="text-red-300 font-bold text-lg">{selectedJob.failed_packages.toLocaleString('tr-TR')}</div>
                  </div>
                </div>

                {(selectedJob.status === 'running' || selectedJob.status === 'pending') && (
                  <div>
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span>İlerleme</span>
                      <span>{Math.round((selectedJob.synced_packages / Math.max(selectedJob.total_packages, 1)) * 100)}%</span>
                    </div>
                    <div className="bg-slate-700 rounded-full h-2">
                      <div className="bg-blue-500 h-2 rounded-full transition-all"
                        style={{ width: `${Math.round((selectedJob.synced_packages / Math.max(selectedJob.total_packages, 1)) * 100)}%` }} />
                    </div>
                  </div>
                )}

                {selectedJob.log && (
                  <div>
                    <div className="text-xs text-slate-400 mb-2">İşlem Logu</div>
                    <pre className="bg-slate-900 border border-slate-700 rounded-xl p-4 text-xs text-green-300 font-mono whitespace-pre-wrap max-h-80 overflow-y-auto">
                      {selectedJob.log}
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">
                ← Detay için bir iş seçin
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── RHSM Sync Settings Modal ────────────────────────────────────────────────
const RhsmSettingsModal: React.FC<{ repo: RepoSource; onClose: () => void; onSaved: () => void }> = ({ repo, onClose, onSaved }) => {
  const [form, setForm] = useState({
    rhsm_repo_id:         repo.rhsm_repo_id || '',
    mirror_host:          repo.mirror_host || '127.0.0.1',
    mirror_port:          String(repo.mirror_port || 22),
    mirror_username:      repo.mirror_username || 'root',
    mirror_password:      '',
    mirror_download_path: repo.mirror_download_path || '/var/lib/server_management/repos',
  })
  const [saving, setSaving]     = useState(false)
  const [testing, setTesting]   = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [error, setError]       = useState('')

  const save = async () => {
    setSaving(true); setError('')
    try {
      const r = await fetch(`${API}/${repo.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sync_method:          'rhsm',
          rhsm_repo_id:         form.rhsm_repo_id,
          mirror_host:          form.mirror_host,
          mirror_port:          parseInt(form.mirror_port),
          mirror_username:      form.mirror_username,
          mirror_password:      form.mirror_password || undefined,
          mirror_download_path: form.mirror_download_path,
        }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Hata')
      onSaved()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const r = await fetch(`${API}/${repo.id}/rhsm-check-status`, { method: 'POST' })
      if (r.ok) setTestResult(await r.json())
      else setTestResult({ registered: false, status: (await r.json()).detail })
    } catch (e: any) {
      setTestResult({ registered: false, status: e.message })
    } finally {
      setTesting(false)
    }
  }

  const listRepos = async () => {
    setTesting(true); setTestResult(null)
    try {
      const r = await fetch(`${API}/${repo.id}/rhsm-list-repos`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setTestResult({ repos: d.repos, total: d.total })
      }
    } catch (e: any) {
      setTestResult({ error: e.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-white">RHSM Sync Ayarları</h2>
            <p className="text-xs text-slate-400 mt-0.5">{repo.display_name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="p-6 space-y-5">
          {/* Açıklama */}
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4 text-xs text-blue-300 space-y-1.5">
            <div className="font-semibold text-sm">📋 subscription-manager + reposync</div>
            <div>Bu mod, belirtilen mirror host'a SSH bağlanır ve <code>subscription-manager</code> + <code>reposync</code> komutlarını çalıştırır.</div>
            <div>Mirror host varsayılan olarak <strong>127.0.0.1</strong> (bu yönetim sunucusu). Host RHEL/OEL ise subscription-manager kurulu olmalıdır.</div>
          </div>

          {/* RHSM Repo ID */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">
              RHSM Repo ID <span className="text-slate-500">(subscription-manager repos --list ile bulunabilir)</span>
            </label>
            <input
              value={form.rhsm_repo_id}
              onChange={e => setForm(p => ({...p, rhsm_repo_id: e.target.value}))}
              placeholder="rhel-9-for-x86_64-baseos-rpms"
              className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Mirror Host */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="text-xs text-slate-400 block mb-1">Mirror Host (SSH)</label>
              <input
                value={form.mirror_host}
                onChange={e => setForm(p => ({...p, mirror_host: e.target.value}))}
                placeholder="127.0.0.1"
                className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">Port</label>
              <input
                value={form.mirror_port}
                onChange={e => setForm(p => ({...p, mirror_port: e.target.value}))}
                className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">SSH Kullanıcı</label>
              <input
                value={form.mirror_username}
                onChange={e => setForm(p => ({...p, mirror_username: e.target.value}))}
                placeholder="root"
                className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">SSH Şifre</label>
              <input
                type="password"
                value={form.mirror_password}
                onChange={e => setForm(p => ({...p, mirror_password: e.target.value}))}
                placeholder="(değiştirmek için girin)"
                className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-400 block mb-1">
              İndirme Dizini (host'ta)
              <span className="text-slate-500 ml-1">— container bu dizini /app/repos olarak görür</span>
            </label>
            <input
              value={form.mirror_download_path}
              onChange={e => setForm(p => ({...p, mirror_download_path: e.target.value}))}
              placeholder="/var/lib/server_management/repos"
              className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Test butonları */}
          <div className="flex gap-2 flex-wrap">
            <button onClick={testConnection} disabled={testing}
              className="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors disabled:opacity-40">
              {testing ? '...' : '🔌 Bağlantıyı Test Et'}
            </button>
            <button onClick={listRepos} disabled={testing}
              className="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors disabled:opacity-40">
              {testing ? '...' : '📋 Mevcut Repo\'ları Listele'}
            </button>
          </div>

          {/* Test sonucu */}
          {testResult && (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 text-xs font-mono">
              {'repos' in testResult ? (
                <div className="space-y-1 max-h-52 overflow-y-auto">
                  <div className="text-slate-400 mb-2">{testResult.total} repo bulundu:</div>
                  {testResult.repos.map((r: any) => (
                    <div key={r.id} className={`flex items-center gap-2 ${r.enabled ? 'text-green-300' : 'text-slate-400'}`}>
                      <span>{r.enabled ? '●' : '○'}</span>
                      <span className="font-medium">{r.id}</span>
                      <span className="text-slate-500">{r.name}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div>
                  <div className={`font-semibold mb-1 ${testResult.registered ? 'text-green-300' : 'text-red-300'}`}>
                    {testResult.registered ? '✓ Abonelik aktif' : '✗ Kayıtlı değil / Erişilemiyor'}
                  </div>
                  <pre className="text-slate-300 whitespace-pre-wrap">{testResult.status}</pre>
                </div>
              )}
            </div>
          )}

          {error && <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{error}</div>}

          <button onClick={save} disabled={saving}
            className="w-full py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-40 flex items-center justify-center gap-2">
            {saving ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Kaydediliyor...</> : '💾 Kaydet'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Progress type ────────────────────────────────────────────────────────────
interface SyncProgress {
  rpm_on_disk: number
  disk_mb: number
  total_packages: number
  synced_packages: number
  log_tail: string
}

// ─── Repo Row (tablo satırı) ──────────────────────────────────────────────────
const RepoRow: React.FC<{
  repo: RepoSource
  progress: SyncProgress | null
  onSync: (id: number, metaOnly: boolean) => void
  onSyncRhsm: (id: number) => void
  onCancel: (id: number) => void
  onDelete: (id: number) => void
  onPackages: (repo: RepoSource) => void
  onConfig: (repo: RepoSource) => void
  onLogs: (repo: RepoSource) => void
  onFetchCerts: (id: number) => void
  onRhsmSettings: (repo: RepoSource) => void
}> = ({ repo, progress, onSync, onSyncRhsm, onCancel, onDelete, onPackages, onConfig, onLogs, onFetchCerts, onRhsmSettings }) => {
  const syncing = repo.sync_status === 'syncing'

  return (
    <tr className="border-b border-slate-700/60 hover:bg-slate-800/60 transition-colors group">
      {/* Dağıtım + ad */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-lg flex-shrink-0">{TYPE_ICON[repo.repo_type] || '📦'}</span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-white truncate max-w-[220px]">{repo.display_name}</div>
            <div className="text-xs text-slate-500 font-mono truncate max-w-[220px]">{repo.name}</div>
          </div>
        </div>
      </td>

      {/* Tip badge */}
      <td className="px-3 py-3 whitespace-nowrap">
        <span className={`text-xs px-2 py-0.5 rounded-full border ${TYPE_BADGE[repo.repo_type] || TYPE_BADGE.custom}`}>
          {repo.repo_type.toUpperCase()}{repo.os_version ? ` ${repo.os_version}` : ''}
        </span>
      </td>

      {/* Sync durumu */}
      <td className="px-3 py-3 min-w-[200px]">
        {syncing && progress ? (
          <div className="space-y-1.5">
            {/* İlerleme çubuğu */}
            {progress.total_packages > 0 ? (
              <>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-blue-300 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />
                    {progress.rpm_on_disk.toLocaleString('tr-TR')} / {progress.total_packages.toLocaleString('tr-TR')} RPM
                  </span>
                  <span className="text-slate-400">
                    {Math.round(progress.rpm_on_disk * 100 / progress.total_packages)}%
                  </span>
                </div>
                <div className="w-full bg-slate-700 rounded-full h-1.5">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(Math.round(progress.rpm_on_disk * 100 / progress.total_packages), 100)}%` }}
                  />
                </div>
                <div className="text-xs text-slate-400">{progress.disk_mb >= 1024 ? `${(progress.disk_mb/1024).toFixed(1)} GB` : `${progress.disk_mb} MB`} indirildi</div>
              </>
            ) : (
              <span className="text-xs text-blue-400 flex items-center gap-1 animate-pulse">
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />
                Metadata çekiliyor...
              </span>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className={`text-xs font-medium flex items-center gap-1 ${SYNC_COLOR[repo.sync_status] || 'text-slate-400'}`}>
              {SYNC_LABEL[repo.sync_status] || repo.sync_status}
            </span>
            {repo.last_sync && (
              <span className="text-xs text-slate-500">{fmtDate(repo.last_sync)}</span>
            )}
          </div>
        )}
      </td>

      {/* Paket / Boyut */}
      <td className="px-3 py-3 whitespace-nowrap text-center">
        <div className="text-sm font-medium text-white">{fmtPkg(repo.package_count)}</div>
        <div className="text-xs text-slate-500">{repo.total_size_mb > 0 ? fmtSize(repo.total_size_mb) : '—'}</div>
      </td>

      {/* Auth / Sertifika */}
      <td className="px-3 py-3 whitespace-nowrap">
        {repo.repo_type === 'rhel' ? (
          repo.has_ssl_cert ? (
            <span className="text-xs text-green-400 flex items-center gap-1">✓ Sertifikalı</span>
          ) : (
            <button onClick={() => onFetchCerts(repo.id)}
              className="text-xs text-orange-300 bg-orange-500/10 border border-orange-500/30 px-2 py-1 rounded-lg hover:bg-orange-500/20 transition-colors whitespace-nowrap">
              ⚠️ Sertifika Al
            </button>
          )
        ) : (
          <span className="text-xs text-green-400">Açık</span>
        )}
      </td>

      {/* İşlemler */}
      <td className="px-3 py-3">
        <div className="flex items-center gap-1 flex-wrap">

          {/* Sync / Durdur */}
          {syncing ? (
            <button onClick={() => onCancel(repo.id)}
              className="px-2.5 py-1 text-xs font-semibold bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-red-300 rounded-full animate-pulse flex-shrink-0" />
              Durdur
            </button>
          ) : repo.sync_method === 'rhsm' ? (
            <button onClick={() => onSyncRhsm(repo.id)}
              className="px-2.5 py-1 text-xs bg-purple-700 hover:bg-purple-600 text-white rounded-lg transition-colors">
              Sync
            </button>
          ) : (
            <>
              <button onClick={() => onSync(repo.id, false)}
                className="px-2.5 py-1 text-xs bg-green-700 hover:bg-green-600 text-white rounded-lg transition-colors">
                Sync
              </button>
              <button onClick={() => onSync(repo.id, true)}
                className="px-2.5 py-1 text-xs bg-blue-800 hover:bg-blue-700 text-blue-200 rounded-lg transition-colors">
                Meta
              </button>
            </>
          )}

          {/* Log — her zaman görünür */}
          <button onClick={() => onLogs(repo)}
            className="px-2.5 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors">
            Log
          </button>

          {/* Paketler */}
          <button onClick={() => onPackages(repo)} disabled={repo.package_count === 0}
            className="px-2.5 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors disabled:opacity-30">
            Paketler
          </button>

          {/* .repo */}
          <button onClick={() => onConfig(repo)}
            className="px-2.5 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors">
            .repo
          </button>

          {/* RHSM ayarları */}
          {repo.repo_type === 'rhel' && (
            <button onClick={() => onRhsmSettings(repo)}
              className="px-2.5 py-1 text-xs bg-purple-900/50 hover:bg-purple-800/60 text-purple-300 border border-purple-700/40 rounded-lg transition-colors">
              RHSM
            </button>
          )}

          {/* Sil */}
          <button onClick={() => onDelete(repo.id)}
            className="px-2.5 py-1 text-xs text-red-400 hover:text-white hover:bg-red-700 rounded-lg transition-colors">
            Sil
          </button>

        </div>
      </td>
    </tr>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const Repositories: React.FC = () => {
  const [repos, setRepos]           = useState<RepoSource[]>([])
  const [products, setProducts]     = useState<ProductTemplate[]>([])
  const [loading, setLoading]       = useState(true)
  const [showAdd, setShowAdd]       = useState(false)
  const [aggStats, setAggStats]     = useState<any>(null)
  const [progressMap, setProgressMap] = useState<Record<number, SyncProgress>>({})
  const [packageBrowserRepo, setPackageBrowserRepo] = useState<RepoSource | null>(null)
  const [clientConfigRepo, setClientConfigRepo] = useState<RepoSource | null>(null)
  const [syncLogRepo, setSyncLogRepo] = useState<RepoSource | null>(null)
  const [rhsmSettingsRepo, setRhsmSettingsRepo] = useState<RepoSource | null>(null)
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type }); setTimeout(() => setToast(null), 4000)
  }

  const loadRepos = useCallback(async () => {
    const r = await fetch(API)
    if (r.ok) setRepos(await r.json())
    setLoading(false)
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const r = await fetch(`${API}/aggregate-stats`)
      if (r.ok) setAggStats(await r.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    loadRepos()
    loadStats()
    fetch(`${API}/templates/products`).then(r => r.json()).then(setProducts).catch(() => {})
  }, [loadRepos])

  // Merkezi progress polling — tüm syncing repolar için tek interval
  useEffect(() => {
    const syncingIds = repos.filter(r => r.sync_status === 'syncing').map(r => r.id)
    if (syncingIds.length === 0) return

    const pollProgress = async () => {
      const results = await Promise.allSettled(
        syncingIds.map(id =>
          fetch(`${API}/${id}/progress`).then(r => r.ok ? r.json() : null)
        )
      )
      const newMap: Record<number, SyncProgress> = {}
      results.forEach((res, i) => {
        if (res.status === 'fulfilled' && res.value) {
          newMap[syncingIds[i]] = res.value
        }
      })
      // setProgressMap ile partial güncelleme — repos state'e dokunmaz
      setProgressMap(prev => ({ ...prev, ...newMap }))
    }

    pollProgress()
    const t = setInterval(pollProgress, 4000)
    return () => clearInterval(t)
  }, [repos])   // repos değişince (yeni sync başlayınca) interval yenilenir

  // Auto-refresh repo listesi + stats (daha seyrek — her 10 sn)
  useEffect(() => {
    const hasSyncing = repos.some(r => r.sync_status === 'syncing')
    if (!hasSyncing) return
    const t = setInterval(() => { loadRepos(); loadStats() }, 10000)
    return () => clearInterval(t)
  }, [repos, loadRepos, loadStats])

  const handleSync = async (repoId: number, metaOnly: boolean) => {
    const url = metaOnly ? `${API}/${repoId}/sync-metadata` : `${API}/${repoId}/sync`
    const r = await fetch(url, { method: 'POST' })
    if (r.ok) { showToast(metaOnly ? 'Metadata sync başlatıldı' : 'Tam sync başlatıldı'); await loadRepos() }
    else showToast((await r.json()).detail || 'Hata', 'err')
  }

  const handleCancel = async (repoId: number) => {
    const r = await fetch(`${API}/${repoId}/cancel-sync`, { method: 'POST' })
    if (r.ok) { showToast('Sync durduruldu'); await loadRepos() }
    else showToast((await r.json()).detail || 'Hata', 'err')
  }

  const handleSyncRhsm = async (repoId: number) => {
    const r = await fetch(`${API}/${repoId}/sync-rhsm`, { method: 'POST' })
    if (r.ok) { showToast('RHSM sync başlatıldı'); await loadRepos() }
    else showToast((await r.json()).detail || 'Hata', 'err')
  }

  const handleFetchCerts = async (repoId: number) => {
    showToast('RHSM API\'ye bağlanılıyor, lütfen bekleyin...')
    try {
      const r = await fetch(`${API}/${repoId}/fetch-rhsm-certs`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || 'Hata')
      showToast(`✓ ${d.message}`)
      await loadRepos()
    } catch (e: any) {
      showToast(e.message || 'RHSM sertifikası alınamadı', 'err')
    }
  }

  const handleDelete = async (repoId: number) => {
    const repo = repos.find(r => r.id === repoId)
    const isSyncing = repo?.sync_status === 'syncing'
    const msg = isSyncing
      ? 'Sync devam ediyor! Durdurulup silinecek. Emin misiniz?'
      : 'Bu repo ve tüm yerel dosyaları silinecek. Emin misiniz?'
    if (!confirm(msg)) return
    const url = isSyncing ? `${API}/${repoId}?force=true` : `${API}/${repoId}`
    const r = await fetch(url, { method: 'DELETE' })
    if (r.ok) { showToast('Repo silindi'); await loadRepos() }
    else showToast((await r.json()).detail || 'Silinemedi', 'err')
  }

  const totalPackages = repos.reduce((s, r) => s + r.package_count, 0)
  const totalSize     = repos.reduce((s, r) => s + r.total_size_mb, 0)
  const syncedCount   = repos.filter(r => r.sync_status === 'synced').length
  const syncingCount  = repos.filter(r => r.sync_status === 'syncing').length

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Local Repository Yönetimi</h1>
          <p className="text-slate-400 text-sm mt-1">
            Satellite/Foreman gibi — RHEL, OEL, Rocky için local mirror yönetimi
          </p>
        </div>
        <button onClick={() => setShowAdd(true)}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
          + Repo Ekle
        </button>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium ${
          toast.type === 'ok' ? 'bg-green-900/90 border-green-500/50 text-green-300' : 'bg-red-900/90 border-red-500/50 text-red-300'
        }`}>
          {toast.type === 'ok' ? '✓ ' : '✗ '}{toast.msg}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="Toplam Repo"
          value={String(aggStats?.total_repos ?? repos.length)}
          sub={`${aggStats?.synced_repos ?? syncedCount} güncel`}
        />
        <StatCard
          label="Yerel RPM"
          value={aggStats ? fmtPkg(aggStats.total_rpm) : fmtPkg(totalPackages)}
          sub={aggStats ? 'disk\'te mevcut' : 'tüm repolar'}
        />
        <StatCard
          label="Disk Kullanımı"
          value={aggStats
            ? (aggStats.disk_gb >= 1 ? `${aggStats.disk_gb.toFixed(1)} GB` : `${aggStats.disk_mb} MB`)
            : fmtSize(totalSize)
          }
          sub="yerel depo"
        />
        <StatCard
          label="Sync Durumu"
          value={
            aggStats?.syncing_repos > 0
              ? `${aggStats.syncing_repos} aktif`
              : (syncingCount > 0 ? `${syncingCount} aktif` : 'Boşta')
          }
          sub={
            aggStats && aggStats.active_total_packages > 0
              ? `${fmtPkg(aggStats.active_synced_packages)} / ${fmtPkg(aggStats.active_total_packages)} paket`
              : (syncingCount > 0 ? 'işlem devam ediyor' : 'tümü hazır')
          }
        /></div>

      {/* Repo list */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : repos.length === 0 ? (
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-16 text-center">
          <div className="text-6xl mb-4">📦</div>
          <h3 className="text-lg font-semibold text-white">Henüz repo yok</h3>
          <p className="text-slate-400 text-sm mt-2">OEL, RHEL veya Rocky Linux mirror'ı ekleyin</p>
          <button onClick={() => setShowAdd(true)}
            className="mt-4 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
            İlk Repo'yu Ekle
          </button>
        </div>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-700/60 border-b border-slate-600">
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">Repo</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">Tip</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">Durum</th>
                <th className="text-center px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">Paket / Boyut</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">Auth</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {repos.map(repo => (
                <RepoRow key={repo.id} repo={repo}
                  progress={progressMap[repo.id] ?? null}
                  onSync={handleSync}
                  onSyncRhsm={handleSyncRhsm}
                  onCancel={handleCancel}
                  onDelete={handleDelete}
                  onPackages={setPackageBrowserRepo}
                  onConfig={setClientConfigRepo}
                  onLogs={setSyncLogRepo}
                  onFetchCerts={handleFetchCerts}
                  onRhsmSettings={setRhsmSettingsRepo}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modals */}
      {showAdd && (
        <AddRepoModal products={products} onClose={() => setShowAdd(false)}
          onCreated={(count) => { setShowAdd(false); loadRepos(); showToast(`${count} repo eklendi`) }} />
      )}
      {packageBrowserRepo && (
        <PackageBrowser repo={packageBrowserRepo} onClose={() => setPackageBrowserRepo(null)} />
      )}
      {clientConfigRepo && (
        <ClientConfigModal repo={clientConfigRepo} onClose={() => setClientConfigRepo(null)} />
      )}
      {syncLogRepo && (
        <SyncLogModal repo={syncLogRepo} onClose={() => setSyncLogRepo(null)} />
      )}
      {rhsmSettingsRepo && (
        <RhsmSettingsModal
          repo={rhsmSettingsRepo}
          onClose={() => setRhsmSettingsRepo(null)}
          onSaved={() => { setRhsmSettingsRepo(null); loadRepos(); showToast('RHSM ayarları kaydedildi') }}
        />
      )}
    </div>
  )
}

export default Repositories
