import { useSearchParams } from 'react-router-dom'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL_KEY } from '../config/platformAiops'
import { useT } from '../i18n/LocaleProvider'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { PageHeader, Tabs } from '../components/aiops/ui'
import RootCauseAnalysis from './RootCauseAnalysis'
import BaselineManager from './BaselineManager'

function PlatformBanner({ platform }: { platform: PlatformKey }) {
  const t = useT()
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">{t('platform')}:</span>{' '}
      <span className="font-medium text-white">{t(PLATFORM_AIOPS_LABEL_KEY[platform])}</span>
    </div>
  )
}

type TabId = 'rca' | 'baseline'

function normalizeTab(raw: string | null): TabId {
  return raw === 'baseline' ? 'baseline' : 'rca'
}

export default function AnalysisHub({ platform = 'linux' }: PlatformAiopsProps) {
  const t = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = normalizeTab(searchParams.get('tab'))
  const setTab = (id: string) => setSearchParams({ tab: id }, { replace: true })

  return (
    <>
      <PlatformBanner platform={platform} />
      <div className="space-y-4 animate-fade-in">
        <PageHeader
          title={t('ana_title')}
          subtitle={t('ana_subtitle')}
        />
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'rca', label: t('ana_tab_rca') },
            { id: 'baseline', label: t('ana_tab_baseline') },
          ]}
        />
        {tab === 'rca' && <RootCauseAnalysis platform={platform} hideHeader />}
        {tab === 'baseline' && <BaselineManager platform={platform} hideHeader />}
      </div>
    </>
  )
}
