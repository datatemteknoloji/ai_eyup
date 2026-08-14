import React from 'react'
import {
  Zap, ClipboardList, AlertTriangle, Wrench, MessageSquare,
} from 'lucide-react'

import type { TranslationKey } from '../i18n/messages'

export type PlatformKey = 'linux' | 'virt' | 'windows' | 'exadata' | 'openshift'

export const PLATFORM_AIOPS_PREFIX: Record<PlatformKey, string> = {
  linux: '/linux',
  virt: '/virt',
  windows: '/windows/aiops',
  exadata: '/exadata',
  openshift: '/openshift',
}

export type AiopsSummary = {
  critical: number
  warning: number
  total?: number
  open_incidents?: number
  action_needed?: boolean
}

type ChildItem = {
  path: string
  name: string
  icon: React.ReactNode
  badge?: () => React.ReactNode
}

function critBadge(n: number) {
  if (n <= 0) return null
  return (
    <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse">
      {n > 99 ? '99+' : n}
    </span>
  )
}

function warnBadge(n: number) {
  if (n <= 0) return null
  return (
    <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-white text-[10px] font-bold flex items-center justify-center">
      {n > 99 ? '99+' : n}
    </span>
  )
}

function totalBadge(n: number) {
  if (n <= 0) return null
  return (
    <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500/90 text-white text-[10px] font-bold flex items-center justify-center">
      {n > 99 ? '99+' : n}
    </span>
  )
}

/** Her platform modülü için AIOps alt menüsü — rozetler /ops/summary event sayılarıyla aynı */
export function buildPlatformAiopsChildren(
  platform: PlatformKey,
  summary: AiopsSummary | undefined,
  t: (key: TranslationKey) => string,
): ChildItem[] {
  const base = PLATFORM_AIOPS_PREFIX[platform]
  const critical = summary?.critical ?? 0
  const warning = summary?.warning ?? 0
  const openInc = summary?.open_incidents ?? 0
  return [
    {
      path: `${base}/chat`,
      name: t('nav_nl_assistant'),
      icon: React.createElement(MessageSquare, { size: 15 }),
    },
    {
      path: `${base}/ops`,
      name: t('nav_command_center'),
      icon: React.createElement(Zap, { size: 15 }),
      badge: () => critBadge(critical),
    },
    {
      path: `${base}/events`,
      name: t('nav_events'),
      icon: React.createElement(ClipboardList, { size: 15 }),
      badge: () => warnBadge(warning),
    },
    {
      path: `${base}/incidents`,
      name: t('nav_incidents'),
      icon: React.createElement(AlertTriangle, { size: 15 }),
      badge: () => (openInc > 0 ? warnBadge(openInc) : null),
    },
    {
      path: `${base}/analysis`,
      name: t(platform === 'openshift' ? 'nav_cluster_analysis' : 'nav_analysis_tools'),
      icon: React.createElement(Wrench, { size: 15 }),
    },
  ]
}

/** Linux AIOps / Windows AIOps üst satır toplam rozeti */
export function aiopsTotalBadge(summary?: AiopsSummary) {
  const n = summary?.total ?? ((summary?.critical ?? 0) + (summary?.warning ?? 0))
  return () => totalBadge(n)
}

export const PLATFORM_AIOPS_LABEL_KEY: Record<PlatformKey, TranslationKey> = {
  linux: 'nav_aiops_linux',
  virt: 'nav_aiops_virt',
  windows: 'nav_aiops_windows',
  exadata: 'nav_aiops_exadata',
  openshift: 'nav_aiops_openshift',
}

export function platformAiopsLabel(
  platform: PlatformKey,
  t: (key: TranslationKey) => string,
) {
  return t(PLATFORM_AIOPS_LABEL_KEY[platform])
}
