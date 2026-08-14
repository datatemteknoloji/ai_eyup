import React from 'react'
import {
  BarChart3, Zap, Shield, Server, TrendingUp, AlertTriangle,
  Activity, RefreshCw, CheckCircle2, Cpu, Layers, Target, Radar,
} from 'lucide-react'
import type { PlatformKey } from '../config/platformAiops'
import type { TranslationKey } from '../i18n/messages'

export type ReportCatalogItem = {
  type: string
  titleKey: TranslationKey
  icon: React.ReactNode
  color: string
  descKey: TranslationKey
}

export const PLATFORM_REPORT_TITLE_KEYS: Record<PlatformKey, TranslationKey> = {
  linux: 'rpt_plat_linux',
  windows: 'rpt_plat_windows',
  virt: 'rpt_plat_virt',
  exadata: 'rpt_plat_exadata',
  openshift: 'rpt_plat_openshift',
}

export const PLATFORM_REPORT_SUBTITLE_KEYS: Record<PlatformKey, TranslationKey> = {
  linux: 'rpt_sub_linux',
  windows: 'rpt_sub_windows',
  virt: 'rpt_sub_virt',
  exadata: 'rpt_sub_exadata',
  openshift: 'rpt_sub_openshift',
}

const VIRT_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', titleKey: 'rpt_exec', icon: <BarChart3 size={18} />, color: 'blue', descKey: 'rpt_exec_virt_desc' },
  { type: 'capacity', titleKey: 'rpt_capacity', icon: <Server size={18} />, color: 'purple', descKey: 'rpt_capacity_virt_desc' },
  { type: 'risk', titleKey: 'rpt_risk', icon: <AlertTriangle size={18} />, color: 'red', descKey: 'rpt_risk_virt_desc' },
  { type: 'vm_health', titleKey: 'rpt_vm_health', icon: <Zap size={18} />, color: 'green', descKey: 'rpt_vm_health_desc' },
  { type: 'resource_usage', titleKey: 'rpt_resource', icon: <Cpu size={18} />, color: 'amber', descKey: 'rpt_resource_desc' },
  { type: 'security_compliance', titleKey: 'rpt_sec_comp', icon: <Shield size={18} />, color: 'teal', descKey: 'rpt_sec_comp_desc' },
  { type: 'consolidation', titleKey: 'rpt_consol', icon: <RefreshCw size={18} />, color: 'orange', descKey: 'rpt_consol_desc' },
  { type: 'operations', titleKey: 'rpt_ops', icon: <BarChart3 size={18} />, color: 'indigo', descKey: 'rpt_ops_virt_desc' },
  { type: 'forecast', titleKey: 'rpt_forecast', icon: <TrendingUp size={18} />, color: 'cyan', descKey: 'rpt_forecast_desc' },
  { type: 'sla', titleKey: 'rpt_sla', icon: <CheckCircle2 size={18} />, color: 'green', descKey: 'rpt_sla_desc' },
  { type: 'riskiest_assets', titleKey: 'rpt_riskiest', icon: <Target size={18} />, color: 'red', descKey: 'rpt_riskiest_desc' },
]

const LINUX_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', titleKey: 'rpt_exec', icon: <BarChart3 size={18} />, color: 'blue', descKey: 'rpt_exec_linux_desc' },
  { type: 'capacity', titleKey: 'rpt_capacity', icon: <Server size={18} />, color: 'purple', descKey: 'rpt_capacity_linux_desc' },
  { type: 'operations', titleKey: 'rpt_ops', icon: <Activity size={18} />, color: 'indigo', descKey: 'rpt_ops_linux_desc' },
  { type: 'risk', titleKey: 'rpt_risk', icon: <AlertTriangle size={18} />, color: 'red', descKey: 'rpt_risk_linux_desc' },
  { type: 'performance', titleKey: 'rpt_perf', icon: <Zap size={18} />, color: 'yellow', descKey: 'rpt_perf_desc' },
  { type: 'patch_status', titleKey: 'rpt_patch', icon: <RefreshCw size={18} />, color: 'orange', descKey: 'rpt_patch_linux_desc' },
  { type: 'security', titleKey: 'rpt_sec', icon: <Shield size={18} />, color: 'teal', descKey: 'rpt_sec_desc' },
  { type: 'sla', titleKey: 'rpt_sla_linux', icon: <CheckCircle2 size={18} />, color: 'green', descKey: 'rpt_sla_desc' },
  { type: 'monitoring_coverage', titleKey: 'rpt_mon', icon: <Radar size={18} />, color: 'cyan', descKey: 'rpt_mon_linux_desc' },
]

const WINDOWS_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', titleKey: 'rpt_exec', icon: <BarChart3 size={18} />, color: 'blue', descKey: 'rpt_exec_win_desc' },
  { type: 'operations', titleKey: 'rpt_ops', icon: <Activity size={18} />, color: 'indigo', descKey: 'rpt_ops_win_desc' },
  { type: 'risk', titleKey: 'rpt_risk', icon: <AlertTriangle size={18} />, color: 'red', descKey: 'rpt_risk_win_desc' },
  { type: 'security', titleKey: 'rpt_sec_win', icon: <Shield size={18} />, color: 'teal', descKey: 'rpt_sec_win_desc' },
  { type: 'patch_status', titleKey: 'rpt_patch', icon: <RefreshCw size={18} />, color: 'orange', descKey: 'rpt_patch_win_desc' },
  { type: 'sla', titleKey: 'rpt_sla_linux', icon: <CheckCircle2 size={18} />, color: 'green', descKey: 'rpt_sla_desc' },
  { type: 'monitoring_coverage', titleKey: 'rpt_mon', icon: <Radar size={18} />, color: 'cyan', descKey: 'rpt_mon_win_desc' },
]

const EXADATA_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', titleKey: 'rpt_exec', icon: <BarChart3 size={18} />, color: 'blue', descKey: 'rpt_exec_exa_desc' },
  { type: 'capacity', titleKey: 'rpt_capacity', icon: <Server size={18} />, color: 'purple', descKey: 'rpt_capacity_exa_desc' },
  { type: 'operations', titleKey: 'rpt_ops', icon: <Activity size={18} />, color: 'indigo', descKey: 'rpt_ops_exa_desc' },
  { type: 'risk', titleKey: 'rpt_risk', icon: <AlertTriangle size={18} />, color: 'red', descKey: 'rpt_risk_exa_desc' },
  { type: 'node_health', titleKey: 'rpt_node_health', icon: <Layers size={18} />, color: 'green', descKey: 'rpt_node_health_desc' },
]

const OPENSHIFT_CATALOG: ReportCatalogItem[] = []

export const PLATFORM_REPORT_CATALOGS: Record<PlatformKey, ReportCatalogItem[]> = {
  linux: LINUX_CATALOG,
  windows: WINDOWS_CATALOG,
  virt: VIRT_CATALOG,
  exadata: EXADATA_CATALOG,
  openshift: OPENSHIFT_CATALOG,
}

export function reportsApiBase(platform: PlatformKey): string {
  return platform === 'virt'
    ? '/hypervisors/reports'
    : `/platform-reports/${platform}`
}
