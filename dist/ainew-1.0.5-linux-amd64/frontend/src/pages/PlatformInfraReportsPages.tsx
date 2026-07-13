import InfraReports from './InfraReports'
import type { PlatformKey } from '../config/platformAiops'

const page = (platform: PlatformKey, initialTab?: 'reports' | 'chat' | 'compare') =>
  () => <InfraReports platform={platform} initialTab={initialTab} />

export const LinuxInfraReportsPage = page('linux')
export const WindowsInfraReportsPage = page('windows')
export const VirtInfraReportsPage = page('virt')
export const ExadataInfraReportsPage = page('exadata')
