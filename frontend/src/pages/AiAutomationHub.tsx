import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bot, Server, Shield, Cloud, Layers, Globe, Boxes } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import Chat from './Chat'
import WindowsChat from './WindowsChat'
import UnifiedChat from './UnifiedChat'
import HypervisorChat from './HypervisorChat'

type PlatformId = 'all' | 'linux' | 'windows' | 'virt' | 'exadata' | 'openshift'

const PLATFORM_TABS: {
  id: PlatformId
  label: string
  icon: React.ReactNode
  moduleIds: string[]
}[] = [
  { id: 'all', label: 'Tüm Altyapı', icon: <Globe size={14} />, moduleIds: ['linux', 'windows', 'virtualization', 'executive', 'openshift'] },
  { id: 'linux', label: 'Linux', icon: <Server size={14} />, moduleIds: ['linux'] },
  { id: 'windows', label: 'Windows', icon: <Shield size={14} />, moduleIds: ['windows'] },
  { id: 'virt', label: 'Sanallaştırma', icon: <Cloud size={14} />, moduleIds: ['virtualization'] },
  { id: 'openshift', label: 'OpenShift', icon: <Boxes size={14} />, moduleIds: ['openshift'] },
  { id: 'exadata', label: 'Exadata', icon: <Layers size={14} />, moduleIds: ['exadata'] },
]

export default function AiAutomationHub() {
  const { hasModule } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const platforms = useMemo(
    () => PLATFORM_TABS.filter(tab => tab.moduleIds.some(id => hasModule(id))),
    [hasModule],
  )

  const requested = searchParams.get('platform') as PlatformId | null
  const platform: PlatformId =
    requested && platforms.some(p => p.id === requested)
      ? requested
      : platforms[0]?.id ?? 'linux'

  const setPlatform = (id: PlatformId) => {
    setSearchParams({ platform: id }, { replace: true })
  }

  if (platforms.length === 0) {
    return (
      <div className="p-8 text-center text-slate-400">
        Altyapı analizi için en az bir platform modülüne erişiminiz olmalı.
      </div>
    )
  }

  return (
    <div className="-m-5 flex flex-col h-[calc(100vh-3.5rem)] min-h-0 overflow-hidden bg-slate-900">
      <div className="flex-shrink-0 px-4 py-3 bg-cyber-deep/60 border-b border-white/[0.06]">
        <div className="flex items-center gap-2 mb-3">
          <Bot size={18} className="text-violet-400" />
          <div>
            <h1 className="text-sm font-semibold text-white">AI & Otomasyon — Altyapı Analizi</h1>
            <p className="text-xs text-slate-500">Tüm modüller tek merkezden; platform seçerek analiz yapın</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {platforms.map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setPlatform(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                platform === tab.id
                  ? 'bg-violet-600/30 border border-violet-500/40 text-violet-200'
                  : 'bg-white/[0.04] border border-white/[0.06] text-slate-400 hover:text-white hover:border-white/[0.12]'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        {platform === 'all' && <UnifiedChat embedded />}
        {platform === 'linux' && <Chat embedded inventoryPlatform="linux" />}
        {platform === 'windows' && <WindowsChat embedded />}
        {platform === 'openshift' && <Chat embedded inventoryPlatform="openshift" />}
        {platform === 'exadata' && <Chat embedded inventoryPlatform="exadata" />}
        {platform === 'virt' && <HypervisorChat embedded />}
      </div>
    </div>
  )
}
