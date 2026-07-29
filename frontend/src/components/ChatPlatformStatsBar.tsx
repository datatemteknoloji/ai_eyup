/**
 * Sanallaştırma QuickStatsBar ile aynı dil: platform doğal dil sohbetlerinde
 * üstte kompakt envanter şeridi.
 */
import { useQuery } from '@tanstack/react-query'
import { Server, Cpu, Zap, Boxes, Shield } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import type { PlatformKey } from '../config/platformAiops'

type Stat = { label: string; value: string | number; icon: React.ReactNode }

function StatsRow({ stats }: { stats: Stat[] }) {
  if (!stats.length) return null
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-slate-800/50 border-b border-slate-700/50 text-xs text-slate-400 overflow-x-auto flex-shrink-0">
      {stats.map(s => (
        <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-slate-500">{s.icon}</span>
          <span className="text-slate-500">{s.label}:</span>
          <span className="text-slate-200 font-medium">{s.value}</span>
        </div>
      ))}
    </div>
  )
}

export function ChatPlatformStatsBar({
  platform,
}: {
  platform: PlatformKey | 'all' | 'windows'
}) {
  const { data: linuxStats } = useQuery({
    queryKey: ['chat-stats', 'linux'],
    enabled: platform === 'linux' || platform === 'exadata',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/ai-ready/list?platform=${platform === 'exadata' ? 'exadata' : 'linux'}`)
      if (!r.ok) return { total: 0, online: 0 }
      const list = await r.json()
      const arr = Array.isArray(list) ? list : []
      return {
        total: arr.length,
        online: arr.filter((s: { status?: string }) => (s.status || '').toUpperCase() === 'ONLINE').length,
      }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: winStats } = useQuery({
    queryKey: ['chat-stats', 'windows'],
    enabled: platform === 'windows',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/ai-ready/list?platform=windows`)
      if (!r.ok) return { total: 0, online: 0 }
      const list = await r.json()
      const arr = Array.isArray(list) ? list : []
      return {
        total: arr.length,
        online: arr.filter((s: { status?: string }) => (s.status || '').toUpperCase() === 'ONLINE').length,
      }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: ocpStats } = useQuery({
    queryKey: ['chat-stats', 'openshift'],
    enabled: platform === 'openshift',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/ops/summary`)
      if (!r.ok) return null
      return r.json() as Promise<{
        critical?: number
        warning?: number
        total?: number
        open_incidents?: number
      }>
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: allStats } = useQuery({
    queryKey: ['chat-stats', 'all'],
    enabled: platform === 'all',
    queryFn: async () => {
      const [linux, win] = await Promise.all([
        fetch(`${API_BASE_URL}/servers/ai-ready/list?platform=linux`).then(r => r.ok ? r.json() : []),
        fetch(`${API_BASE_URL}/servers/ai-ready/list?platform=windows`).then(r => r.ok ? r.json() : []),
      ])
      return {
        linux: Array.isArray(linux) ? linux.length : 0,
        windows: Array.isArray(win) ? win.length : 0,
      }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (platform === 'linux' || platform === 'exadata') {
    if (!linuxStats) return null
    return (
      <StatsRow
        stats={[
          { icon: <Server size={14} />, label: platform === 'exadata' ? 'Exadata node' : 'AI Ready', value: linuxStats.total },
          { icon: <Zap size={14} />, label: 'Online', value: linuxStats.online },
        ]}
      />
    )
  }

  if (platform === 'windows') {
    if (!winStats) return null
    return (
      <StatsRow
        stats={[
          { icon: <Shield size={14} />, label: 'AI Ready', value: winStats.total },
          { icon: <Zap size={14} />, label: 'Online', value: winStats.online },
        ]}
      />
    )
  }

  if (platform === 'openshift') {
    if (!ocpStats) return null
    return (
      <StatsRow
        stats={[
          { icon: <Boxes size={14} />, label: 'Olay', value: ocpStats.total ?? ((ocpStats.critical ?? 0) + (ocpStats.warning ?? 0)) },
          { icon: <Cpu size={14} />, label: 'Kritik', value: ocpStats.critical ?? 0 },
          { icon: <Zap size={14} />, label: 'Uyarı', value: ocpStats.warning ?? 0 },
        ]}
      />
    )
  }

  if (platform === 'all' && allStats) {
    return (
      <StatsRow
        stats={[
          { icon: <Server size={14} />, label: 'Linux AI Ready', value: allStats.linux },
          { icon: <Shield size={14} />, label: 'Windows AI Ready', value: allStats.windows },
        ]}
      />
    )
  }

  return null
}
