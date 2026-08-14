import React from 'react'
import { PLATFORM_AIOPS_LABEL_KEY, type PlatformKey } from '../config/platformAiops'
import { useT } from '../i18n/LocaleProvider'
import OpsCenter from './OpsCenter'
import VirtOpsCenter from './VirtOpsCenter'
import OpenShiftOpsCenter from './OpenShiftOpsCenter'
import EventsHub from './EventsHub'
import AnalysisHub from './AnalysisHub'
import Incidents from './Incidents'
import AnomalyDetection from './AnomalyDetection'
import Chat from './Chat'
import WindowsChat from './WindowsChat'
import HypervisorChat from './HypervisorChat'
import type { PlatformAiopsProps } from '../utils/platformApi'

const CHAT_HINT: Record<PlatformKey, 'chat_hint_linux' | 'chat_hint_windows' | 'chat_hint_virt' | 'chat_hint_exadata' | 'chat_hint_openshift'> = {
  linux: 'chat_hint_linux',
  windows: 'chat_hint_windows',
  virt: 'chat_hint_virt',
  exadata: 'chat_hint_exadata',
  openshift: 'chat_hint_openshift',
}

function PlatformBanner({ platform, hint }: { platform: PlatformKey; hint?: string }) {
  const t = useT()
  return (
    <div className="px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-400">
      <span className="text-slate-500">{t('platform')}:</span>{' '}
      <span className="font-medium text-slate-200">{t(PLATFORM_AIOPS_LABEL_KEY[platform])}</span>
      <span className="text-slate-500 ml-2">— {hint || t('ops_nl_hint')}</span>
    </div>
  )
}

function PlatformChatShell({
  platform,
  children,
}: {
  platform: PlatformKey
  children: React.ReactNode
}) {
  const t = useT()
  return (
    <div className="-m-5 flex flex-col h-[calc(100vh-3.5rem)] min-h-0 overflow-hidden bg-slate-900">
      <div className="flex-none px-4 pt-3 pb-2 border-b border-slate-700/50">
        <PlatformBanner platform={platform} hint={t(CHAT_HINT[platform])} />
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {children}
      </div>
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
export const WindowsOpsPage = () => <OpsCenter platform="windows" />
export const ExadataOpsPage = () => <OpsCenter platform="exadata" />

export const LinuxEventsPage = () => <EventsHub platform="linux" />
export const VirtEventsPage = () => <EventsHub platform="virt" />
export const WindowsEventsPage = () => <EventsHub platform="windows" />

export const LinuxIncidentsPage = withPlatformPage('linux', Incidents)
export const VirtIncidentsPage = withPlatformPage('virt', Incidents)
export const WindowsIncidentsPage = withPlatformPage('windows', Incidents)

export const LinuxAnalysisPage = () => <AnalysisHub platform="linux" />
export const VirtAnalysisPage = () => <AnalysisHub platform="virt" />
export const WindowsAnalysisPage = () => <AnalysisHub platform="windows" />

export const ExadataEventsPage = () => <EventsHub platform="exadata" />
export const ExadataIncidentsPage = withPlatformPage('exadata', Incidents)
export const ExadataAnalysisPage = () => <AnalysisHub platform="exadata" />

export const OpenShiftOpsPage = () => <OpenShiftOpsCenter />
export const OpenShiftEventsPage = () => <EventsHub platform="openshift" />
export const OpenShiftIncidentsPage = withPlatformPage('openshift', Incidents)

export const LinuxChatPage = () => (
  <PlatformChatShell platform="linux">
    <Chat embedded inventoryPlatform="linux" />
  </PlatformChatShell>
)
export const WindowsChatPage = () => (
  <PlatformChatShell platform="windows">
    <WindowsChat embedded />
  </PlatformChatShell>
)
export const VirtChatPage = () => (
  <PlatformChatShell platform="virt">
    <HypervisorChat embedded />
  </PlatformChatShell>
)
export const ExadataChatPage = () => (
  <PlatformChatShell platform="exadata">
    <Chat embedded inventoryPlatform="exadata" />
  </PlatformChatShell>
)
export const OpenShiftChatPage = () => (
  <PlatformChatShell platform="openshift">
    <Chat embedded inventoryPlatform="openshift" />
  </PlatformChatShell>
)

/** @deprecated Geriye dönük uyumluluk — yönlendirme route'ları kullanılır */
export const LinuxAnomaliesPage = withPlatformPage('linux', AnomalyDetection)
export const VirtAnomaliesPage = withPlatformPage('virt', AnomalyDetection)
export const WindowsAnomaliesPage = withPlatformPage('windows', AnomalyDetection)
