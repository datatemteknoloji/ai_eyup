import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface DiscoveredApp {
  id: number
  server_id: number
  server_name: string
  server_ip: string | null
  name: string
  category: string
  version: string | null
  port: number | null
  process_or_service: string | null
  detection_method: string | null
  evidence: string | null
  status: string
  source: string
  first_detected_at: string | null
  last_seen_at: string | null
  times_confirmed: number
}

interface ByProduct {
  name: string
  category: string
  server_count: number
}

interface ByCategory {
  category: string
  count: number
}

interface Summary {
  total_running: number
  total_installed?: number
  scanned_servers: number
  by_product: ByProduct[]
  by_category: ByCategory[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_LABEL: Record<string, string> = {
  database: 'Veritabanı', webserver: 'Web Sunucusu', appserver: 'Uygulama Sunucusu',
  cache: 'Cache', messaging: 'Mesajlaşma', container_platform: 'Konteyner Platformu',
  other: 'Diğer',
}

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  running: { label: 'Çalışıyor', color: 'text-green-300 bg-green-500/10 border-green-500/25' },
  installed: { label: 'Kurulu', color: 'text-amber-300 bg-amber-500/10 border-amber-500/25' },
  stopped: { label: 'Durdu', color: 'text-slate-400 bg-white/[0.05] border-white/[0.1]' },
}

const METHOD_LABEL: Record<string, string> = {
  process: 'Süreç', service: 'Servis', port: 'Port', package: 'Paket', registry: 'Kayıt',
}

const SOURCE_LABEL: Record<string, string> = { ssh: 'SSH', winrm: 'WinRM', manual: 'Manuel' }

function fmt(dt: string | null) {
  if (!dt) return '—'
  try {
    return new Date(dt).toLocaleString('tr-TR')
  } catch {
    return dt
  }
}

function fmtVersion(v: string | null) {
  if (!v) return '—'
  const s = v.trim()
  if (!s) return '—'
  // Zaten temizlenmiş beklenir; yine de uzun banner kırp
  if (s.length > 48) return s.slice(0, 48) + '…'
  return s
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const Applications: React.FC = () => {
  const [serverId, setServerId] = useState<number | ''>('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('running')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [rescanningId, setRescanningId] = useState<number | null>(null)
  const limit = 100
  const qc = useQueryClient()

  const { data: summary } = useQuery<Summary>({
    queryKey: ['apps-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/applications/summary`)
      return r.ok ? r.json() : { total_running: 0, scanned_servers: 0, by_product: [], by_category: [] }
    },
    refetchInterval: 30000,
  })

  const { data, isFetching, refetch } = useQuery<{ total: number; applications: DiscoveredApp[] }>({
    queryKey: ['apps-list', serverId, category, status, q, offset],
    queryFn: async () => {
      const p = new URLSearchParams()
      if (serverId) p.set('server_id', String(serverId))
      if (category) p.set('category', category)
      if (status) p.set('status', status)
      if (q) p.set('q', q)
      p.set('limit', String(limit))
      p.set('offset', String(offset))
      const r = await fetch(`${API_BASE_URL}/applications/?${p}`)
      if (!r.ok) return { total: 0, applications: [] }
      return r.json()
    },
  })

  const { data: serverOptions } = useQuery<{ id: number; name: string }[]>({
    queryKey: ['apps-server-options'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/`)
      if (!r.ok) return []
      const list = await r.json()
      return (Array.isArray(list) ? list : list?.servers || []).map((s: any) => ({ id: s.id, name: s.name }))
    },
    staleTime: 60000,
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/applications/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apps-list'] })
      qc.invalidateQueries({ queryKey: ['apps-summary'] })
    },
  })

  const clearServerMutation = useMutation({
    mutationFn: async (sid: number) => {
      await fetch(`${API_BASE_URL}/applications/server/${sid}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['apps-list'] })
      qc.invalidateQueries({ queryKey: ['apps-summary'] })
    },
  })

  const rescan = async (sid: number) => {
    setRescanningId(sid)
    try {
      await fetch(`${API_BASE_URL}/applications/servers/${sid}/rescan`, { method: 'POST' })
      await refetch()
      qc.invalidateQueries({ queryKey: ['apps-summary'] })
    } finally {
      setRescanningId(null)
    }
  }

  const rows = data?.applications || []
  const total = data?.total || 0

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-white">Uygulamalar</h1>
        <p className="text-sm text-slate-400 mt-1">
          Sunucularda SSH/WinRM ile tespit edilen gerçek uygulamalar. Yalnızca çalışan süreç/servis
          veya dinleyen port kanıtı varsa &quot;Çalışıyor&quot;; yalnızca paket/registry varsa &quot;Kurulu&quot;.
          Port ve sürüm uydurulmaz — taramada görülmeyen alanlar boş kalır.
        </p>
      </div>

      {/* Özet */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{summary.total_running}</div>
            <div className="text-xs text-slate-400 mt-0.5">Çalışan uygulama</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{summary.total_installed ?? 0}</div>
            <div className="text-xs text-slate-400 mt-0.5">Kurulu (çalışmıyor)</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{summary.scanned_servers}</div>
            <div className="text-xs text-slate-400 mt-0.5">Taranmış sunucu</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-xs text-slate-400 mb-1.5">Kategori (çalışan)</div>
            <div className="flex flex-wrap gap-1.5">
              {summary.by_category.map(c => (
                <button
                  key={c.category}
                  onClick={() => { setOffset(0); setCategory(category === c.category ? '' : c.category) }}
                  className={`px-2 py-0.5 rounded-md text-xs border ${category === c.category
                    ? 'bg-blue-500/20 border-blue-500/40 text-blue-200'
                    : 'bg-white/[0.05] border-white/[0.08] text-slate-300 hover:bg-white/[0.09]'}`}
                >
                  {CATEGORY_LABEL[c.category] || c.category} ({c.count})
                </button>
              ))}
              {summary.by_category.length === 0 && (
                <span className="text-xs text-slate-500">Henüz yok</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* En yaygın ürünler */}
      {summary && summary.by_product.length > 0 && (
        <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
          <div className="text-xs text-slate-400 mb-2">Ürüne göre dağılım (kaç sunucuda çalışıyor)</div>
          <div className="flex flex-wrap gap-2">
            {summary.by_product.slice(0, 20).map(p => (
              <span key={p.name} className="px-2.5 py-1 rounded-md text-xs bg-white/[0.05] border border-white/[0.08] text-slate-200">
                {p.name} <span className="text-slate-500">· {p.server_count} sunucu</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Filtreler */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-3 flex flex-wrap gap-2 items-center">
        <select value={serverId} onChange={e => { setOffset(0); setServerId(e.target.value ? Number(e.target.value) : '') }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 min-w-[160px]">
          <option value="">Tüm sunucular</option>
          {serverOptions?.map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select value={category} onChange={e => { setOffset(0); setCategory(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm kategoriler</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select value={status} onChange={e => { setOffset(0); setStatus(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tümü</option>
          <option value="running">Çalışıyor</option>
          <option value="installed">Kurulu</option>
          <option value="stopped">Durdu</option>
        </select>
        <input value={q} onChange={e => { setOffset(0); setQ(e.target.value) }}
          placeholder="Uygulama/servis adında ara..."
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[160px]" />
        <button onClick={() => refetch()} disabled={isFetching}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50">
          {isFetching ? '...' : '↺ Yenile'}
        </button>
        {serverId !== '' && (
          <>
            <button
              onClick={() => rescan(Number(serverId))}
              disabled={rescanningId === Number(serverId)}
              className="px-3 py-1.5 text-sm bg-emerald-600/80 hover:bg-emerald-500 text-white rounded-lg disabled:opacity-50"
            >
              {rescanningId === Number(serverId) ? 'Taranıyor...' : '⟳ Yeniden Tara'}
            </button>
            <button
              onClick={() => {
                if (confirm('Bu sunucuya ait tüm tespit edilen uygulama kayıtları silinsin mi?')) {
                  clearServerMutation.mutate(Number(serverId))
                }
              }}
              className="px-3 py-1.5 text-sm bg-red-600/80 hover:bg-red-500 text-white rounded-lg"
            >
              Kayıtları temizle
            </button>
          </>
        )}
      </div>

      {/* Tablo */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-cyber-deep/60 text-slate-400 text-xs">
              <tr>
                <th className="text-left px-3 py-2.5 font-medium">Sunucu</th>
                <th className="text-left px-3 py-2.5 font-medium">Uygulama</th>
                <th className="text-left px-3 py-2.5 font-medium">Kategori</th>
                <th className="text-left px-3 py-2.5 font-medium">Sürüm</th>
                <th className="text-left px-3 py-2.5 font-medium">Port</th>
                <th className="text-left px-3 py-2.5 font-medium">Durum</th>
                <th className="text-left px-3 py-2.5 font-medium">Kanıt</th>
                <th className="text-left px-3 py-2.5 font-medium">Kaynak</th>
                <th className="text-left px-3 py-2.5 font-medium">Son görülme</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {rows.map(a => {
                const st = STATUS_LABEL[a.status] || { label: a.status, color: 'text-slate-300 bg-white/[0.05] border-white/[0.1]' }
                return (
                  <tr key={a.id} className="hover:bg-white/[0.03]">
                    <td className="px-3 py-2 text-slate-200 whitespace-nowrap text-xs">{a.server_name}</td>
                    <td className="px-3 py-2 text-slate-200 text-xs font-medium" title={a.evidence || ''}>{a.name}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs text-slate-300">{CATEGORY_LABEL[a.category] || a.category}</td>
                    <td className="px-3 py-2 text-slate-300 font-mono text-[11px] max-w-xs truncate" title={a.version || ''}>
                      {fmtVersion(a.version)}
                    </td>
                    <td className="px-3 py-2 text-slate-400 text-xs">{a.port ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded-md text-[10px] border ${st.color}`}>{st.label}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-500 text-xs" title={a.evidence || ''}>
                      {METHOD_LABEL[a.detection_method || ''] || a.detection_method || '—'}
                    </td>
                    <td className="px-3 py-2 text-slate-500 text-xs">{SOURCE_LABEL[a.source] || a.source}</td>
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap text-xs">{fmt(a.last_seen_at)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => { if (confirm('Bu kayıt silinsin mi?')) deleteMutation.mutate(a.id) }}
                          className="text-slate-500 hover:text-red-300 text-xs">Sil</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
              {!isFetching && rows.length === 0 && (
                <tr><td colSpan={10} className="px-3 py-10 text-center text-slate-500">
                  Henüz tespit edilen uygulama yok — arka plan taraması ilk çalıştığında (veya bir sunucu
                  seçip &quot;Yeniden Tara&quot; dediğinizde) burada birikmeye başlar.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Sayfalama */}
        <div className="flex items-center justify-between px-3 py-2.5 border-t border-white/[0.05] text-xs text-slate-400">
          <span>{total} kayıt{total > 0 ? ` · ${offset + 1}–${Math.min(offset + limit, total)}` : ''}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">← Önceki</button>
            <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">Sonraki →</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Applications
