import React from 'react'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL } from '../config/platformAiops'
import OpsCenter from './OpsCenter'
import VirtOpsCenter from './VirtOpsCenter'
import Events from './Events'
import Incidents from './Incidents'
import AnomalyDetection from './AnomalyDetection'
import RootCauseAnalysis from './RootCauseAnalysis'
import BaselineManager from './BaselineManager'
import type { PlatformAiopsProps } from '../utils/platformApi'

function PlatformBanner({ platform }: { platform: PlatformKey }) {
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
      <span className="text-slate-500 ml-2">— kendi log kaynaklarından analiz</span>
    </div>
  )
}

function withPlatformPage(platform: PlatformKey, Page: React.ComponentType<PlatformAiopsProps>) {
  return () => (
    <>
      <PlatformBanner platform={platform} />
      <Page platform={platform} />
    </>
  )
}

export const LinuxOpsPage = () => <OpsCenter platform="linux" />
export const VirtOpsPage = () => <VirtOpsCenter />
export const WindowsOpsPage = () => (
  <>
    <PlatformBanner platform="windows" />
    <OpsCenter platform="windows" />
  </>
)

export const LinuxEventsPage = withPlatformPage('linux', Events)
export const VirtEventsPage = withPlatformPage('virt', Events)
export const WindowsEventsPage = withPlatformPage('windows', Events)

export const LinuxIncidentsPage = withPlatformPage('linux', Incidents)
export const VirtIncidentsPage = withPlatformPage('virt', Incidents)
export const WindowsIncidentsPage = withPlatformPage('windows', Incidents)

export const LinuxAnomaliesPage = withPlatformPage('linux', AnomalyDetection)
export const VirtAnomaliesPage = withPlatformPage('virt', AnomalyDetection)
export const WindowsAnomaliesPage = withPlatformPage('windows', AnomalyDetection)

export const LinuxRcaPage = withPlatformPage('linux', RootCauseAnalysis)
export const VirtRcaPage = withPlatformPage('virt', RootCauseAnalysis)
export const WindowsRcaPage = withPlatformPage('windows', RootCauseAnalysis)

export const LinuxBaselinePage = withPlatformPage('linux', BaselineManager)
export const VirtBaselinePage = withPlatformPage('virt', BaselineManager)
export const WindowsBaselinePage = withPlatformPage('windows', BaselineManager)
