import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { API_BASE_URL } from '../config/api'

export const DEFAULT_APP_NAME = 'ainew'

interface BrandingContextValue {
  appName: string
  logoUrl: string | null
  version: string
  /** Boş string = giriş ekranı kendi varsayılanını kullanır. */
  companyName: string
  tagline: string
  footerText: string
  /** Giriş ekranı sol panel başlığı / açıklaması. Boş string = arayüz varsayılanı. */
  heroTitle: string
  heroText: string
  loading: boolean
  refreshBranding: () => Promise<void>
}

const BrandingContext = createContext<BrandingContextValue>({
  appName: DEFAULT_APP_NAME,
  logoUrl: null,
  version: '',
  companyName: '',
  tagline: '',
  footerText: '',
  heroTitle: '',
  heroText: '',
  loading: true,
  refreshBranding: async () => {},
})

export const useBranding = () => useContext(BrandingContext)

export const BrandingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [appName, setAppName] = useState(DEFAULT_APP_NAME)
  const [hasLogo, setHasLogo] = useState(false)
  const [version, setVersion] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [tagline, setTagline] = useState('')
  const [footerText, setFooterText] = useState('')
  const [heroTitle, setHeroTitle] = useState('')
  const [heroText, setHeroText] = useState('')
  const [cacheBust, setCacheBust] = useState(0)
  const [loading, setLoading] = useState(true)

  const fetchBranding = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE_URL}/public/branding`)
      if (r.ok) {
        const data = await r.json()
        setAppName(data.app_name || DEFAULT_APP_NAME)
        setHasLogo(Boolean(data.has_logo))
        if (data.version) setVersion(String(data.version).replace(/^v/i, ''))
        setCompanyName(typeof data.company_name === 'string' ? data.company_name : '')
        setTagline(typeof data.tagline === 'string' ? data.tagline : '')
        setFooterText(typeof data.footer_text === 'string' ? data.footer_text : '')
        setHeroTitle(typeof data.hero_title === 'string' ? data.hero_title : '')
        setHeroText(typeof data.hero_text === 'string' ? data.hero_text : '')
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
    document.title = version ? `${appName} ${version}` : appName
  }, [appName, version])

  const logoUrl = hasLogo ? `${API_BASE_URL}/public/logo?v=${cacheBust}` : null

  return (
    <BrandingContext.Provider value={{ appName, logoUrl, version, companyName, tagline, footerText, heroTitle, heroText, loading, refreshBranding }}>
      {children}
    </BrandingContext.Provider>
  )
}
