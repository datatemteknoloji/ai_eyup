import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Server } from 'lucide-react'
import { apiGet, type InfraEngineServerDetail } from './api'
import {
  Card, EmptyNote, ErrorNote, fmtAgo, fmtDateTime, InfraStatusBadge, NoticeBox,
} from './ui'

export default function AutomationEngineServer() {
  const { systemId, ip: ipRaw } = useParams()
  const sid = Number(systemId)
  const ip = decodeURIComponent(ipRaw ?? '')

  const q = useQuery({
    queryKey: ['automic-engine-server', sid, ip],
    queryFn: () => apiGet<InfraEngineServerDetail>(`/infrastructure/engines/${sid}/${encodeURIComponent(ip)}`),
  })
  const d = q.data
  const server = d?.server

  return (
    <div className="space-y-4">
      <Link to={`/automation/infrastructure?system=${sid}`} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ArrowLeft size={13} /> Altyapı
      </Link>

      <div className="flex flex-wrap items-start gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Server size={18} /></div>
          <div className="min-w-0">
            <h1 className="font-mono text-lg font-semibold text-white break-all">{ip}</h1>
            <p className="text-xs text-slate-500">{server?.node ? `${server.node} · ` : ''}{d ? d.system : '…'} · engine sunucusu</p>
          </div>
        </div>
      </div>

      {q.isLoading ? <div className="text-sm text-slate-400">Yükleniyor…</div> : null}
      {q.error ? <ErrorNote error={q.error} /> : null}
      {d && !d.ok && <NoticeBox tone="warning" text={d.error ?? 'Sunucu bulunamadı'} />}
      {d?.note && <NoticeBox tone="info" text={d.note} />}

      {server && (
        <>
          <Card title="Process'ler" hint="Automic MQSRV kaydı (Type≠8): CP/WP/PWP/JWP/JCP/REST. PWP bağlı olan sunucu şu an birincil engine'dir.">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-700/60 text-slate-400">
                  <tr>
                    <th className="px-2 py-2 font-medium">Durum</th>
                    <th className="px-2 py-2 font-medium">Ad</th>
                    <th className="px-2 py-2 font-medium">Tip</th>
                    <th className="px-2 py-2 font-medium">Port</th>
                    <th className="px-2 py-2 font-medium">Bağlantı</th>
                    <th className="px-2 py-2 font-medium">REST</th>
                    <th className="px-2 py-2 font-medium">Son sinyal</th>
                  </tr>
                </thead>
                <tbody>
                  {server.processes.map(p => (
                    <tr key={p.name} className="border-b border-white/[0.04]">
                      <td className="px-2 py-1.5"><InfraStatusBadge status={p.status} label={p.status_label} /></td>
                      <td className="px-2 py-1.5 text-slate-200">
                        {p.name}
                        {p.missing_since && <span className="ml-1.5 text-[11px] text-red-300/80">kayboldu {fmtAgo(p.missing_since)}</span>}
                      </td>
                      <td className="px-2 py-1.5 text-slate-400">{p.process_type}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-400">{p.port ?? '—'}</td>
                      <td className="px-2 py-1.5 text-slate-400">
                        {p.connection_count ?? '—'}{p.is_pwp ? <span className="ml-1 text-green-300">· PWP aktif</span> : null}
                      </td>
                      <td className="px-2 py-1.5 font-mono text-slate-400 break-all">{p.rest_endpoint ?? '—'}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">{fmtAgo(p.last_life_sign)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="PWP geçmişi (30 gün)" hint="Hangi process'in ne zaman birincil (PWP) olduğunu gösteren durum geçmişi — toplama aralığına bağlı örneklenmiştir, saniye hassasiyeti değildir.">
            {d?.pwp_history?.length ? (
              <ul className="space-y-1 text-xs">
                {[...d.pwp_history].reverse().slice(0, 200).map((h, i) => (
                  <li key={i} className="flex items-center gap-2 border-b border-white/[0.04] py-1">
                    <span className="w-40 whitespace-nowrap text-slate-400">{fmtDateTime(h.at, true)}</span>
                    <InfraStatusBadge status={h.status} label={h.status} />
                    <span className="text-slate-300">{h.name}</span>
                  </li>
                ))}
              </ul>
            ) : <EmptyNote>PWP geçmişi yok</EmptyNote>}
          </Card>
        </>
      )}
    </div>
  )
}
