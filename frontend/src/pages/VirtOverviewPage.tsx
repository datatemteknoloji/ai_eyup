import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Cloud, Monitor, Server, Activity } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

/** Sanallaştırma modülü dashboard — envanter yönetimi Entegrasyonlar altında. */
export default function VirtOverviewPage() {
  const { data: hvData } = useQuery({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!r.ok) return []
      return r.json()
    },
  })

  const { data: opsSummary } = useQuery({
    queryKey: ['virt-ops-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ops/summary`)
      if (!r.ok) return null
      return r.json()
    },
    refetchInterval: 60_000,
  })

  const hypervisors = Array.isArray(hvData) ? hvData : []
  const vmCount = opsSummary?.vm_count ?? '—'

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Sanallaştırma Dashboard</h1>
        <p className="text-slate-400 text-sm mt-1">
          VM ve hypervisor operasyon özeti — envanter tanımları{' '}
          <Link to="/integrations/hypervisors" className="text-blue-400 hover:underline">Entegrasyonlar → vCenter/OLVM</Link>
          {' '}altında yönetilir
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { icon: Cloud, label: 'Hypervisor', value: hypervisors.length, color: 'text-blue-400' },
          { icon: Monitor, label: 'VM', value: vmCount, color: 'text-sky-400' },
          { icon: Activity, label: 'Kritik', value: opsSummary?.critical ?? 0, color: 'text-red-400' },
          { icon: Server, label: 'Uyarı', value: opsSummary?.warning ?? 0, color: 'text-amber-400' },
        ].map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <Icon size={18} className={`${color} mb-2`} />
            <div className={`text-2xl font-bold ${color}`}>{value}</div>
            <div className="text-xs text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <Link to="/virt/ops" className="text-xs px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white">Komuta Merkezi</Link>
        <Link to="/infra-reports" className="text-xs px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:text-white">Altyapı Raporları</Link>
        <Link to="/integrations/hypervisors" className="text-xs px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:text-white">Hypervisor Yönetimi</Link>
      </div>
    </div>
  )
}
