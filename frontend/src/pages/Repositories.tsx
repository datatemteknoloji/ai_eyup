import React, { useState, useEffect, useCallback } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

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
const dateLoc = (locale: string) => locale === 'en' ? 'en-GB' : 'tr-TR'
const fmtDate = (s: string | null, locale: string) => s ? new Date(s).toLocaleString(dateLoc(locale)) : '—'
const fmtSize = (mb: number) => mb > 1024 ? `${(mb/1024).toFixed(1)} GB` : `${mb} MB`
const fmtPkg  = (n: number, locale: string) => n.toLocaleString(dateLoc(locale))

const SYNC_COLOR: Record<string, string> = {
  never:     'text-slate-400',
  syncing:   'text-blue-400 animate-pulse',
  synced:    'text-green-400',
  failed:    'text-red-400',
  partial:   'text-orange-400',
  cancelled: 'text-yellow-400',
}
const SYNC_KEYS: Record<string, TranslationKey> = {
  never:     'repo_sync_never',
  syncing:   'repo_syncing',
  synced:    'repo_sync_ok',
  failed:    'repo_sync_fail',
  partial:   'repo_sync_partial',
  cancelled: 'repo_sync_cancelled',
}

const TYPE_BADGE: Record<string, string> = {
  rhel:   'bg-red-500/20 text-red-300 border-red-500/40',
  oel:    'bg-red-700/20 text-orange-300 border-orange-500/40',
  rocky:  'bg-green-500/20 text-green-300 border-green-500/40',
  alma:   'bg-blue-500/20 text-blue-300 border-blue-500/40',
  centos: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
  custom: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
}

