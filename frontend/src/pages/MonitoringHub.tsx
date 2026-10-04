/**
 * Ana Monitoring hub — kompakt tek satır araç çubuğu.
 * Other kaynaklar generic "Other" değil; her biri kendi label’ı ile listelenir.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'
import { useT } from '../i18n/LocaleProvider'
import { MonitoringArchitectureHint } from '../components/monitoring/MonitoringArchitectureHint'
import { CustomMetricExplorer } from '../components/monitoring/CustomMetricExplorer'
import { ZabbixMonitoringView } from '../components/monitoring/ZabbixMonitoringView'
import LiveMetrics from './LiveMetrics'
import WindowsMonitoring from './WindowsMonitoring'
import OpenShiftMonitoring from './OpenShiftMonitoring'
import VirtMonitoring from './VirtMonitoring'

type Src = {
  id: string
  label: string
  url: string
  binding: string
  collector_type?: string
  prom_compatible?: boolean
}

type HubModule = 'linux' | 'windows' | 'openshift' | 'virtualization' | `custom:${string}`

const LS_MOD = 'ainew.monitoring.hub.module'

function isCustomMod(mod: string): mod is `custom:${string}` {
  return mod.startsWith('custom:')
}

const MonitoringHub: React.FC = () => {
  const t = useT()
  const { hasModule } = useAuth()
  const canOther = hasModule('executive') || hasModule('ai_automation') || hasModule('linux')
    || hasModule('windows') || hasModule('openshift') || hasModule('virtualization')

  const { data: settings, isFetched: settingsFetched } = useQuery({
    queryKey: ['general-settings', 'hub'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/`)
      if (!r.ok) throw new Error('settings')
      return r.json() as Promise<{ monitoring_sources?: Src[] }>
    },
  })
  const sources = settings?.monitoring_sources || []
  const customSources = useMemo(
    () => sources.filter((s) => s.binding === 'none'),
    [sources],
  )

  const modules = useMemo(() => {
    const list: { id: HubModule; label: string; ok: boolean; hint?: string }[] = [
      { id: 'linux', label: t('nav_linux'), ok: hasModule('linux') },
      { id: 'windows', label: t('nav_windows'), ok: hasModule('windows') },
      { id: 'openshift', label: t('nav_openshift'), ok: hasModule('openshift') },
      { id: 'virtualization', label: t('nav_virt'), ok: hasModule('virtualization') },
    ]
    if (canOther) {
      if (customSources.length === 0) {
        // Ayarlar henüz gelmediyse placeholder koyma — kayıtlı custom:* seçimini silmesin
        if (settingsFetched) {
          list.push({ id: 'custom:__empty__', label: t('mon_other'), ok: true, hint: 'empty' })
        }
      } else {
        for (const s of customSources) {
          const ct = s.collector_type || 'prometheus'
          list.push({
            id: `custom:${s.id}`,
            label: s.label,
            ok: true,
            hint: ct,
          })
        }
      }
    }
    return list.filter((m) => m.ok)
  }, [hasModule, t, canOther, customSources, settingsFetched])

  const [mod, setMod] = useState<HubModule>(() => {
    const saved = localStorage.getItem(LS_MOD) as HubModule | null
    return saved || 'linux'
  })
  const [sourceId, setSourceId] = useState('')
  const [headerSlot, setHeaderSlot] = useState<HTMLElement | null>(null)
  const [ocpDataMode, setOcpDataMode] = useState<'api' | 'prometheus'>(() => {
    const m = localStorage.getItem('ainew.ocp.monitoring.mode')
    return m === 'prometheus' ? 'prometheus' : 'api'
  })
  const [virtDataMode, setVirtDataMode] = useState<'api' | 'prometheus'>(() => {
    const m = localStorage.getItem('ainew.virt.monitoring.mode')
    return m === 'prometheus' ? 'prometheus' : 'api'
  })
  const [winDataMode, setWinDataMode] = useState<'api' | 'prometheus'>(() => {
    const m = localStorage.getItem('ainew.win.monitoring.mode')
    return m === 'prometheus' ? 'prometheus' : 'api'
  })

  useEffect(() => {
    setHeaderSlot(document.getElementById('monitoring-arch-header-slot'))
  }, [])

  // Ayarlar yüklenmeden custom:* henüz modules'ta yok; linux'a düşürme
  useEffect(() => {
    if (!settingsFetched) return
    if (!modules.find((m) => m.id === mod) && modules[0]) setMod(modules[0].id)
  }, [modules, mod, settingsFetched])

  useEffect(() => {
    localStorage.setItem(LS_MOD, mod)
  }, [mod])

  const activeCustom = useMemo(() => {
    if (!isCustomMod(mod) || mod === 'custom:__empty__') return null
    const id = mod.slice('custom:'.length)
    return customSources.find((s) => s.id === id) || null
  }, [mod, customSources])

  const bound = useMemo(() => {
    if (isCustomMod(mod)) return customSources
    return sources.filter((s) => s.binding === mod)
  }, [sources, mod, customSources])

  useEffect(() => {
    if (activeCustom) {
      setSourceId(activeCustom.id)
      return
    }
    if (bound.length && !bound.find((s) => s.id === sourceId)) {
      setSourceId(bound[0].id)
    }
  }, [bound, sourceId, activeCustom])

  const showSource = bound.length > 0 && (
    (mod === 'virtualization' && virtDataMode === 'prometheus')
    || (mod === 'openshift' && ocpDataMode === 'prometheus')
    || (mod === 'windows' && winDataMode === 'prometheus' && bound.some((s) => s.binding === 'windows'))
  )

  const hubLeading = (
    <>
      <label className="flex items-center gap-1.5 text-xs text-slate-400">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">{t('mon_module')}</span>
        <select
          value={mod}
          onChange={(e) => setMod(e.target.value as HubModule)}
          className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200 max-w-[18rem]"
        >
          {modules.map((m) => (
            <option key={m.id} value={m.id}>
              {m.hint && m.hint !== 'empty' && isCustomMod(m.id)
                ? `${m.label} · ${m.hint}`
                : m.label}
            </option>
          ))}
        </select>
      </label>
      {showSource && (
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">{t('mon_source_label')}</span>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200 max-w-[14rem]"
          >
            {bound.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      )}
    </>
  )

  const customPromCompatible = activeCustom
    && (activeCustom.prom_compatible !== false)
    && (activeCustom.collector_type || 'prometheus') !== 'zabbix'

  return (
    <div className="px-4 pt-1.5 pb-4 max-w-[1600px] mx-auto">
      {headerSlot && createPortal(<MonitoringArchitectureHint />, headerSlot)}
      {mod === 'linux' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-h-[2rem]">{hubLeading}</div>
          <LiveMetrics embedded />
        </div>
      )}
      {mod === 'windows' && (
        <WindowsMonitoring
          embedded
          sourceId={sourceId || undefined}
          hubLeading={hubLeading}
          onDataModeChange={setWinDataMode}
        />
      )}
      {isCustomMod(mod) && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-h-[2rem]">{hubLeading}</div>
          {mod === 'custom:__empty__' && (
            <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-6 text-sm text-slate-400">
              {t('mon_other_empty')}
            </div>
          )}
          {activeCustom && customPromCompatible && (
            <CustomMetricExplorer
              sourceId={activeCustom.id}
              onSourceIdChange={(id) => {
                setSourceId(id)
                setMod(`custom:${id}`)
              }}
              hideSourcePicker
              titleLabel={activeCustom.label}
              collectorType={activeCustom.collector_type || 'prometheus'}
            />
          )}
          {activeCustom && !customPromCompatible && (activeCustom.collector_type || '') === 'zabbix' && (
            <ZabbixMonitoringView
              sourceId={activeCustom.id}
              titleLabel={activeCustom.label}
            />
          )}
          {activeCustom && !customPromCompatible && (activeCustom.collector_type || '') !== 'zabbix' && (
            <div className="rounded-xl border border-amber-500/20 bg-cyber-card p-6 space-y-2">
              <h3 className="text-sm font-medium text-white">{activeCustom.label}</h3>
              <p className="text-xs text-slate-400">
                {t('mon_zabbix_pending', { type: activeCustom.collector_type || 'unknown' })}
              </p>
              <p className="text-[11px] text-slate-500 font-mono truncate">{activeCustom.url}</p>
            </div>
          )}
        </div>
      )}
      {mod === 'openshift' && (
        <OpenShiftMonitoring
          embedded
          sourceId={sourceId || undefined}
          hubLeading={hubLeading}
          onDataModeChange={setOcpDataMode}
        />
      )}
      {mod === 'virtualization' && (
        <VirtMonitoring
          embedded
          sourceId={sourceId || undefined}
          hubLeading={hubLeading}
          onDataModeChange={setVirtDataMode}
        />
      )}
    </div>
  )
}

export default MonitoringHub
