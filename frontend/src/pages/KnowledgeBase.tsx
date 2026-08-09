import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Fact {
  id: number
  server_id: number
  server_name: string
  server_ip: string | null
  category: string
  key: string
  value: string
  source: string
  first_learned_at: string | null
  last_confirmed_at: string | null
  times_confirmed: number
  confidence: number
}

interface SummaryServer {
  server_id: number
  server_name: string
  server_ip: string | null
  fact_count: number
}

interface SummaryCategory {
  category: string
  count: number
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CATEGORY_LABEL: Record<string, string> = {
  kernel: 'Çekirdek', sysctl: 'Sysctl', os: 'İşletim Sistemi', cpu: 'CPU',
  hardware: 'Donanım', disk: 'Disk / Mount', memory: 'Bellek', network: 'Ağ',
  security: 'Güvenlik', packages: 'Paketler', apps: 'Uygulama Sürümleri',
  limits: 'Sistem Limitleri', ssl: 'SSL', cron: 'Cron',
  chat_discovery: 'Sohbet Keşfi', correction: 'Düzeltme',
  virt_os: 'Virt OS', virt_power: 'Virt Güç', virt_tools: 'Virt Tools',
  virt_storage: 'Virt Depolama', virt_cluster: 'Virt Cluster',
  virt_cpu: 'Virt CPU', virt_memory: 'Virt RAM', virt_network: 'Virt Ağ',
}

const SOURCE_LABEL: Record<string, { label: string; color: string }> = {
  ssh: { label: 'SSH', color: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/25' },
  winrm: { label: 'WinRM', color: 'text-blue-300 bg-blue-500/10 border-blue-500/25' },
  manual: { label: 'Manuel', color: 'text-amber-300 bg-amber-500/10 border-amber-500/25' },
  virt_sync: { label: 'Virt Sync', color: 'text-sky-300 bg-sky-500/10 border-sky-500/25' },
  chat_tool: { label: 'Chat Tool', color: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/25' },
}

function fmt(dt: string | null) {
  if (!dt) return '—'
  try {
    return new Date(dt).toLocaleString('tr-TR')
  } catch {
    return dt
  }
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const KnowledgeBase: React.FC = () => {
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const [serverId, setServerId] = useState<number | ''>('')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<Fact | null>(null)
  const [editValue, setEditValue] = useState('')
  const [pinServerId, setPinServerId] = useState<number | ''>('')
  const [pinKey, setPinKey] = useState('')
  const [pinValue, setPinValue] = useState('')
  const [pinHint, setPinHint] = useState('')
  const limit = 100
  const qc = useQueryClient()

  const { data: summary } = useQuery<{ total_facts: number; servers: SummaryServer[]; categories: SummaryCategory[] }>({
    queryKey: ['knowledge-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/knowledge/summary`)
      return r.ok ? r.json() : { total_facts: 0, servers: [], categories: [] }
    },
    refetchInterval: 30000,
  })

  const { data, isFetching, refetch } = useQuery<{ total: number; facts: Fact[] }>({
    queryKey: ['knowledge-facts', serverId, category, q, offset],
    queryFn: async () => {
      const p = new URLSearchParams()
      if (serverId) p.set('server_id', String(serverId))
      if (category) p.set('category', category)
      if (q) p.set('q', q)
      p.set('limit', String(limit))
      p.set('offset', String(offset))
      const r = await fetch(`${API_BASE_URL}/knowledge/?${p}`)
      if (!r.ok) return { total: 0, facts: [] }
      return r.json()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/knowledge/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-facts'] })
      qc.invalidateQueries({ queryKey: ['knowledge-summary'] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: async ({ id, value }: { id: number; value: string }) => {
      await fetch(`${API_BASE_URL}/knowledge/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
    },
    onSuccess: () => {
      setEditing(null)
      qc.invalidateQueries({ queryKey: ['knowledge-facts'] })
    },
  })

  const confirmMutation = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/knowledge/${id}/confirm`, { method: 'POST' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-facts'] })
      qc.invalidateQueries({ queryKey: ['knowledge-summary'] })
    },
  })

  const pinMutation = useMutation({
    mutationFn: async () => {
      if (pinServerId === '' || !pinKey.trim() || !pinValue.trim()) {
        throw new Error('Sunucu, anahtar ve değer gerekli')
      }
      const r = await fetch(`${API_BASE_URL}/knowledge/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_id: Number(pinServerId),
          key: pinKey.trim(),
          value: pinValue.trim(),
          category: 'correction',
        }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(typeof err?.detail === 'string' ? err.detail : 'Kaydedilemedi')
      }
      return r.json()
    },
    onSuccess: () => {
      setPinKey('')
      setPinValue('')
      setPinHint('Sabitlendi — RAG yeniden indekslenecek')
      qc.invalidateQueries({ queryKey: ['knowledge-facts'] })
      qc.invalidateQueries({ queryKey: ['knowledge-summary'] })
    },
    onError: (e: Error) => setPinHint(e.message || 'Kaydedilemedi'),
  })

  const clearServerMutation = useMutation({
    mutationFn: async (sid: number) => {
      await fetch(`${API_BASE_URL}/knowledge/server/${sid}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['knowledge-facts'] })
      qc.invalidateQueries({ queryKey: ['knowledge-summary'] })
    },
  })

  const { data: allServers } = useQuery<{ id: number; name: string }[]>({
    queryKey: ['knowledge-pin-servers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?page=1&page_size=200`)
      if (!r.ok) return []
      const data = await r.json()
      const items = data?.items || data?.servers || data || []
      if (!Array.isArray(items)) return []
      return items.map((s: any) => ({ id: s.id, name: s.name || `#${s.id}` }))
    },
    staleTime: 60_000,
  })

  const pinServerChoices = (() => {
    if (allServers?.length) return allServers.map((s) => ({ server_id: s.id, server_name: s.name }))
    return (summary?.servers || []).map((s) => ({ server_id: s.server_id, server_name: s.server_name }))
  })()

  const rows = data?.facts || []
  const total = data?.total || 0

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-white">Bilgi Bankası</h1>
        <p className="text-sm text-slate-400 mt-1">
          AI&apos;nin SSH/WinRM ve hypervisor envanter sync&apos;inden öğrendiği kalıcı yapısal bilgiler.
          Yanlış kayıtları Düzenle ile düzeltin (manuel kaynak) veya Onayla ile güçlendirin.
          Anlık metrikler (CPU/RAM %) burada tutulmaz.
        </p>
      </div>

      {/* Özet */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{summary.total_facts}</div>
            <div className="text-xs text-slate-400 mt-0.5">Toplam öğrenilmiş bilgi</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{summary.servers.length}</div>
            <div className="text-xs text-slate-400 mt-0.5">Bilgi öğrenilen sunucu</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4 col-span-2">
            <div className="text-xs text-slate-400 mb-1.5">Kategori dağılımı</div>
            <div className="flex flex-wrap gap-1.5">
              {summary.categories.slice(0, 8).map(c => (
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
            </div>
          </div>
        </div>
      )}

      {/* Yeni bilgi sabitle — yalnızca admin */}
      {isAdmin ? (
      <div className="bg-cyber-card border border-amber-500/20 rounded-[10px] p-3 space-y-2">
        <div className="text-sm text-slate-200 font-medium">Gerçeği sabitle</div>
        <p className="text-xs text-slate-500">
          Yalnızca admin — kalıcı manuel düzeltme (source=manual, RAG reindex). Canlı SSH ile çelişirse canlı veri esas alınır.
        </p>
        <div className="flex flex-wrap gap-2 items-center">
          <select
            value={pinServerId}
            onChange={(e) => setPinServerId(e.target.value ? Number(e.target.value) : '')}
            className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 min-w-[160px]"
          >
            <option value="">Sunucu seçin</option>
            {pinServerChoices.map((s) => (
              <option key={s.server_id} value={s.server_id}>
                {s.server_name}
              </option>
            ))}
          </select>
          <input
            value={pinKey}
            onChange={(e) => setPinKey(e.target.value)}
            placeholder="Anahtar"
            maxLength={200}
            className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 min-w-[140px]"
          />
          <input
            value={pinValue}
            onChange={(e) => setPinValue(e.target.value)}
            placeholder="Doğru değer"
            maxLength={2000}
            className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[160px]"
          />
          <button
            type="button"
            disabled={pinMutation.isPending || pinServerId === '' || !pinKey.trim() || !pinValue.trim()}
            onClick={() => {
              setPinHint('')
              pinMutation.mutate()
            }}
            className="px-3 py-1.5 text-sm bg-amber-600/90 hover:bg-amber-500 text-white rounded-lg disabled:opacity-50"
          >
            {pinMutation.isPending ? '…' : 'Sabitle'}
          </button>
          {pinHint && <span className="text-xs text-slate-400">{pinHint}</span>}
        </div>
      </div>
      ) : (
        <p className="text-xs text-slate-500">
          Manuel bilgi sabitleme / düzenleme yalnızca yöneticilere açıktır. Onayla ve silme knowledge yetkisiyle yapılabilir.
        </p>
      )}

      {/* Filtreler */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-3 flex flex-wrap gap-2 items-center">
        <select value={serverId} onChange={e => { setOffset(0); setServerId(e.target.value ? Number(e.target.value) : '') }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 min-w-[160px]">
          <option value="">Tüm sunucular</option>
          {summary?.servers.map(s => (
            <option key={s.server_id} value={s.server_id}>{s.server_name} ({s.fact_count})</option>
          ))}
        </select>
        <select value={category} onChange={e => { setOffset(0); setCategory(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm kategoriler</option>
          {summary?.categories.map(c => (
            <option key={c.category} value={c.category}>{CATEGORY_LABEL[c.category] || c.category}</option>
          ))}
        </select>
        <input value={q} onChange={e => { setOffset(0); setQ(e.target.value) }}
          placeholder="Anahtar/değerde ara..."
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[160px]" />
        <button onClick={() => refetch()} disabled={isFetching}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50">
          {isFetching ? '...' : '↺ Yenile'}
        </button>
        {serverId !== '' && (
          <button
            onClick={() => {
              if (confirm('Bu sunucuya ait tüm öğrenilmiş bilgiler silinsin mi? (bir sonraki taramada yeniden öğrenilir)')) {
                clearServerMutation.mutate(Number(serverId))
              }
            }}
            className="px-3 py-1.5 text-sm bg-red-600/80 hover:bg-red-500 text-white rounded-lg"
          >
            Sunucunun bilgisini temizle
          </button>
        )}
      </div>

      {/* Tablo */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-cyber-deep/60 text-slate-400 text-xs">
              <tr>
                <th className="text-left px-3 py-2.5 font-medium">Sunucu</th>
                <th className="text-left px-3 py-2.5 font-medium">Kategori</th>
                <th className="text-left px-3 py-2.5 font-medium">Anahtar</th>
                <th className="text-left px-3 py-2.5 font-medium">Değer</th>
                <th className="text-left px-3 py-2.5 font-medium">Kaynak</th>
                <th className="text-left px-3 py-2.5 font-medium">Son doğrulama</th>
                <th className="text-left px-3 py-2.5 font-medium">Kez</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {rows.map(f => {
                const src = SOURCE_LABEL[f.source] || { label: f.source, color: 'text-slate-300 bg-white/[0.05] border-white/[0.1]' }
                return (
                  <tr key={f.id} className="hover:bg-white/[0.03]">
                    <td className="px-3 py-2 text-slate-200 whitespace-nowrap text-xs">{f.server_name}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs text-slate-300">{CATEGORY_LABEL[f.category] || f.category}</td>
                    <td className="px-3 py-2 text-slate-400 font-mono text-[11px] whitespace-nowrap">{f.key}</td>
                    <td className="px-3 py-2 text-slate-300 text-xs max-w-md truncate" title={f.value}>
                      {editing?.id === f.id ? (
                        <div className="flex gap-1.5">
                          <input
                            value={editValue}
                            onChange={e => setEditValue(e.target.value)}
                            className="bg-cyber-deep border border-white/[0.15] rounded px-1.5 py-0.5 text-xs text-white flex-1"
                            autoFocus
                          />
                          <button
                            onClick={() => updateMutation.mutate({ id: f.id, value: editValue })}
                            className="text-green-400 hover:text-green-300 text-xs">✓</button>
                          <button onClick={() => setEditing(null)} className="text-slate-500 hover:text-slate-300 text-xs">✕</button>
                        </div>
                      ) : f.value}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded-md text-[10px] border ${src.color}`}>{src.label}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap text-xs">{fmt(f.last_confirmed_at)}</td>
                    <td className="px-3 py-2 text-slate-500 text-xs text-center">{f.times_confirmed}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {editing?.id !== f.id && (
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={() => confirmMutation.mutate(f.id)}
                            className="text-slate-500 hover:text-emerald-300 text-xs">Onayla</button>
                          {isAdmin && (
                            <button
                              onClick={() => { setEditing(f); setEditValue(f.value) }}
                              className="text-slate-500 hover:text-blue-300 text-xs">Düzenle</button>
                          )}
                          <button
                            onClick={() => { if (confirm('Bu bilgi silinsin mi?')) deleteMutation.mutate(f.id) }}
                            className="text-slate-500 hover:text-red-300 text-xs">Sil</button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
              {!isFetching && rows.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-500">
                  Henüz öğrenilmiş bilgi yok — sohbet üzerinden SSH/WinRM ile bir sunucu sorgulandığında burada birikmeye başlar.
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

export default KnowledgeBase
