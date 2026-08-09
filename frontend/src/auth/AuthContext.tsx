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
  auth_source?: 'local' | 'ad' | 'sso'
  last_login: string | null
  modules: string[]
  is_admin: boolean
  theme?: 'dark' | 'light'
}

export type LoginResult =
  | { mfa_required: false }
  | {
      mfa_required: true
      mfa_enrollment_required: boolean
      mfa_token: string
    }

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<LoginResult>
  completeMfaLogin: (mfaToken: string, code: string, enroll: boolean) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  hasModule: (moduleId: string) => boolean
}

const AuthContext = createContext<AuthContextValue>(null as any)

export const useAuth = () => useContext(AuthContext)

function applyUser(data: any): AuthUser {
  return {
    ...data,
    modules: data.modules ?? [],
    is_admin: data.is_admin ?? (data.role === 'admin'),
  }
}

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
        setUser(applyUser(await r.json()))
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

  const login = useCallback(async (username: string, password: string): Promise<LoginResult> => {
    setLoading(true)
    try {
      const r = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Giriş başarısız')
      }
      const data = await r.json()
      if (data.mfa_required) {
        return {
          mfa_required: true,
          mfa_enrollment_required: !!data.mfa_enrollment_required,
          mfa_token: data.mfa_token,
        }
      }
      setToken(data.access_token)
      if (data.user) setUser(applyUser(data.user))
      else await fetchMe()
      return { mfa_required: false }
    } finally {
      setLoading(false)
    }
  }, [fetchMe])

  const completeMfaLogin = useCallback(async (mfaToken: string, code: string, enroll: boolean) => {
    setLoading(true)
    try {
      const path = enroll ? '/auth/mfa/enroll/confirm' : '/auth/mfa/verify'
      const r = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfa_token: mfaToken, code }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(typeof err.detail === 'string' ? err.detail : 'MFA başarısız')
      }
      const data = await r.json()
      setToken(data.access_token)
      if (data.user) setUser(applyUser(data.user))
      else await fetchMe()
    } finally {
      setLoading(false)
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

  const hasModule = useCallback((moduleId: string): boolean => {
    if (!user) return false
    if (user.is_admin || user.role === 'admin') return true
    return user.modules.includes(moduleId)
  }, [user])

  return (
    <AuthContext.Provider value={{
      user, loading, login, completeMfaLogin, logout, refresh: fetchMe, hasModule,
    }}>
      {children}
    </AuthContext.Provider>
  )
}
