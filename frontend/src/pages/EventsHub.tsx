import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL_KEY } from '../config/platformAiops'
import { useT } from '../i18n/LocaleProvider'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { API_BASE_URL } from '../config/api'
import { PageHeader, Tabs, GhostButton, NEON } from '../components/aiops/ui'
import BulkJobOverlay, { beginBulkJobModal, persistBulkJobId } from '../components/BulkJobOverlay'
import Events from './Events'
import { CorrelationTab, LogHeatmapPanel } from './AnomalyDetection'

function PlatformBanner({ platform }: { platform: PlatformKey }) {
  const t = useT()
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">{t('platform')}:</span>{' '}
      <span className="font-medium text-white">{t(PLATFORM_AIOPS_LABEL_KEY[platform])}</span>
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
  const t = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = normalizeTab(searchParams.get('tab'))
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  useEffect(() => {
    const current = searchParams.get('tab')
    if (current && !TAB_IDS.includes(current as TabId) && current !== 'list') {
      setSearchParams({ tab: normalizeTab(current) }, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    persistBulkJobId(bulkJobId)
  }, [bulkJobId])

  const setTab = (id: string) => setSearchParams({ tab: id }, { replace: true })

  const startScanJob = (jobId: string) => {
    beginBulkJobModal(jobId)
    setBulkJobId(jobId)
    setScanMsg(null)
  }

  const invalidateAfterScan = () => {
    queryClient.invalidateQueries({ queryKey: ['events'] })
    queryClient.invalidateQueries({ queryKey: ['eventStats'] })
    queryClient.invalidateQueries({ queryKey: ['anomaly-log-heatmap-30d', platform] })
  }

  const handleScanNow = async () => {
    setScanning(true)
    setScanMsg(null)
    try {
      const res = await fetch(
        `${API_BASE_URL}/events/scan?platform=${platform}&only_ai_ready=true`,
        { method: 'POST' },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : t('ev_scan_failed'))
      if (data.job_id) {
        startScanJob(data.job_id)
      } else {
        setScanMsg(data.message || t('ev_scan_done'))
        invalidateAfterScan()
      }
    } catch (e) {
      setScanMsg(e instanceof Error ? e.message : t('ev_scan_error'))
    } finally {
      setScanning(false)
    }
  }

  return (
    <>
      <PlatformBanner platform={platform} />
      <div className="space-y-4 animate-fade-in">
        <PageHeader
          title={t('nav_events')}
          subtitle={t('ev_hub_subtitle')}
          actions={
            <GhostButton accent={NEON.green} onClick={handleScanNow} disabled={scanning || !!bulkJobId}>
              {scanning ? t('starting') : t('ev_scan_now')}
            </GhostButton>
          }
        />
        {scanMsg && (
          <div className="px-4 py-2 rounded-xl text-sm text-slate-300 bg-slate-800/60 border border-slate-700/50">
            {scanMsg}
          </div>
        )}
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'olaylar', label: t('ev_tab_events') },
            { id: 'heatmap', label: t('ev_tab_heatmap') },
            { id: 'correlation', label: t('ev_tab_corr') },
          ]}
        />
        {tab === 'olaylar' && <Events platform={platform} hideHeader />}
        {tab === 'heatmap' && (
          <LogHeatmapPanel platform={platform} onScanJobStarted={startScanJob} />
        )}
        {tab === 'correlation' && <CorrelationTab />}
      </div>
      {bulkJobId && (
        <BulkJobOverlay
          jobId={bulkJobId}
          onDone={(job) => {
            invalidateAfterScan()
            const r = (job as { result?: { total_saved?: number; total_servers?: number } })?.result
            if (r) {
              const saved = r.total_saved ?? 0
              setScanMsg(
                saved > 0
                  ? t('ev_scan_done_n_srv', { n: saved, s: r.total_servers ?? 0 })
                  : t('ev_scan_done_none_srv', { s: r.total_servers ?? 0 }),
              )
            }
          }}
          onDismiss={() => setBulkJobId(null)}
        />
      )}
    </>
  )
}
