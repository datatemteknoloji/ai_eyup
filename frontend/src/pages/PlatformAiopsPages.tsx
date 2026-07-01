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

type ScopeProps = { platform: PlatformKey }

function PlatformBanner({ platform }: ScopeProps) {
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
    </div>
  )
}

function withPlatform<P extends object>(
  platform: PlatformKey,
  Page: React.ComponentType<P>,
): React.FC<P> {
  return (props) => (
    <>
      <PlatformBanner platform={platform} />
      <Page {...props} />
    </>
  )
}

export const LinuxOpsPage = () => <OpsCenter />
export const VirtOpsPage = () => <VirtOpsCenter />
export const WindowsOpsPage = () => (
  <>
    <PlatformBanner platform="windows" />
    <OpsCenter />
  </>
)

export const LinuxEventsPage = withPlatform('linux', Events)
export const VirtEventsPage = withPlatform('virt', Events)
export const WindowsEventsPage = withPlatform('windows', Events)

export const LinuxIncidentsPage = withPlatform('linux', Incidents)
export const VirtIncidentsPage = withPlatform('virt', Incidents)
export const WindowsIncidentsPage = withPlatform('windows', Incidents)

export const LinuxAnomaliesPage = withPlatform('linux', AnomalyDetection)
export const VirtAnomaliesPage = withPlatform('virt', AnomalyDetection)
export const WindowsAnomaliesPage = withPlatform('windows', AnomalyDetection)

export const LinuxRcaPage = withPlatform('linux', RootCauseAnalysis)
export const VirtRcaPage = withPlatform('virt', RootCauseAnalysis)
export const WindowsRcaPage = withPlatform('windows', RootCauseAnalysis)

export const LinuxBaselinePage = withPlatform('linux', BaselineManager)
export const VirtBaselinePage = withPlatform('virt', BaselineManager)
export const WindowsBaselinePage = withPlatform('windows', BaselineManager)
