import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { API_BASE_URL } from '../config/api'
import { getToken, setToken, clearToken } from './authStore'

export interface AuthUser {
  id: number
  username: string
  email: string | null
  full_name: string | null
  role: 'admin' | 'operator' | 'viewer'
  is_active: boolean
  last_login: string | null
  modules: string[]      // erişilebilir modül ID'leri
  is_admin: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  hasModule: (moduleId: string) => boolean
}

const AuthContext = createContext<AuthContextValue>(null as any)

export const useAuth = () => useContext(AuthContext)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchMe = useCallback(async () => {
    const token = getToken()
    if (!token) { setUser(null); return }
    try {
      const r = await fetch(`${API_BASE_URL}/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (r.ok) {
        const data = await r.json()
        // Ensure modules field exists (fallback for older backends)
        setUser({
          ...data,
          modules: data.modules ?? [],
          is_admin: data.is_admin ?? (data.role === 'admin'),
        })
      } else {
        clearToken(); setUser(null)
      }
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    fetchMe().finally(() => setLoading(false))
  }, [fetchMe])

  const login = useCallback(async (username: string, password: string) => {
    const r = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.detail || 'Giriş başarısız')
    }
    const data = await r.json()
    setToken(data.access_token)
    // login response'dan user geliyorsa onu kullan, yoksa fetchMe çağır
    if (data.user) {
      setUser({
        ...data.user,
        modules: data.user.modules ?? [],
        is_admin: data.user.is_admin ?? (data.user.role === 'admin'),
      })
    } else {
      await fetchMe()
    }
  }, [fetchMe])

  const logout = useCallback(async () => {
    const token = getToken()
    if (token) {
      fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      }).catch(() => {})
    }
    clearToken()
    setUser(null)
    window.location.href = '/login'
  }, [])

  /** Kullanıcının belirtilen modüle erişimi var mı? */
  const hasModule = useCallback((moduleId: string): boolean => {
    if (!user) return false
    if (user.is_admin || user.role === 'admin') return true
    return user.modules.includes(moduleId)
  }, [user])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh: fetchMe, hasModule }}>
      {children}
    </AuthContext.Provider>
  )
}
