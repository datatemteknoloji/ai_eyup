export const API_BASE_URL = (() => {
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl) return envUrl

  if (typeof window === 'undefined') {
    return 'http://localhost:8000/api/v1'
  }

  const protocol = window.location.protocol
  const host = window.location.hostname
  const port = import.meta.env.VITE_API_PORT || '8000'
  return `${protocol}//${host}:${port}/api/v1`
})()
