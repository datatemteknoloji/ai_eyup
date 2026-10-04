/**
 * Windows monitoring — API (Timescale metric_data) + Prometheus (windows_exporter).
 * Hub `/monitoring` (Windows) ve `/windows/live-metrics` aynı bileşen.
 */
import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useT } from '../i18n/LocaleProvider'
import { MonitoringShell, type MonitoringDataMode } from '../components/monitoring/MonitoringShell'
import { WindowsApiView } from '../components/monitoring/WindowsApiView'
import LiveMetrics from './LiveMetrics'

const WindowsMonitoring: React.FC<{
  embedded?: boolean
  sourceId?: string
  hubLeading?: React.ReactNode
  onDataModeChange?: (mode: MonitoringDataMode) => void
}> = ({
  embedded = false,
  hubLeading,
  onDataModeChange,
}) => {
  const t = useT()
  const [dataMode, setDataMode] = useState<MonitoringDataMode>(() => {
    const m = localStorage.getItem('ainew.win.monitoring.mode')
    return m === 'prometheus' ? 'prometheus' : 'api'
  })

  useEffect(() => {
    localStorage.setItem('ainew.win.monitoring.mode', dataMode)
    onDataModeChange?.(dataMode)
  }, [dataMode, onDataModeChange])

  return (
    <MonitoringShell
      title={t('wmn_title')}
      subtitle={dataMode === 'prometheus' ? t('wlm_subtitle_prom') : t('wmn_subtitle')}
      mode={dataMode}
      onModeChange={setDataMode}
      prometheusConfigured
      embedded={embedded}
      hubLeading={hubLeading}
      extraHeader={
        dataMode === 'api' ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <Link to="/windows" className="text-blue-400 hover:underline whitespace-nowrap">{t('nav_inventory')}</Link>
            <Link to="/windows/aiops/chat" className="text-blue-400 hover:underline whitespace-nowrap">{t('nav_assistant')}</Link>
          </div>
        ) : undefined
      }
    >
      {dataMode === 'prometheus' ? (
        <LiveMetrics embedded platform="windows" />
      ) : (
        <WindowsApiView />
      )}
    </MonitoringShell>
  )
}

export default WindowsMonitoring
