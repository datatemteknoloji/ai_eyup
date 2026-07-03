/**
 * Baseline Manager — Sunucu başına alarm bastırma kuralları.
 *
 * Sekmeler:
 *   1. Tekrarlayan Alarmlar  — hangi metrikler kronik, "Bastır" butonu
 *   2. Aktif Kurallar        — mevcut suppression kuralları listesi
 */
import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import {
  NEON, PageHeader, GhostButton, PrimaryButton, Section, EmptyState, Select,
} from '../components/aiops/ui'
import type { PlatformAiopsProps } from '../utils/platformApi'

// ── Tipler ───────────────────────────────────────────────────────────────────

interface Server { id: number; name: string; hostname?: string; os_type?: string }

interface RecurrenceMetric {
  metric: string
  recurrence_days: number
  total_count: number
  max_severity: string
  is_chronic: boolean
  is_very_chronic: boolean
  has_suppression: boolean
}

interface SuppressionRule {
  id: number
  server_id: number | null
  metric_name: string
  scope: string
  reason: string | null
  baseline_severity: string | null
  baseline_value: number | null
  active: boolean
  created_at: string | null
  expires_at: string | null
}

// ── Yardımcı bileşenler ───────────────────────────────────────────────────────

const SEV_COLOR: Record<string, string> = {
  critical: NEON.red,
  warning: NEON.orange,
  info: NEON.cyan,
}

function SevBadge({ severity }: { severity: string }) {
  const color = SEV_COLOR[severity] ?? 'rgba(148,163,184,0.5)'
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase"
      style={{ background: `color-mix(in srgb, ${color} 12%, transparent)`, color, border: `1px solid color-mix(in srgb, ${color} 20%, transparent)` }}>
      {severity}
    </span>
  )
}

function ChronicBadge({ days }: { days: number }) {
  const color = days >= 7 ? NEON.red : days >= 3 ? NEON.orange : 'rgba(148,163,184,0.4)'
  const label = days >= 7 ? `${days}g kronik` : days >= 3 ? `${days}g tekrar` : `${days}g`
  return (
    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
      style={{ background: `color-mix(in srgb, ${color} 10%, transparent)`, color, border: `1px solid color-mix(in srgb, ${color} 18%, transparent)` }}>
      {label}
    </span>
  )
}

// ── Suppression oluşturma modali ──────────────────────────────────────────────

