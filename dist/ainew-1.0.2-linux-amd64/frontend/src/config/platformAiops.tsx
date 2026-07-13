import React from 'react'
import {
  Zap, ClipboardList, AlertTriangle, Wrench,
} from 'lucide-react'

export type PlatformKey = 'linux' | 'virt' | 'windows' | 'exadata'

export const PLATFORM_AIOPS_PREFIX: Record<PlatformKey, string> = {
  linux: '/linux',
  virt: '/virt',
  windows: '/windows/aiops',
  exadata: '/exadata',
}

export type AiopsSummary = { critical: number; warning: number; action_needed?: boolean }

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

/** Her platform modülü için AIOps alt menüsü */
export function buildPlatformAiopsChildren(
  platform: PlatformKey,
  summary?: AiopsSummary,
): ChildItem[] {
  const base = PLATFORM_AIOPS_PREFIX[platform]
  return [
    {
      path: `${base}/ops`,
      name: 'Komuta Merkezi',
      icon: React.createElement(Zap, { size: 15 }),
      badge: () => critBadge(summary?.critical ?? 0),
    },
    {
      path: `${base}/events`,
      name: 'Events',
      icon: React.createElement(ClipboardList, { size: 15 }),
      badge: () => warnBadge(summary?.warning ?? 0),
    },
    { path: `${base}/incidents`, name: 'Incidents', icon: React.createElement(AlertTriangle, { size: 15 }) },
    { path: `${base}/analysis`, name: 'Analiz Araçları', icon: React.createElement(Wrench, { size: 15 }) },
  ]
}

export const PLATFORM_AIOPS_LABEL: Record<PlatformKey, string> = {
  linux: 'Linux AIOps',
  virt: 'Sanallaştırma AIOps',
  windows: 'Windows AIOps',
  exadata: 'Exadata AIOps',
}
