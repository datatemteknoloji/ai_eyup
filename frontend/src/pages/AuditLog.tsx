import React, { useEffect, useState, useCallback } from 'react'
import { API_BASE_URL } from '../config/api'

interface AuditRow {
  id: number
  actor_name: string | null
  category: string
  action: string
  target_type: string | null
  target_id: string | null
  server_id: number | null
  status: string
  summary: string | null
  detail: any
  ip_address: string | null
  created_at: string | null
}

const CATEGORY_LABEL: Record<string, string> = {
  auth: 'Kimlik', agent: 'Agent', system_update: 'Sistem Güncelleme',
  ssh: 'SSH', rca: 'RCA', snapshot: 'Snapshot',
}

const STATUS_STYLE: Record<string, string> = {
  success: 'bg-green-500/15 text-green-300 border-green-500/30',
  failure: 'bg-red-500/15 text-red-300 border-red-500/30',
  rejected: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  blocked: 'bg-red-500/15 text-red-300 border-red-500/30',
  pending: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
}

const CAT_STYLE: Record<string, string> = {
  auth: 'text-sky-300', agent: 'text-purple-300', system_update: 'text-blue-300',
  ssh: 'text-emerald-300', rca: 'text-cyan-300', snapshot: 'text-pink-300',
}

const AuditLog: React.FC = () => {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<any>(null)

  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [actor, setActor] = useState('')
  const [q, setQ] = useState('')
  const [days, setDays] = useState('7')
  const [offset, setOffset] = useState(0)
  const limit = 100

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (category) params.set('category', category)
      if (status) params.set('status', status)
      if (actor) params.set('actor', actor)
      if (q) params.set('q', q)
      if (days) params.set('days', days)
      params.set('limit', String(limit))
      params.set('offset', String(offset))
      const r = await fetch(`${API_BASE_URL}/audit/?${params.toString()}`)
      if (r.ok) {
        const d = await r.json()
        setRows(d.logs || [])
        setTotal(d.total || 0)
      }
    } finally {
      setLoading(false)
    }
  }, [category, status, actor, q, days, offset])

  const loadStats = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE_URL}/audit/stats?days=${days || 7}`)
      if (r.ok) setStats(await r.json())
    } catch { /* ignore */ }
  }, [days])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadStats() }, [loadStats])

  const fmt = (s: string | null) => s ? new Date(s).toLocaleString('tr-TR') : '—'

  return (
    <div className="space-y-4">
      {/* İstatistik kartları */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-xs text-slate-400">Toplam kayıt ({stats.days}g)</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <div className="text-2xl font-bold text-green-300">{stats.by_status?.success || 0}</div>
            <div className="text-xs text-slate-400">Başarılı</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <div className="text-2xl font-bold text-red-300">
              {(stats.by_status?.failure || 0) + (stats.by_status?.blocked || 0) + (stats.by_status?.rejected || 0)}
            </div>
            <div className="text-xs text-slate-400">Başarısız / Engellendi / Red</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4">
            <div className="text-sm font-semibold text-white truncate">
              {Object.keys(stats.top_actors || {})[0] || '—'}
            </div>
            <div className="text-xs text-slate-400">En aktif kullanıcı</div>
          </div>
        </div>
      )}

      {/* Filtreler */}
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-3 flex flex-wrap gap-2 items-center">
        <select value={category} onChange={e => { setOffset(0); setCategory(e.target.value) }}
          className="bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm kategoriler</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={status} onChange={e => { setOffset(0); setStatus(e.target.value) }}
          className="bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm durumlar</option>
          <option value="success">Başarılı</option>
          <option value="failure">Başarısız</option>
          <option value="rejected">Reddedildi</option>
          <option value="blocked">Engellendi</option>
        </select>
        <select value={days} onChange={e => { setOffset(0); setDays(e.target.value) }}
          className="bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="1">Son 1 gün</option>
          <option value="7">Son 7 gün</option>
          <option value="30">Son 30 gün</option>
          <option value="">Tümü</option>
        </select>
        <input value={actor} onChange={e => { setOffset(0); setActor(e.target.value) }}
          placeholder="Kullanıcı..."
          className="bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 w-32" />
        <input value={q} onChange={e => { setOffset(0); setQ(e.target.value) }}
          placeholder="Özet ara..."
          className="bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[140px]" />
        <button onClick={() => load()}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg">
          Yenile
        </button>
      </div>

      {/* Tablo */}
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-slate-400 text-xs">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Zaman</th>
                <th className="text-left px-3 py-2 font-medium">Kullanıcı</th>
                <th className="text-left px-3 py-2 font-medium">Kategori</th>
                <th className="text-left px-3 py-2 font-medium">Eylem</th>
                <th className="text-left px-3 py-2 font-medium">Özet</th>
                <th className="text-left px-3 py-2 font-medium">Durum</th>
                <th className="text-left px-3 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {rows.map(r => (
                <tr key={r.id} className="hover:bg-slate-700/20">
                  <td className="px-3 py-2 text-slate-400 whitespace-nowrap text-xs">{fmt(r.created_at)}</td>
                  <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{r.actor_name || '—'}</td>
                  <td className={`px-3 py-2 whitespace-nowrap ${CAT_STYLE[r.category] || 'text-slate-300'}`}>
                    {CATEGORY_LABEL[r.category] || r.category}
                  </td>
                  <td className="px-3 py-2 text-slate-400 font-mono text-xs whitespace-nowrap">{r.action}</td>
                  <td className="px-3 py-2 text-slate-300 max-w-md truncate" title={r.summary || ''}>{r.summary || '—'}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] border ${STATUS_STYLE[r.status] || 'bg-slate-600/20 text-slate-300 border-slate-600/40'}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-500 font-mono text-xs">{r.ip_address || '—'}</td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-500">Kayıt bulunamadı</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Sayfalama */}
        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-700/50 text-xs text-slate-400">
          <span>{total} kayıt · {offset + 1}-{Math.min(offset + limit, total)}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-2.5 py-1 rounded-lg bg-slate-700 disabled:opacity-40 hover:bg-slate-600 text-slate-200">← Önceki</button>
            <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}
              className="px-2.5 py-1 rounded-lg bg-slate-700 disabled:opacity-40 hover:bg-slate-600 text-slate-200">Sonraki →</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AuditLog
