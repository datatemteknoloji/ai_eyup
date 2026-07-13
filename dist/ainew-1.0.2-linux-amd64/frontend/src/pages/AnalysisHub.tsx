import { useSearchParams } from 'react-router-dom'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL } from '../config/platformAiops'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { PageHeader, Tabs } from '../components/aiops/ui'
import RootCauseAnalysis from './RootCauseAnalysis'
import BaselineManager from './BaselineManager'

function PlatformBanner({ platform }: { platform: PlatformKey }) {
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
    </div>
  )
}

type TabId = 'rca' | 'baseline'

function normalizeTab(raw: string | null): TabId {
  return raw === 'baseline' ? 'baseline' : 'rca'
}

export default function AnalysisHub({ platform = 'linux' }: PlatformAiopsProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = normalizeTab(searchParams.get('tab'))
  const setTab = (id: string) => setSearchParams({ tab: id }, { replace: true })

  return (
    <>
      <PlatformBanner platform={platform} />
      <div className="space-y-4 animate-fade-in">
        <PageHeader
          title="Analiz Araçları"
          subtitle="Kök neden analizi ve baseline / alarm bastırma kuralları"
        />
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'rca', label: 'Kök Neden Analizi' },
            { id: 'baseline', label: 'Baseline Yönetimi' },
          ]}
        />
        {tab === 'rca' && <RootCauseAnalysis platform={platform} hideHeader />}
        {tab === 'baseline' && <BaselineManager platform={platform} hideHeader />}
      </div>
    </>
  )
}
