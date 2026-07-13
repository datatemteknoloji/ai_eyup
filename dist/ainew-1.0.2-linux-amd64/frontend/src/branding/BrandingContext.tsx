import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { API_BASE_URL } from '../config/api'

export const DEFAULT_APP_NAME = 'datatem AI'

interface BrandingContextValue {
  appName: string
  logoUrl: string | null
  loading: boolean
  refreshBranding: () => Promise<void>
}

const BrandingContext = createContext<BrandingContextValue>({
  appName: DEFAULT_APP_NAME,
  logoUrl: null,
  loading: true,
  refreshBranding: async () => {},
})

export const useBranding = () => useContext(BrandingContext)

export const BrandingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [appName, setAppName] = useState(DEFAULT_APP_NAME)
  const [hasLogo, setHasLogo] = useState(false)
  const [cacheBust, setCacheBust] = useState(0)
  const [loading, setLoading] = useState(true)

  const fetchBranding = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE_URL}/public/branding`)
      if (r.ok) {
        const data = await r.json()
        setAppName(data.app_name || DEFAULT_APP_NAME)
        setHasLogo(Boolean(data.has_logo))
      }
    } catch {
      // Sessizce varsayılanlarda kal — marka bilgisi kritik değil
    }
  }, [])

  const refreshBranding = useCallback(async () => {
    setCacheBust(v => v + 1)
    await fetchBranding()
  }, [fetchBranding])

  useEffect(() => {
    fetchBranding().finally(() => setLoading(false))
  }, [fetchBranding])

  useEffect(() => {
    document.title = appName
  }, [appName])

  const logoUrl = hasLogo ? `${API_BASE_URL}/public/logo?v=${cacheBust}` : null

  return (
    <BrandingContext.Provider value={{ appName, logoUrl, loading, refreshBranding }}>
      {children}
    </BrandingContext.Provider>
  )
}
