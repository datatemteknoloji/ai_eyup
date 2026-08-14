import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { API_BASE_URL } from '../config/api'
import { getToken } from '../auth/authStore'
import { useAuth } from '../auth/AuthContext'
import {
  dictionaries,
  formatMessage,
  type Locale,
  type TranslationKey,
} from './messages'

export const LOCALE_STORAGE_KEY = 'ainew_locale'
export const LOCALE_EVENT = 'ainew-locale'

type LocaleCtx = {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string
}

const Ctx = createContext<LocaleCtx | null>(null)

function parseLocale(raw: string | null | undefined): Locale | null {
  return raw === 'en' || raw === 'tr' ? raw : null
}

export function readStoredLocale(): Locale {
  return parseLocale(localStorage.getItem(LOCALE_STORAGE_KEY)) ?? 'tr'
}

function applyDocumentLang(locale: Locale) {
  document.documentElement.lang = locale
}

function broadcastLocale(locale: Locale) {
  localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  localStorage.setItem('dropt_locale', locale)
  applyDocumentLang(locale)
  window.dispatchEvent(new CustomEvent(LOCALE_EVENT, { detail: locale }))
}

const LocaleContext = Ctx

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { user, refresh } = useAuth()
  const [locale, setLocaleState] = useState<Locale>(() => {
    const initial = readStoredLocale()
    broadcastLocale(initial)
    return initial
  })

  const persist = useCallback(async (l: Locale) => {
    broadcastLocale(l)
    setLocaleState(l)
    const token = getToken()
    if (!token) return
    try {
      const res = await fetch(`${API_BASE_URL}/auth/preferences`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ locale: l }),
      })
      if (res.ok) await refresh()
    } catch {
      /* local locale still applied */
    }
  }, [refresh])

  useEffect(() => {
    const server = parseLocale(user?.locale)
    if (!server) return
    if (server !== locale) {
      broadcastLocale(server)
      setLocaleState(server)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync when profile locale changes
  }, [user?.locale])

  const setLocale = useCallback((l: Locale) => {
    void persist(l)
  }, [persist])

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const dict = dictionaries[locale] ?? dictionaries.tr
      const msg = dict[key] ?? dictionaries.tr[key] ?? key
      return vars ? formatMessage(msg, vars) : msg
    },
    [locale],
  )

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleCtx {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale outside LocaleProvider')
  return ctx
}

export function useT() {
  return useLocale().t
}