function SuppressModal({
  metric,
  serverId,
  serverName,
  onClose,
  onSuccess,
}: {
  metric: string
  serverId: number
  serverName: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [cap, setCap] = useState<string>('suppress')  // 'suppress' | 'warning' | 'info'
  const [reason, setReason] = useState('')
  const [expireDays, setExpireDays] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API_BASE_URL}/baseline/suppressions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_id: serverId,
          metric_name: metric,
          reason: reason || `${serverName} için normal davranış`,
          baseline_severity: cap === 'suppress' ? null : cap,
          scope: 'server',
          expires_in_days: expireDays ? parseInt(expireDays) : null,
        }),
      })
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        setError(e.detail); return
      }
      onSuccess()
      onClose()
    } catch (e: any) {
      setError(e.message)
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)' }} onClick={onClose}>
      <div className="w-full max-w-md rounded-[12px] p-6 space-y-4"
        style={{ background: 'rgb(15,23,42)', border: '1px solid rgba(6,182,212,0.2)' }}
        onClick={e => e.stopPropagation()}>
        <div>
          <h3 className="text-base font-semibold" style={{ color: NEON.cyan }}>Alarm Bastırma Kuralı</h3>
          <p className="text-xs mt-1" style={{ color: 'rgba(148,163,184,0.6)' }}>
            <span style={{ color: NEON.orange }}>{serverName}</span> sunucusu için{' '}
            <code className="px-1 rounded text-[11px]" style={{ background: 'rgba(0,0,0,0.3)' }}>{metric}</code>{' '}
            metriğine kural ekle
          </p>
        </div>

        {/* Kural tipi */}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'rgba(148,163,184,0.55)' }}>
            Uygulama
          </div>
          <div className="space-y-2">
            {[
              { value: 'suppress', label: 'Tamamen bastır', desc: 'Bu metrik için hiç alarm oluşturma' },
              { value: 'warning', label: 'Maksimum Warning', desc: 'Critical yerine Warning olarak oluştur' },
              { value: 'info', label: 'Maksimum Info', desc: 'Her zaman info seviyesinde oluştur' },
            ].map(opt => (
              <button key={opt.value} onClick={() => setCap(opt.value)}
                className="w-full text-left p-3 rounded-[8px] transition-colors"
                style={{
                  background: cap === opt.value ? 'rgba(6,182,212,0.08)' : 'rgba(255,255,255,0.02)',
                  border: `1px solid ${cap === opt.value ? 'rgba(6,182,212,0.25)' : 'rgba(255,255,255,0.06)'}`,
                }}>
                <div className="text-sm font-medium" style={{ color: cap === opt.value ? NEON.cyan : 'rgba(226,232,240,0.7)' }}>{opt.label}</div>
                <div className="text-[11px] mt-0.5" style={{ color: 'rgba(148,163,184,0.45)' }}>{opt.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Sebep */}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: 'rgba(148,163,184,0.55)' }}>Sebep (opsiyonel)</div>
          <input value={reason} onChange={e => setReason(e.target.value)}
            className="w-full text-sm px-3 py-2 rounded-[6px] outline-none"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(226,232,240,0.9)' }}
            placeholder="Örn: Bu sunucu yüklü bir Oracle DB sunucusu" />
        </div>

        {/* Süre */}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-1.5" style={{ color: 'rgba(148,163,184,0.55)' }}>Süre (opsiyonel)</div>
          <Select value={expireDays} onChange={setExpireDays}>
            <option value="">Süresiz</option>
            <option value="7">7 gün</option>
            <option value="30">30 gün</option>
            <option value="90">90 gün</option>
          </Select>
        </div>

        {error && (
          <div className="text-xs p-2 rounded" style={{ background: 'rgba(239,68,68,0.07)', color: NEON.red }}>{error}</div>
        )}

        <div className="flex gap-2 pt-1">
          <GhostButton accent={NEON.cyan} onClick={onClose}>İptal</GhostButton>
          <PrimaryButton accent={NEON.cyan} onClick={submit} disabled={loading}>
            {loading ? 'Kaydediliyor...' : 'Kuralı Kaydet'}
          </PrimaryButton>
        </div>
      </div>
    </div>
  )
}

// ── Ana bileşen ───────────────────────────────────────────────────────────────

type Tab = 'recurrence' | 'rules'

