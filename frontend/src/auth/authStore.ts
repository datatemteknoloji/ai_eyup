// Token saklama + global fetch interceptor.
// Tüm /api/v1 isteklerine otomatik Authorization başlığı ekler; 401'de oturumu kapatır.

const TOKEN_KEY = 'auth_token'

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

let installed = false

export function installFetchInterceptor() {
  if (installed) return
  installed = true

  const originalFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url =
      typeof input === 'string' ? input :
      input instanceof URL ? input.toString() :
      (input as Request).url || ''

    const isApi = url.includes('/api/v1')
    // Sadece login/token endpoint'i token gerektirmez; diğer /auth/* uçları (users, me, change-password) token ister
    const isLoginEndpoint = url.includes('/auth/token') || url.includes('/auth/login')

    if (isApi && !isLoginEndpoint) {
      const token = getToken()
      if (token) {
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined))
        if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
        init = { ...init, headers }
      }
    }

    const res = await originalFetch(input as any, init)

    // Oturum süresi dolmuş / geçersiz → login'e gönder (login uçları hariç).
    if (res.status === 401 && isApi && !isLoginEndpoint) {
      clearToken()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return res
  }
}
