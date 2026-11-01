import InfraReports from './InfraReports'
import type { ReportPlatformKey } from '../config/infraReportCatalog'

const page = (platform: ReportPlatformKey, initialTab?: 'reports' | 'chat' | 'compare') =>
  () => <InfraReports platform={platform} initialTab={initialTab} />

export const LinuxInfraReportsPage = page('linux')
export const WindowsInfraReportsPage = page('windows')
export const VirtInfraReportsPage = page('virt')
export const ExadataInfraReportsPage = page('exadata')
export const OpenShiftInfraReportsPage = page('openshift')
export const ExecutiveInfraReportsPage = page('executive')