const BaselineManager: React.FC<PlatformAiopsProps> = ({ platform = 'linux' }) => {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<Tab>('recurrence')
  const [selectedServer, setSelectedServer] = useState('')
  const [modalMetric, setModalMetric] = useState<{ metric: string; serverId: number; serverName: string } | null>(null)

  // Sunucu listesi
  const { data: serversData } = useQuery({
    queryKey: ['servers-list'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?limit=100`)
      return r.json()
    },
  })
  const serversRaw: Server[] = serversData?.servers ?? serversData ?? []
  const servers = serversRaw.filter(s => {
    const os = (s.os_type || '').toLowerCase()
    if (platform === 'windows') return os.includes('windows')
    if (platform === 'virt') return false
    return !os.includes('windows')
  })

  // Tekrarlayan metrikler
  const { data: recurrenceData, isLoading: recLoading } = useQuery({
    queryKey: ['baseline-recurrence', selectedServer],
    queryFn: async () => {
      if (!selectedServer) return null
      const r = await fetch(`${API_BASE_URL}/baseline/recurrence/${selectedServer}`)
      return r.json()
    },
    enabled: !!selectedServer,
  })

  // Suppression kuralları
  const { data: rulesData, isLoading: rulesLoading } = useQuery({
    queryKey: ['baseline-rules', selectedServer],
    queryFn: async () => {
      const params = selectedServer ? `?server_id=${selectedServer}` : ''
      const r = await fetch(`${API_BASE_URL}/baseline/suppressions${params}`)
      return r.json() as Promise<SuppressionRule[]>
    },
  })

  const deleteRule = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/baseline/suppressions/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['baseline-rules'] }),
  })

  const metrics: RecurrenceMetric[] = recurrenceData?.metrics ?? []
  const rules: SuppressionRule[] = rulesData ?? []
  const chronicCount = metrics.filter(m => m.is_chronic).length
  const suppressedCount = metrics.filter(m => m.has_suppression).length

  const getServerName = (id: number) => servers.find(s => s.id === id)?.name ?? `Server #${id}`

  return (
    <div className="space-y-6">
      <PageHeader
        title="Baseline Yönetimi"
        subtitle="Sunucu başına normal davranış tanımla — tekrarlayan alarmları bastır veya önceliğini düşür"
      />

      {/* Sunucu seçimi */}
      <Section>
        <div className="p-4 flex flex-wrap items-center gap-3">
          <span className="text-sm" style={{ color: 'rgba(148,163,184,0.6)' }}>Sunucu:</span>
          <Select value={selectedServer} onChange={setSelectedServer}>
            <option value="">Sunucu seçin...</option>
            {servers.map(s => (
              <option key={s.id} value={String(s.id)}>{s.name}</option>
            ))}
          </Select>
          {selectedServer && metrics.length > 0 && (
            <div className="flex gap-4 ml-2 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
              <span>Toplam metrik: <span style={{ color: NEON.cyan }}>{metrics.length}</span></span>
              <span>Kronik: <span style={{ color: NEON.orange }}>{chronicCount}</span></span>
              <span>Bastırılmış: <span style={{ color: NEON.green }}>{suppressedCount}</span></span>
            </div>
          )}
        </div>
      </Section>

      {/* Sekme bar */}
      <div className="flex gap-1 p-1 rounded-[10px]" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {([
          { id: 'recurrence' as Tab, label: 'Tekrarlayan Alarmlar' },
          { id: 'rules' as Tab, label: 'Aktif Kurallar' },
        ]).map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className="flex-1 py-2 px-3 rounded-[8px] text-sm font-medium transition-all"
            style={activeTab === tab.id
              ? { background: 'rgba(6,182,212,0.12)', color: NEON.cyan, border: '1px solid rgba(6,182,212,0.2)' }
              : { color: 'rgba(148,163,184,0.55)', border: '1px solid transparent' }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tekrarlayan Alarmlar */}
      {activeTab === 'recurrence' && (
        <>
          {!selectedServer ? (
            <EmptyState icon="🖥️" text="Tekrarlayan alarmları görmek için bir sunucu seçin." />
          ) : recLoading ? (
            <div className="py-16 flex justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" />
            </div>
          ) : metrics.length === 0 ? (
            <EmptyState icon="✅" text="Bu sunucuda son 14 günde tekrarlayan alarm yok." />
          ) : (
            <div className="space-y-2">
              {metrics.map(m => (
                <div key={m.metric} className="cyber-card p-4 flex items-start gap-3">
                  {/* Kronik göstergesi */}
                  <div className="flex-shrink-0 mt-0.5">
                    <div className="w-2 h-2 rounded-full"
                      style={{
                        background: m.is_very_chronic ? NEON.red : m.is_chronic ? NEON.orange : 'rgba(148,163,184,0.3)',
                        boxShadow: m.is_chronic ? `0 0 6px ${m.is_very_chronic ? NEON.red : NEON.orange}` : 'none',
                      }} />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <ChronicBadge days={m.recurrence_days} />
                      <SevBadge severity={m.max_severity} />
                      {m.has_suppression && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: NEON.green, border: '1px solid rgba(34,197,94,0.2)' }}>
                          ✓ Kural var
                        </span>
                      )}
                    </div>
                    <p className="text-sm font-medium truncate" style={{ color: 'rgba(226,232,240,0.88)' }}>{m.metric}</p>
                    <p className="text-[11px] mt-0.5" style={{ color: 'rgba(148,163,184,0.45)' }}>
                      {m.total_count} olay · son 14 günde {m.recurrence_days} farklı gün
                    </p>
                  </div>

                  {!m.has_suppression && m.is_chronic && (
                    <PrimaryButton
                      accent={NEON.orange}
                      onClick={() => setModalMetric({
                        metric: m.metric,
                        serverId: parseInt(selectedServer),
                        serverName: getServerName(parseInt(selectedServer)),
                      })}>
                      Bu Normal
                    </PrimaryButton>
                  )}
                  {m.has_suppression && (
                    <span className="text-xs px-2 py-1" style={{ color: 'rgba(148,163,184,0.35)' }}>Bastırılıyor</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Aktif Kurallar */}
      {activeTab === 'rules' && (
        <>
          {rulesLoading ? (
            <div className="py-16 flex justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" />
            </div>
          ) : rules.length === 0 ? (
            <EmptyState icon="📋" text="Henüz suppression kuralı yok. Tekrarlayan alarmlar sekmesinden kural ekleyin." />
          ) : (
            <div className="space-y-2">
              {rules.map(rule => (
                <div key={rule.id} className="cyber-card p-4 flex items-start gap-3">
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase"
                        style={{
                          background: rule.baseline_severity === null ? 'rgba(239,68,68,0.1)' : 'rgba(251,191,36,0.1)',
                          color: rule.baseline_severity === null ? NEON.red : NEON.orange,
                          border: `1px solid ${rule.baseline_severity === null ? 'rgba(239,68,68,0.2)' : 'rgba(251,191,36,0.2)'}`,
                        }}>
                        {rule.baseline_severity === null ? 'Tamamen bastır' : `Max: ${rule.baseline_severity}`}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.04)', color: 'rgba(148,163,184,0.5)' }}>
                        {rule.scope}
                      </span>
                      {rule.server_id && (
                        <span className="text-[11px]" style={{ color: NEON.cyan }}>{getServerName(rule.server_id)}</span>
                      )}
                    </div>
                    <p className="text-sm font-medium" style={{ color: 'rgba(226,232,240,0.85)' }}>{rule.metric_name}</p>
                    {rule.reason && (
                      <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{rule.reason}</p>
                    )}
                    <div className="flex gap-3 text-[10px]" style={{ color: 'rgba(148,163,184,0.35)' }}>
                      {rule.created_at && <span>Oluşturuldu: {new Date(rule.created_at).toLocaleDateString('tr-TR')}</span>}
                      {rule.expires_at
                        ? <span style={{ color: NEON.orange }}>Bitiş: {new Date(rule.expires_at).toLocaleDateString('tr-TR')}</span>
                        : <span>Süresiz</span>
                      }
                    </div>
                  </div>
                  <button onClick={() => deleteRule.mutate(rule.id)}
                    className="flex-shrink-0 text-xs px-2 py-1.5 rounded transition-colors"
                    style={{ color: NEON.red, border: '1px solid rgba(239,68,68,0.15)', background: 'rgba(239,68,68,0.05)' }}>
                    Kaldır
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Modal */}
      {modalMetric && (
        <SuppressModal
          {...modalMetric}
          onClose={() => setModalMetric(null)}
          onSuccess={() => {
            qc.invalidateQueries({ queryKey: ['baseline-recurrence'] })
            qc.invalidateQueries({ queryKey: ['baseline-rules'] })
          }}
        />
      )}
    </div>
  )
}

export default BaselineManager
