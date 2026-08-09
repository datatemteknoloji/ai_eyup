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

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'ainew_theme'

type ThemeCtx = {
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
}

function readStored(): Theme {
  return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user, refresh } = useAuth()
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = readStored()
    applyTheme(t)
    return t
  })

  const persist = useCallback(async (t: Theme) => {
    localStorage.setItem(STORAGE_KEY, t)
    applyTheme(t)
    setThemeState(t)
    const token = getToken()
    if (!token) return
    try {
      const res = await fetch(`${API_BASE_URL}/auth/preferences`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ theme: t }),
      })
      if (res.ok) await refresh()
    } catch {
      /* local theme still applied */
    }
  }, [refresh])

  // Prefer server preference when user loads / logs in
  useEffect(() => {
    const server = user?.theme
    if (server === 'light' || server === 'dark') {
      if (server !== theme) {
        localStorage.setItem(STORAGE_KEY, server)
        applyTheme(server)
        setThemeState(server)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only sync when user.theme changes
  }, [user?.theme])

  const setTheme = useCallback((t: Theme) => {
    void persist(t)
  }, [persist])

  const toggleTheme = useCallback(() => {
    void persist(theme === 'dark' ? 'light' : 'dark')
  }, [persist, theme])

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme outside ThemeProvider')
  return ctx
}
