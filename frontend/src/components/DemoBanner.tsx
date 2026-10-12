import React from 'react'
import { AlertTriangle } from 'lucide-react'
import { useCapabilities } from '../hooks/useCapabilities'
import { useT } from '../i18n/LocaleProvider'

/** F.0: DEMO yedek sağlayıcısı etkinken HER ekranın üstünde görünür (üretimde bayrak kapalı → hiç render edilmez). */
export const DemoBanner: React.FC = () => {
  const { demoActive } = useCapabilities()
  const t = useT()
  if (!demoActive) return null
  return (
    <div
      role="alert"
      data-testid="demo-global-banner"
      className="flex items-center gap-2 px-4 py-1.5 text-xs font-semibold bg-fuchsia-600 text-white border-b border-fuchsia-300/40"
    >
      <AlertTriangle size={14} />
      <span>{t('demo_global_banner')}</span>
      <span className="font-normal opacity-90 truncate">— {t('demo_global_banner_desc')}</span>
    </div>
  )
}

export default DemoBanner
