import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL } from '../config/platformAiops'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { PageHeader, Tabs } from '../components/aiops/ui'
import Events from './Events'
import { CorrelationTab, LogHeatmapPanel } from './AnomalyDetection'

function PlatformBanner({ platform }: { platform: PlatformKey }) {
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
    </div>
  )
}

const TAB_IDS = ['olaylar', 'heatmap', 'correlation'] as const
type TabId = typeof TAB_IDS[number]

function normalizeTab(raw: string | null): TabId {
  if (raw === 'heatmap' || raw === 'list') return 'heatmap'
  if (raw === 'correlation') return 'correlation'
  return 'olaylar'
}

export default function EventsHub({ platform = 'linux' }: PlatformAiopsProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = normalizeTab(searchParams.get('tab'))

  useEffect(() => {
    const current = searchParams.get('tab')
    if (current && !TAB_IDS.includes(current as TabId) && current !== 'list') {
      setSearchParams({ tab: normalizeTab(current) }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const setTab = (id: string) => setSearchParams({ tab: id }, { replace: true })

  return (
    <>
      <PlatformBanner platform={platform} />
      <div className="space-y-4 animate-fade-in">
        <PageHeader
          title="Events"
          subtitle="Olay listesi, log ısı haritası ve metrik korelasyonu"
        />
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'olaylar', label: 'Olaylar' },
            { id: 'heatmap', label: 'Log Isı Haritası' },
            { id: 'correlation', label: 'Korelasyon' },
          ]}
        />
        {tab === 'olaylar' && <Events platform={platform} hideHeader />}
        {tab === 'heatmap' && <LogHeatmapPanel platform={platform} />}
        {tab === 'correlation' && <CorrelationTab />}
      </div>
    </>
  )
}
