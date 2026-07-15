import React from 'react'
import type { PlatformKey } from '../config/platformAiops'
import { PLATFORM_AIOPS_LABEL } from '../config/platformAiops'
import OpsCenter from './OpsCenter'
import VirtOpsCenter from './VirtOpsCenter'
import EventsHub from './EventsHub'
import AnalysisHub from './AnalysisHub'
import Incidents from './Incidents'
import AnomalyDetection from './AnomalyDetection'
import Chat from './Chat'
import WindowsChat from './WindowsChat'
import HypervisorChat from './HypervisorChat'
import type { PlatformAiopsProps } from '../utils/platformApi'

const CHAT_HINT: Record<PlatformKey, string> = {
  linux: 'AI-Ready Linux sunuculara SSH ile bağlanır; OS, proses, disk, servis, log sorularına canlı cevap verir.',
  windows: 'AI-Ready Windows sunuculara WinRM ile bağlanır; performans, servis, event log, güncelleme sorularına cevap verir.',
  virt: 'Senkronize vCenter/OLVM verisi (host, VM, cluster, datastore, metrik) üzerinden doğal dilde soru sorabilirsiniz.',
  exadata: 'Exadata compute/cell’e bağlı Linux node’lar üzerinden doğal dil sorgulama.',
}

function PlatformBanner({ platform, hint }: { platform: PlatformKey; hint?: string }) {
  return (
    <div className="mb-4 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
      <span className="text-slate-500 ml-2">— {hint || 'kendi log kaynaklarından analiz'}</span>
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
  return (
    <div className="-m-5 flex flex-col h-[calc(100vh-3.5rem)] min-h-0 overflow-hidden bg-slate-900">
      <div className="flex-none px-5 pt-4">
        <PlatformBanner platform={platform} hint={CHAT_HINT[platform]} />
      </div>
      <div className="flex-1 min-h-0 overflow-hidden px-5 pb-4">
        <div className="h-full min-h-0 overflow-hidden rounded-xl border border-slate-700/50">
          {children}
        </div>
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

/** @deprecated Geriye dönük uyumluluk — yönlendirme route'ları kullanılır */
export const LinuxAnomaliesPage = withPlatformPage('linux', AnomalyDetection)
export const VirtAnomaliesPage = withPlatformPage('virt', AnomalyDetection)
export const WindowsAnomaliesPage = withPlatformPage('windows', AnomalyDetection)
