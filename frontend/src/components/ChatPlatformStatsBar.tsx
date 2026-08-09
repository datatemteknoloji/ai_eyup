/**
 * Sanallaştırma QuickStatsBar ile aynı dil: platform doğal dil sohbetlerinde
 * üstte kompakt envanter şeridi.
 */
import { useQuery } from '@tanstack/react-query'
import { Server, Cpu, Zap, Boxes, Shield } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { fetchServersSummary } from '../api/servers'
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
  const summaryPlatform =
    platform === 'all' || platform === 'windows'
      ? null
      : (platform as 'linux' | 'virt' | 'exadata' | 'openshift')

  const { data: platStats } = useQuery({
    queryKey: ['chat-stats', 'platform', platform],
    enabled: summaryPlatform === 'linux' || summaryPlatform === 'exadata' || summaryPlatform === 'virt',
    queryFn: async () => {
      const s = await fetchServersSummary(summaryPlatform === 'virt' ? 'virt' : summaryPlatform === 'exadata' ? 'exadata' : 'linux')
      return { total: s.total, online: s.online, ai_ready: s.ai_ready }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: winStats } = useQuery({
    queryKey: ['chat-stats', 'windows'],
    enabled: platform === 'windows' || platform === 'all',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/windows/servers/summary`)
      if (!r.ok) return { total: 0, online: 0, ai_ready: 0 }
      const s = await r.json()
      return { total: s.total || 0, online: s.online || 0, ai_ready: s.ai_ready || 0 }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: allStats } = useQuery({
    queryKey: ['chat-stats', 'all'],
    enabled: platform === 'all',
    queryFn: async () => {
      const [linux, win] = await Promise.all([
        fetchServersSummary('linux'),
        fetch(`${API_BASE_URL}/windows/servers/summary`).then(r => r.ok ? r.json() : { total: 0, online: 0, ai_ready: 0 }),
      ])
      return {
        total: (linux.total || 0) + (win.total || 0),
        online: (linux.online || 0) + (win.online || 0),
        ai_ready: (linux.ai_ready || 0) + (win.ai_ready || 0),
      }
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  if (platform === 'openshift') return null

  if (platform === 'linux' || platform === 'exadata' || platform === 'virt') {
    const s = platStats
    if (!s) return null
    return (
      <StatsRow
        stats={[
          { label: platform === 'virt' ? 'VM' : 'Envanter', value: s.total, icon: <Server size={12} /> },
          { label: 'Online', value: s.online, icon: <Zap size={12} /> },
          { label: 'AI Ready', value: s.ai_ready, icon: <Cpu size={12} /> },
        ]}
      />
    )
  }

  if (platform === 'windows') {
    const s = winStats
    if (!s) return null
    return (
      <StatsRow
        stats={[
          { label: 'Windows', value: s.total, icon: <Boxes size={12} /> },
          { label: 'Online', value: s.online, icon: <Zap size={12} /> },
          { label: 'AI Ready', value: s.ai_ready, icon: <Shield size={12} /> },
        ]}
      />
    )
  }

  const s = allStats
  if (!s) return null
  return (
    <StatsRow
      stats={[
        { label: 'Toplam', value: s.total, icon: <Server size={12} /> },
        { label: 'Online', value: s.online, icon: <Zap size={12} /> },
        { label: 'AI Ready', value: s.ai_ready, icon: <Cpu size={12} /> },
      ]}
    />
  )
}
