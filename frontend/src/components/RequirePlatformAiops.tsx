import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { PlatformKey } from '../config/platformAiops'

const ACCESS: Record<PlatformKey, (hasModule: (id: string) => boolean) => boolean> = {
  linux: (hm) => hm('linux'),
  virt: (hm) => hm('virtualization'),
  windows: (hm) => hm('windows'),
  exadata: (hm) => hm('exadata'),
}

export const RequirePlatformAiops: React.FC<{
  platform: PlatformKey
  children: React.ReactNode
}> = ({ platform, children }) => {
  const { hasModule } = useAuth()
  if (!ACCESS[platform](hasModule)) return <Navigate to="/" replace />
  return <>{children}</>
}
