import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface LogEntry {
  id: number
  server_id: number | null
  server_name: string | null
  event_type: string
  severity: string
  source: string | null
  title: string
  description: string | null
  created_at: string | null
}

const Log: React.FC = () => {
  const [page, setPage] = useState(0)
  const limit = 50

  const { data, isLoading } = useQuery<{ total: number; events: LogEntry[] }>({
    queryKey: ['log', page],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('limit', String(limit))
      params.set('offset', String(page * limit))
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    refetchInterval: 30000
  })

  const events = data?.events ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / limit)

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-6">İşlem Günlüğü</h2>
      <p className="text-slate-400 text-sm mb-6">
        Sistemdeki işlemler (sync, kurulum, event vb.) kronolojik sırayla listelenir.
      </p>

      <div className="bg-cyber-card rounded-[10px] border border-white/[0.06] overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mx-auto"></div>
            <p className="text-slate-400 mt-4">Yükleniyor...</p>
          </div>
        ) : events.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            //
            <p>Henüz kayıt yok</p>
            <p className="text-sm mt-2">VM sync, envanter sync veya diğer işlemler burada görünecek</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.06] bg-cyber-deep/60">
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">Tarih</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">Tip</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">Başlık</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">Sunucu</th>
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">Durum</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id} className="border-b border-white/[0.04] hover:bg-white/[0.03]">
                      <td className="py-3 px-4 text-slate-300 font-mono text-xs">
                        {e.created_at ? new Date(e.created_at).toLocaleString('tr-TR') : '-'}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded bg-slate-600 text-slate-300 text-xs">
                          {e.event_type}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-white">{e.title}</td>
                      <td className="py-3 px-4 text-slate-400">{e.server_name || '-'}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          e.severity === 'critical' ? 'bg-red-500/20 text-red-400' :
                          e.severity === 'warning' ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-green-500/20 text-green-400'
                        }`}>
                          {e.severity}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.06]">
                <span className="text-slate-500 text-sm">{total.toLocaleString('tr-TR')} kayıt</span>
                <div className="flex gap-2">
                  <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                    className="px-3 py-1 rounded bg-slate-700 text-slate-300 disabled:opacity-50 text-sm">Önceki</button>
                  <span className="px-3 py-1 text-slate-400 text-sm">{page + 1} / {totalPages}</span>
                  <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                    className="px-3 py-1 rounded bg-slate-700 text-slate-300 disabled:opacity-50 text-sm">Sonraki</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default Log