const TYPE_ICON: Record<string, string> = {
  rhel:   'RH',
  oel:    'OE',
  rocky:  'RK',
  ubuntu: 'UB',
  custom: 'CS',
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
  <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
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
  const t = useT()
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
    if (selectedChannels.size === 0) { setError(t('repo_pick_channel')); return }
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
      if (!r.ok) throw new Error((await r.json()).detail || t('error_generic'))
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
      setError(t('repo_custom_required')); return
    }
    setSaving(true); setError('')
    try {
      const r = await fetch(API, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(customForm),
      })
      if (!r.ok) throw new Error((await r.json()).detail || t('error_generic'))
      onCreated(1)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <h2 className="text-lg font-semibold text-white">{t('repo_add')}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl leading-none">×</button>
        </div>

        {/* Mode tabs */}
        <div className="px-6 pt-4 flex gap-2">
          <button onClick={() => setMode('product')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === 'product' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-white/[0.06]'}`}>
            {t('repo_pick_product')}
          </button>
          <button onClick={() => setMode('custom')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === 'custom' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:bg-white/[0.06]'}`}>
            {t('repo_custom_url')}
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
                      <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-2">{t('repo_rpm_based')}</div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                        {rpm.map(p => (
                          <button
                            key={p.product}
                            onClick={() => selectProduct(p)}
                            className={`text-left p-3 rounded-xl border transition-all ${
                              selectedProduct?.product === p.product
                                ? 'border-blue-500 bg-blue-600/15'
                                : 'border-slate-600 bg-white/[0.07]/30 hover:border-slate-500 hover:bg-white/[0.06]/50'
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <span className="text-xl">{TYPE_ICON[p.icon] || TYPE_ICON[p.repo_type] || 'PKG'}</span>
                              <div>
                                <div className="text-sm font-semibold text-white leading-tight">{p.product}</div>
                                <div className="text-xs text-slate-400 mt-0.5">{p.arch}</div>
                              </div>
                            </div>
                            {p.auth_type !== 'none' && (
                              <div className="mt-1.5 text-xs text-orange-400">{t('repo_auth_needed')}</div>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* APT (Debian/Ubuntu) */}
                    {apt.length > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 font-medium uppercase tracking-wide mb-2">{t('repo_apt_based')}</div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {apt.map(p => (
                            <button
                              key={p.product}
                              onClick={() => selectProduct(p)}
                              className={`text-left p-3 rounded-xl border transition-all ${
                                selectedProduct?.product === p.product
                                  ? 'border-blue-500 bg-blue-600/15'
                                  : 'border-slate-600 bg-white/[0.07]/30 hover:border-slate-500 hover:bg-white/[0.06]/50'
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-xl">{TYPE_ICON[p.repo_type] || 'PKG'}</span>
                                <div>
                                  <div className="text-sm font-semibold text-white leading-tight">{p.product}</div>
                                  <div className="text-xs text-slate-400 mt-0.5">{p.arch}</div>
                                </div>
                              </div>
                              <div className="mt-1.5 text-xs text-blue-400">{t('repo_catalog_only')}</div>
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
                <div className="space-y-4 pt-2 border-t border-white/[0.06]">

                  {/* Version selector */}
                  <div>
                    <label className="text-xs text-slate-400 block mb-2">
                      {t('repo_version')}
                      {selectedProduct.repo_type === 'rhel' || selectedProduct.repo_type === 'rocky' || selectedProduct.repo_type === 'alma' ? (
                        <span className="ml-2 text-slate-500">{t('repo_match_minor')}</span>
                      ) : selectedProduct.url_versioned === false ? (
                        <span className="ml-2 text-yellow-400">{t('repo_url_fixed')}</span>
                      ) : null}
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {selectedProduct.version_options.map(v => (
                        <button
                          key={v.value}
                          onClick={() => setSelectedVersion(v.value)}
                          className={`px-3 py-1.5 text-sm rounded-lg border transition-all font-medium ${
                            selectedVersion === v.value
                              ? 'bg-blue-600 border-blue-500 text-white'
                              : 'border-slate-600 text-slate-300 hover:border-slate-500 hover:bg-white/[0.06]'
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
                        <div className="mt-2 bg-cyber-deep/60 border border-white/[0.06] rounded-lg px-3 py-2 text-xs font-mono space-y-1">
                          <div><span className="text-slate-500">slug: </span><span className="text-blue-300">{slug}</span></div>
                          <div className="text-slate-400 truncate">{url}</div>
                        </div>
                      )
                    })()}
                  </div>

                  <div>
                    <div className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                      <span>{TYPE_ICON[selectedProduct.repo_type] || 'PKG'}</span>
                      {selectedProduct.product} {selectedVersion !== 'latest' ? selectedVersion : ''} — {t('repo_channels')}
                      <span className="text-xs text-slate-400 font-normal ml-1">
                        {t('repo_n_selected', { n: selectedChannels.size })}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {selectedProduct.channels.map(ch => (
                        <label
                          key={ch.key}
                          className={`flex items-center gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-all ${
                            selectedChannels.has(ch.key)
                              ? 'border-blue-500 bg-blue-600/15'
                              : 'border-slate-600 bg-white/[0.07]/30 hover:border-slate-500'
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
                  <div className="bg-white/[0.04] border border-slate-600 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm font-semibold text-white">{t('repo_snapshot_label')}</div>
                        <div className="text-xs text-slate-400 mt-0.5">{t('repo_snapshot_hint')}</div>
                      </div>
                    </div>

                    {/* Mode seçici */}
                    <div className="flex gap-2 flex-wrap">
                      {([
                        { key: 'date',    label: t('repo_daily'),  example: today.toISOString().slice(0,10) },
                        { key: 'monthly', label: t('repo_monthly'),   example: `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}` },
                        { key: 'custom',  label: t('repo_custom'),    example: '' },
                        { key: 'none',    label: t('repo_no_label'), example: '' },
                      ] as const).map(m => (
                        <button
                          key={m.key}
                          onClick={() => applySnapshotMode(m.key)}
                          className={`px-3 py-1.5 text-xs rounded-lg border transition-all font-medium ${
                            snapshotMode === m.key
                              ? 'bg-blue-600 border-blue-500 text-white'
                              : 'border-slate-600 text-slate-300 hover:border-slate-500 hover:bg-white/[0.06]'
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
                          className="flex-1 bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
                        />
                        {snapshotLabel && (
                          <div className="text-xs text-slate-400 whitespace-nowrap">
                            {t('repo_example')} <span className="text-blue-300 font-mono">oel-9-9_5-baseos-{snapshotLabel}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {snapshotMode === 'none' && (
                      <div className="text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2">
                        {t('repo_no_label_warn')}
                      </div>
                    )}
                  </div>

                  {/* Ubuntu/apt uyarısı */}
                  {selectedProduct.format_note === 'apt' && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-3 text-xs text-yellow-300 space-y-1">
                      <div className="font-semibold">{t('repo_apt_format')}</div>
                      <div>{t('repo_apt_note')}</div>
                    </div>
                  )}

                  {/* Credentials (RHEL / kimlik gereken repolar) */}
                  {selectedProduct.auth_type !== 'none' && (
                    <div className="bg-orange-500/10 border border-orange-500/30 rounded-xl p-4 space-y-3">
                      <p className="text-xs text-orange-300">
                        {t('repo_rh_needed', { product: selectedProduct.product })}
                      </p>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-xs text-slate-400 block mb-1">{t('repo_rh_user')}</label>
                          <input
                            value={credentials.username}
                            onChange={e => setCredentials(p => ({...p, username: e.target.value}))}
                            placeholder="kullanici@example.com"
                            className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                          />
                        </div>
                        <div>
                          <label className="text-xs text-slate-400 block mb-1">{t('repo_password')}</label>
                          <input
                            type="password"
                            value={credentials.password}
                            onChange={e => setCredentials(p => ({...p, password: e.target.value}))}
                            className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
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
                      ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{t('repo_adding')}</>
                      : t('repo_add_n_ch', { n: selectedChannels.size })
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
                  <label className="text-xs text-slate-400 block mb-1">{t('repo_slug')}</label>
                  <input value={customForm.name}
                    onChange={e => setCustomForm(p => ({...p, name: e.target.value.toLowerCase().replace(/\s+/g,'-')}))}
                    placeholder="custom-repo" className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('repo_display_name')}</label>
                  <input value={customForm.display_name}
                    onChange={e => setCustomForm(p => ({...p, display_name: e.target.value}))}
                    placeholder="Custom Repo" className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">{t('repo_base_url')}</label>
                <input value={customForm.base_url}
                  onChange={e => setCustomForm(p => ({...p, base_url: e.target.value}))}
                  placeholder="https://..." className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('col_type')}</label>
                  <select value={customForm.repo_type} onChange={e => setCustomForm(p => ({...p, repo_type: e.target.value}))}
                    className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
                    {['oel','rhel','rocky','alma','centos','custom'].map(t => (
                      <option key={t} value={t}>{t.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('repo_os_ver')}</label>
                  <input value={customForm.os_version} onChange={e => setCustomForm(p => ({...p, os_version: e.target.value}))}
                    placeholder="9" className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label className="text-xs text-slate-400 block mb-1">{t('repo_auth')}</label>
                  <select value={customForm.auth_type} onChange={e => setCustomForm(p => ({...p, auth_type: e.target.value}))}
                    className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
                    <option value="none">{t('none')}</option>
                    <option value="basic">Basic</option>
                    <option value="ssl_cert">{t('repo_ssl_cert')}</option>
                  </select>
                </div>
              </div>
              {customForm.auth_type === 'basic' && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">{t('repo_user')}</label>
                    <input value={customForm.username} onChange={e => setCustomForm(p => ({...p, username: e.target.value}))}
                      className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">{t('repo_password')}</label>
                    <input type="password" value={customForm.password} onChange={e => setCustomForm(p => ({...p, password: e.target.value}))}
                      className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                </div>
              )}
              {error && <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{error}</div>}
              <button onClick={saveCustom} disabled={saving}
                className="w-full py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-40 flex items-center justify-center gap-2">
                {saving ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{t('saving')}</> : t('add')}
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
  const t = useT()
  const { locale } = useLocale()
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
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-white">{repo.display_name}</h2>
            <p className="text-xs text-slate-400">{t('repo_n_pkgs', { n: total.toLocaleString(dateLoc(locale)) })}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        {/* Filters */}
        <div className="px-6 py-3 border-b border-white/[0.06] flex flex-wrap gap-3 flex-shrink-0">
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(0) }}
            placeholder={t('repo_search_pkg')} className="flex-1 min-w-[180px] bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
          <input value={arch} onChange={e => { setArch(e.target.value); setPage(0) }}
            placeholder={t('repo_arch_ph')} className="w-32 bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
          <select value={downloaded} onChange={e => { setDownloaded(e.target.value as any); setPage(0) }}
            className="bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500">
            <option value="all">{t('filter_all')}</option>
            <option value="yes">{t('repo_downloaded')}</option>
            <option value="no">{t('repo_not_downloaded')}</option>
          </select>
        </div>

        {/* Package list */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : packages.length === 0 ? (
            <div className="text-center py-12 text-slate-500">{t('repo_no_pkgs')}</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-white/[0.07]/50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium">{t('repo_pkg_col')}</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium">{t('repo_ver_col')}</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-20">Arch</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-24">{t('repo_size_col')}</th>
                  <th className="text-left px-4 py-2 text-xs text-slate-400 font-medium w-24">{t('col_status')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.05]/30">
                {packages.map(p => (
                  <tr key={p.id} className="hover:bg-white/[0.03] transition-colors">
                    <td className="px-4 py-2">
                      <div className="font-medium text-white">{p.name}</div>
                      <div className="text-xs text-slate-400 truncate max-w-xs">{p.summary}</div>
                    </td>
                    <td className="px-4 py-2 text-slate-300 font-mono text-xs">{fmtEvr(p)}</td>
                    <td className="px-4 py-2 text-slate-400 text-xs">{p.arch}</td>
                    <td className="px-4 py-2 text-slate-400 text-xs">{p.size_bytes > 0 ? (p.size_bytes/1024/1024).toFixed(1)+' MB' : '—'}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${p.downloaded ? 'text-green-300 bg-green-500/10 border-green-500/30' : 'text-slate-400 bg-white/[0.07]/50 border-slate-600'}`}>
                        {p.downloaded ? t('repo_local') : t('repo_metadata')}
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
          <div className="px-6 py-3 border-t border-white/[0.06] flex items-center justify-between flex-shrink-0">
            <span className="text-xs text-slate-400">{t('repo_page_range', { a: page * limit + 1, b: Math.min((page+1)*limit, total), total })}</span>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p-1))} disabled={page === 0}
                className="px-3 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-white rounded-lg disabled:opacity-40">{t('page_prev')}</button>
              <button onClick={() => setPage(p => p+1)} disabled={(page+1)*limit >= total}
                className="px-3 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-white rounded-lg disabled:opacity-40">{t('page_next')}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Client Config Modal ──────────────────────────────────────────────────────
const ClientConfigModal: React.FC<{ repo: RepoSource; onClose: () => void }> = ({ repo, onClose }) => {
  const t = useT()
  const [serverIp, setServerIp] = useState('')
  const [port, setPort] = useState('8000')
  const [repoContent, setRepoContent] = useState('')
  const [servers, setServers] = useState<any[]>([])
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [pushing, setPushing] = useState(false)
  const [pushResults, setPushResults] = useState<Record<string, any>>({})

  useEffect(() => {
    import('../api/servers').then(({ fetchServersForPicker }) =>
      fetchServersForPicker({ page_size: 200, maxPages: 2 })
        .then(setServers)
        .catch(() => {})
    )
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
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <h2 className="text-lg font-semibold text-white">{t('repo_client_cfg', { name: repo.display_name })}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="p-6 space-y-5">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-3 text-xs text-blue-300">
            {t('repo_client_hint', { path: `/etc/yum.repos.d/${repo.name}.repo` })}
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-slate-400 block mb-1">{t('repo_mgmt_ip')}</label>
              <input value={serverIp} onChange={e => setServerIp(e.target.value)}
                placeholder="192.168.1.100" className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <div className="w-24">
              <label className="text-xs text-slate-400 block mb-1">{t('repo_port')}</label>
              <input value={port} onChange={e => setPort(e.target.value)}
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <div className="flex items-end">
              <button onClick={generateConfig}
                className="px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white text-sm rounded-lg transition-colors">
                {t('repo_generate')}
              </button>
            </div>
          </div>

          {repoContent && (
            <>
              <div>
                <label className="text-xs text-slate-400 block mb-1">{t('repo_file_content')}</label>
                <pre className="bg-cyber-deep text-green-300 text-xs p-4 rounded-xl font-mono whitespace-pre overflow-x-auto border border-white/[0.06]">{repoContent}</pre>
                <button
                  onClick={() => navigator.clipboard.writeText(repoContent)}
                  className="mt-2 text-xs text-blue-400 hover:text-blue-300"
                >
                  {t('repo_copy')}
                </button>
              </div>

              <div>
                <label className="text-xs text-slate-400 block mb-2">{t('repo_push_ssh')}</label>
                <div className="max-h-40 overflow-y-auto border border-white/[0.06] rounded-xl divide-y divide-white/[0.04]">
                  {servers.map((srv: any) => (
                    <label key={srv.id} className={`flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-white/[0.03] ${selectedServers.includes(srv.id) ? 'bg-blue-600/10' : ''}`}>
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
                  {pushing ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{t('repo_pushing')}</> : t('repo_push_n', { n: selectedServers.length })}
                </button>

                {Object.keys(pushResults).length > 0 && (
                  <div className="mt-3 space-y-1">
                    {Object.entries(pushResults).map(([sid, res]: [string, any]) => (
                      <div key={sid} className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg ${res.status === 'success' ? 'bg-green-500/10 text-green-300' : 'bg-red-500/10 text-red-300'}`}>
                        <span>{res.status === 'success' ? <CheckCircle2 size={13} strokeWidth={2} /> : <XCircle size={13} strokeWidth={2} />}</span>
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
  const t = useT()
  const { locale } = useLocale()
  const [jobs, setJobs] = useState<SyncJob[]>([])
  const [selectedJob, setSelectedJob] = useState<SyncJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [liveProgress, setLiveProgress] = useState<any>(null)
  const logRef = React.useRef<HTMLPreElement>(null)

  const load = useCallback(async () => {
    const r = await fetch(`${API}/${repo.id}/jobs`)
    if (r.ok) setJobs(await r.json())
    setLoading(false)
  }, [repo.id])

  // Canlı ilerleme ve log için progress endpoint'i poll et
  const loadProgress = useCallback(async () => {
    const r = await fetch(`${API}/${repo.id}/progress`)
    if (r.ok) setLiveProgress(await r.json())
  }, [repo.id])

  useEffect(() => { load() }, [load])

  // Auto-refresh: job listesi + canlı progress
  useEffect(() => {
    const hasRunning = jobs.some(j => j.status === 'running' || j.status === 'pending')
    if (!hasRunning) return
    loadProgress()
    const t = setInterval(() => { load(); loadProgress() }, 2000)
    return () => clearInterval(t)
  }, [jobs, load, loadProgress])

  // Seçili job'ı güncelle
  useEffect(() => {
    if (!selectedJob) return
    const updated = jobs.find(j => j.id === selectedJob.id)
    if (updated) setSelectedJob(updated)
  }, [jobs, selectedJob])

  // Log sonuna scroll et
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [selectedJob?.log])

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] flex-shrink-0">
          <h2 className="text-lg font-semibold text-white">{t('repo_sync_history', { name: repo.display_name })}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="flex-1 overflow-hidden flex gap-0">
          {/* Job list */}
          <div className="w-72 border-r border-white/[0.06] overflow-y-auto flex-shrink-0">
            {loading ? (
              <div className="p-6 text-center"><div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" /></div>
            ) : jobs.length === 0 ? (
              <div className="p-6 text-center text-slate-500 text-sm">{t('repo_never_synced')}</div>
            ) : (
              jobs.map(j => (
                <button key={j.id} onClick={() => setSelectedJob(j)}
                  className={`w-full text-left px-4 py-3 hover:bg-white/[0.03] transition-colors border-b border-white/[0.04] ${selectedJob?.id === j.id ? 'bg-blue-600/10' : ''}`}>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${JOB_STATUS_COLOR[j.status]}`}>{j.status}</span>
                    {(j.status === 'running' || j.status === 'pending') && <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />}
                  </div>
                  <div className="text-xs text-slate-400 mt-1">{fmtDate(j.started_at ?? j.created_at ?? null, locale)}</div>
                  <div className="text-xs text-slate-500 mt-0.5">{t('repo_n_pkgs_short', { a: j.synced_packages, b: j.total_packages })}</div>
                </button>
              ))
            )}
          </div>

          {/* Job detail */}
          <div className="flex-1 overflow-y-auto p-5">
            {selectedJob ? (
              <div className="space-y-4">
                {/* Stat kartları */}
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div className="bg-white/[0.07]/50 rounded-lg p-3 text-center">
                    <div className="text-slate-400 mb-0.5">{t('total')}</div>
                    <div className="text-white font-bold text-base">
                      {(liveProgress?.total_packages || selectedJob.total_packages || 0).toLocaleString(dateLoc(locale))}
                    </div>
                  </div>
                  <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 text-center">
                    <div className="text-slate-400 mb-0.5">{t('repo_on_disk')}</div>
                    <div className="text-green-300 font-bold text-base">
                      {(liveProgress?.rpm_on_disk || selectedJob.synced_packages || 0).toLocaleString(dateLoc(locale))}
                    </div>
                  </div>
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 text-center">
                    <div className="text-slate-400 mb-0.5">{t('repo_size')}</div>
                    <div className="text-blue-300 font-bold text-base">
                      {liveProgress?.disk_mb
                        ? liveProgress.disk_mb >= 1024
                          ? `${(liveProgress.disk_mb/1024).toFixed(1)} GB`
                          : `${liveProgress.disk_mb} MB`
                        : '—'}
                    </div>
                  </div>
                  <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 text-center">
                    <div className="text-slate-400 mb-0.5">{t('repo_failed_n')}</div>
                    <div className="text-red-300 font-bold text-base">{selectedJob.failed_packages || 0}</div>
                  </div>
                </div>

                {/* İlerleme çubuğu */}
                {(selectedJob.status === 'running' || selectedJob.status === 'pending') && (
                  <div>
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />
                        {t('repo_sync_running')}
                      </span>
                      <span>
                        {(() => {
                          const done  = liveProgress?.rpm_on_disk || selectedJob.synced_packages || 0
                          const total = liveProgress?.total_packages || selectedJob.total_packages || 0
                          return total > 0 ? `${Math.round(done*100/total)}%` : '...'
                        })()}
                      </span>
                    </div>
                    <div className="bg-white/[0.07] rounded-full h-2.5">
                      <div className="bg-blue-500 h-2.5 rounded-full transition-all duration-500"
                        style={{
                          width: (() => {
                            const done  = liveProgress?.rpm_on_disk || selectedJob.synced_packages || 0
                            const total = liveProgress?.total_packages || selectedJob.total_packages || 1
                            return `${Math.min(100, Math.round(done*100/total))}%`
                          })()
                        }} />
                    </div>
                  </div>
                )}

                {/* Canlı log */}
                <div>
                  <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
                    <span>{t('upd_job_log')}</span>
                    {(selectedJob.status === 'running' || selectedJob.status === 'pending') && (
                      <span className="flex items-center gap-1 text-green-400">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                        {t('repo_live')}
                      </span>
                    )}
                  </div>
                  {selectedJob.log ? (
                    <pre ref={logRef}
                      className="bg-cyber-deep border border-white/[0.06] rounded-xl p-4 text-xs text-green-300 font-mono whitespace-pre-wrap max-h-96 overflow-y-auto leading-relaxed">
                      {selectedJob.log}
                    </pre>
                  ) : (selectedJob.status === 'running' || selectedJob.status === 'pending') ? (
                    <div className="bg-cyber-deep border border-white/[0.06] rounded-xl p-4 flex items-center gap-3">
                      <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                      <div>
                        <div className="text-xs text-blue-300">{t('repo_sync_starting')}</div>
                        <div className="text-xs text-slate-500 mt-0.5">{t('repo_log_soon')}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="bg-cyber-deep border border-white/[0.06] rounded-xl p-4 text-xs text-slate-500 text-center italic">
                      {t('repo_no_log')}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-3">
                {jobs.some(j => j.status === 'running' || j.status === 'pending') ? (
                  <div className="text-center">
                    <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                    <div className="text-sm text-slate-300">{t('repo_sync_running_short')}</div>
                    <div className="text-xs text-slate-500 mt-1">{t('repo_pick_job_left')}</div>
                  </div>
                ) : (
                  <div className="text-slate-500 text-sm">{t('repo_pick_job')}</div>
                )}
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
  const t = useT()
  const [form, setForm] = useState({
    rhsm_repo_id:         repo.rhsm_repo_id || '',
    mirror_host:          repo.mirror_host || '127.0.0.1',
    mirror_port:          String(repo.mirror_port || 22),
    mirror_username:      repo.mirror_username || 'root',
    mirror_password:      '',
    mirror_download_path: repo.mirror_download_path || '/app/repos',
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
      if (!r.ok) throw new Error((await r.json()).detail || t('error_generic'))
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
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div>
            <h2 className="text-lg font-semibold text-white">{t('repo_rhsm_title')}</h2>
            <p className="text-xs text-slate-400 mt-0.5">{repo.display_name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>

        <div className="p-6 space-y-5">
          {/* Açıklama */}
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4 text-xs text-blue-300 space-y-1.5">
            <div className="font-semibold text-sm">{t('repo_rhsm_sub')}</div>
            <div>{t('repo_rhsm_hint')}</div>
            <div>{t('repo_rhsm_hint2')}</div>
          </div>

          {/* RHSM Repo ID */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">
              {t('repo_rhsm_id')} <span className="text-slate-500">{t('repo_rhsm_id_hint')}</span>
            </label>
            <input
              value={form.rhsm_repo_id}
              onChange={e => setForm(p => ({...p, rhsm_repo_id: e.target.value}))}
              placeholder="rhel-9-for-x86_64-baseos-rpms"
              className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Mirror Host */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="text-xs text-slate-400 block mb-1">{t('repo_mirror_host')}</label>
              <input
                value={form.mirror_host}
                onChange={e => setForm(p => ({...p, mirror_host: e.target.value}))}
                placeholder="127.0.0.1"
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">{t('repo_port')}</label>
              <input
                value={form.mirror_port}
                onChange={e => setForm(p => ({...p, mirror_port: e.target.value}))}
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">{t('repo_ssh_user')}</label>
              <input
                value={form.mirror_username}
                onChange={e => setForm(p => ({...p, mirror_username: e.target.value}))}
                placeholder="root"
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">{t('pkg_ssh_password')}</label>
              <input
                type="password"
                value={form.mirror_password}
                onChange={e => setForm(p => ({...p, mirror_password: e.target.value}))}
                placeholder={t('repo_ssh_pass_ph')}
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-400 block mb-1">
              {t('repo_download_dir')}
              <span className="text-slate-500 ml-1">{t('repo_download_dir_hint')}</span>
            </label>
            <input
              value={form.mirror_download_path}
              onChange={e => setForm(p => ({...p, mirror_download_path: e.target.value}))}
              placeholder="/app/repos"
              className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Test butonları */}
          <div className="flex gap-2 flex-wrap">
            <button onClick={testConnection} disabled={testing}
              className="px-4 py-2 text-sm bg-white/[0.07] hover:bg-slate-600 text-white rounded-lg transition-colors disabled:opacity-40">
              {testing ? '...' : t('repo_test_conn')}
            </button>
            <button onClick={listRepos} disabled={testing}
              className="px-4 py-2 text-sm bg-white/[0.07] hover:bg-slate-600 text-white rounded-lg transition-colors disabled:opacity-40">
              {testing ? '...' : t('repo_list_repos')}
            </button>
          </div>

          {/* Test sonucu */}
          {testResult && (
            <div className="bg-cyber-deep border border-white/[0.06] rounded-xl p-4 text-xs font-mono">
              {'repos' in testResult ? (
                <div className="space-y-1 max-h-52 overflow-y-auto">
                  <div className="text-slate-400 mb-2">{t('repo_n_found', { n: testResult.total })}</div>
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
                    <span className="inline-flex items-center gap-1.5">
                      {testResult.registered ? <CheckCircle2 size={14} strokeWidth={2} /> : <XCircle size={14} strokeWidth={2} />}
                      {testResult.registered ? t('repo_sub_active') : t('repo_not_registered')}
                    </span>
                  </div>
                  <pre className="text-slate-300 whitespace-pre-wrap">{testResult.status}</pre>
                </div>
              )}
            </div>
          )}

          {error && <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{error}</div>}

          <button onClick={save} disabled={saving}
            className="w-full py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 text-white transition-all disabled:opacity-40 flex items-center justify-center gap-2">
            {saving ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{t('saving')}</> : t('save')}
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
  const t = useT()
  const { locale } = useLocale()
  const syncing = repo.sync_status === 'syncing'

  return (
    <tr className="border-b border-white/[0.06] hover:bg-cyber-card/60 transition-colors group">
      {/* Dağıtım + ad */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="text-lg flex-shrink-0">{TYPE_ICON[repo.repo_type] || 'PKG'}</span>
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
                    {progress.rpm_on_disk.toLocaleString(dateLoc(locale))} / {progress.total_packages.toLocaleString(dateLoc(locale))} RPM
                  </span>
                  <span className="text-slate-400">
                    {Math.round(progress.rpm_on_disk * 100 / progress.total_packages)}%
                  </span>
                </div>
                <div className="w-full bg-white/[0.07] rounded-full h-1.5">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(Math.round(progress.rpm_on_disk * 100 / progress.total_packages), 100)}%` }}
                  />
                </div>
                <div className="text-xs text-slate-400">{t('repo_downloaded_size', { size: progress.disk_mb >= 1024 ? `${(progress.disk_mb/1024).toFixed(1)} GB` : `${progress.disk_mb} MB` })}</div>
              </>
            ) : (
              <span className="text-xs text-blue-400 flex items-center gap-1 animate-pulse">
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />
                {t('repo_meta_fetch')}
              </span>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className={`text-xs font-medium flex items-center gap-1 ${SYNC_COLOR[repo.sync_status] || 'text-slate-400'}`}>
              {SYNC_KEYS[repo.sync_status] ? t(SYNC_KEYS[repo.sync_status]) : repo.sync_status}
            </span>
            {repo.last_sync && (
              <span className="text-xs text-slate-500">{fmtDate(repo.last_sync, locale)}</span>
            )}
          </div>
        )}
      </td>

      {/* Paket / Boyut */}
      <td className="px-3 py-3 whitespace-nowrap text-center">
        <div className="text-sm font-medium text-white">{fmtPkg(repo.package_count, locale)}</div>
        <div className="text-xs text-slate-500">{repo.total_size_mb > 0 ? fmtSize(repo.total_size_mb) : '—'}</div>
      </td>

      {/* Auth / Sertifika */}
      <td className="px-3 py-3 whitespace-nowrap">
        {repo.repo_type === 'rhel' ? (
          repo.has_ssl_cert ? (
            <span className="text-xs text-green-400 flex items-center gap-1">{t('repo_certified')}</span>
          ) : (
            <button onClick={() => onFetchCerts(repo.id)}
              className="text-xs text-orange-300 bg-orange-500/10 border border-orange-500/30 px-2 py-1 rounded-lg hover:bg-orange-500/20 transition-colors whitespace-nowrap">
              {t('repo_get_cert')}
            </button>
          )
        ) : (
          <span className="text-xs text-green-400">{t('repo_open')}</span>
        )}
      </td>

      {/* İşlemler */}
      <td className="px-3 py-3">
        <div className="flex items-center gap-1 flex-wrap">

          {/* Sync / {t('stop')} */}
          {syncing ? (
            <button onClick={() => onCancel(repo.id)}
              className="px-2.5 py-1 text-xs font-semibold bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-red-300 rounded-full animate-pulse flex-shrink-0" />
              {t('stop')}
            </button>
          ) : repo.sync_method === 'rhsm' ? (
            <button onClick={() => onSyncRhsm(repo.id)}
              className="px-2.5 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded-lg transition-colors">
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
            className="px-2.5 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors">
            Log
          </button>

          {/* {t('repo_pkgs')} */}
          <button onClick={() => onPackages(repo)} disabled={repo.package_count === 0}
            className="px-2.5 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors disabled:opacity-30">
            {t('repo_pkgs')}
          </button>

          {/* .repo */}
          <button onClick={() => onConfig(repo)}
            className="px-2.5 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors">
            .repo
          </button>

          {/* RHSM ayarları */}
          {repo.repo_type === 'rhel' && (
            <button onClick={() => onRhsmSettings(repo)}
              className="px-2.5 py-1 text-xs bg-blue-900/50 hover:bg-blue-800/60 text-blue-300 border border-blue-700/40 rounded-lg transition-colors">
              RHSM
            </button>
          )}

          {/* Sil */}
          <button onClick={() => onDelete(repo.id)}
            className="px-2.5 py-1 text-xs text-red-400 hover:text-white hover:bg-red-700 rounded-lg transition-colors">
            {t('delete')}
          </button>

        </div>
      </td>
    </tr>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const Repositories: React.FC = () => {
  const t = useT()
  const { locale } = useLocale()
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
    if (r.ok) { showToast(metaOnly ? t('repo_meta_started') : t('repo_full_started')); await loadRepos() }
    else showToast((await r.json()).detail || t('error_generic'), 'err')
  }

  const handleCancel = async (repoId: number) => {
    const r = await fetch(`${API}/${repoId}/cancel-sync`, { method: 'POST' })
    if (r.ok) { showToast(t('repo_sync_stopped')); await loadRepos() }
    else showToast((await r.json()).detail || t('error_generic'), 'err')
  }

  const handleSyncRhsm = async (repoId: number) => {
    const r = await fetch(`${API}/${repoId}/sync-rhsm`, { method: 'POST' })
    if (r.ok) { showToast(t('repo_rhsm_started')); await loadRepos() }
    else showToast((await r.json()).detail || t('error_generic'), 'err')
  }

  const handleFetchCerts = async (repoId: number) => {
    showToast(t('repo_rhsm_wait'))
    try {
      const r = await fetch(`${API}/${repoId}/fetch-rhsm-certs`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || t('error_generic'))
      showToast(`✓ ${d.message}`)
      await loadRepos()
    } catch (e: any) {
      showToast(e.message || t('repo_rhsm_cert_fail'), 'err')
    }
  }

  const handleDelete = async (repoId: number) => {
    const repo = repos.find(r => r.id === repoId)
    const isSyncing = repo?.sync_status === 'syncing'
    const msg = isSyncing
      ? t('repo_del_syncing')
      : t('repo_del_confirm')
    if (!confirm(msg)) return
    const url = isSyncing ? `${API}/${repoId}?force=true` : `${API}/${repoId}`
    const r = await fetch(url, { method: 'DELETE' })
    if (r.ok) { showToast(t('repo_deleted')); await loadRepos() }
    else showToast((await r.json()).detail || t('repo_del_fail'), 'err')
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
          <h1 className="text-2xl font-bold text-white">{t('repo_title')}</h1>
          <p className="text-slate-400 text-sm mt-1">{t('repo_subtitle')}</p>
        </div>
        <button onClick={() => setShowAdd(true)}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
          {t('repo_add')}
        </button>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium ${
          toast.type === 'ok' ? 'bg-green-900/90 border-green-500/50 text-green-300' : 'bg-red-900/90 border-red-500/50 text-red-300'
        }`}>
          <span className="inline-flex items-center gap-1.5">
            {toast.type === 'ok' ? <CheckCircle2 size={14} strokeWidth={2} /> : <XCircle size={14} strokeWidth={2} />}
            {toast.msg}
          </span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label={t('repo_stat_total')}
          value={String(aggStats?.total_repos ?? repos.length)}
          sub={t('repo_n_current', { n: aggStats?.synced_repos ?? syncedCount })}
        />
        <StatCard
          label={t('repo_local_rpm')}
          value={aggStats ? fmtPkg(aggStats.total_rpm, locale) : fmtPkg(totalPackages, locale)}
          sub={aggStats ? t('repo_on_disk_sub') : t('repo_all_repos')}
        />
        <StatCard
          label={t('repo_disk_use')}
          value={aggStats
            ? (aggStats.disk_gb >= 1 ? `${aggStats.disk_gb.toFixed(1)} GB` : `${aggStats.disk_mb} MB`)
            : fmtSize(totalSize)
          }
          sub={t('repo_local_store')}
        />
        <StatCard
          label={t('repo_sync_status')}
          value={
            aggStats?.syncing_repos > 0
              ? t('repo_n_active', { n: aggStats.syncing_repos })
              : (syncingCount > 0 ? t('repo_n_active', { n: syncingCount }) : t('repo_idle'))
          }
          sub={
            aggStats && aggStats.active_total_packages > 0
              ? t('repo_n_of_pkgs', { a: fmtPkg(aggStats.active_synced_packages, locale), b: fmtPkg(aggStats.active_total_packages, locale) })
              : (syncingCount > 0 ? t('repo_in_progress') : t('repo_all_ready'))
          }
        /></div>

      {/* Repo list */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : repos.length === 0 ? (
        <div className="bg-cyber-card border border-white/[0.06] rounded-2xl p-16 text-center">
          <div className="text-3xl font-bold text-blue-400 mb-4">PKG</div>
          <h3 className="text-lg font-semibold text-white">{t('repo_empty')}</h3>
          <p className="text-slate-400 text-sm mt-2">{t('repo_empty_hint')}</p>
          <button onClick={() => setShowAdd(true)}
            className="mt-4 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
            {t('repo_add_first')}
          </button>
        </div>
      ) : (
        <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-white/[0.05] border-b border-slate-600">
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('repo_col_repo')}</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('col_type')}</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('col_status')}</th>
                <th className="text-center px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('repo_col_pkg_size')}</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('repo_auth')}</th>
                <th className="text-left px-3 py-3 text-xs font-semibold text-slate-300 uppercase tracking-wide">{t('actions')}</th>
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
          onCreated={(count) => { setShowAdd(false); loadRepos(); showToast(t('repo_n_added', { n: count })) }} />
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
          onSaved={() => { setRhsmSettingsRepo(null); loadRepos(); showToast(t('repo_rhsm_saved')) }}
        />
      )}
    </div>
  )
}

export default Repositories
