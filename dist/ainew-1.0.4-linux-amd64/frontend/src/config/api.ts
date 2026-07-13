// API URL: nginx proxy üzerinden /api/ — aynı origin, port farklılığı yok
// Bu sayede browser doğrudan 8000 portuna bağlanmak zorunda kalmaz
export const API_BASE_URL = (() => {
  // Build-time override (CI/CD ortamları için)
  const envUrl = import.meta.env.VITE_API_BASE_URL
  if (envUrl) return envUrl

  if (typeof window === 'undefined') {
    return 'http://localhost:8000/api/v1'
  }

  // Nginx proxy: same origin /api/v1
  return `${window.location.protocol}//${window.location.host}/api/v1`
})()
