import { ComponentType, LazyExoticComponent, lazy } from 'react'

/** Vite/SPA deploy sonrası eski hash'li chunk 404 → tek seferlik soft reload. */
export function isChunkLoadError(err: unknown): boolean {
  const msg = String((err as Error)?.message || err || '').toLowerCase()
  const name = String((err as Error)?.name || '').toLowerCase()
  return (
    msg.includes('failed to fetch dynamically imported module') ||
    msg.includes('loading chunk') ||
    msg.includes('loading css chunk') ||
    msg.includes('importing a module script failed') ||
    msg.includes('error loading dynamically imported module') ||
    name.includes('chunkloaderror')
  )
}

const RELOAD_KEY = 'ainew.chunkReloadAt'

/** Aynı oturumda sonsuz reload döngüsünü engelle (15 sn). */
function maybeReloadForChunk(): boolean {
  try {
    const prev = Number(sessionStorage.getItem(RELOAD_KEY) || 0)
    if (Date.now() - prev < 15_000) return false
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
    window.location.reload()
    return true
  } catch {
    return false
  }
}

/** lazy() + chunk load hatasında otomatik sayfa yenileme. */
export function lazyWithRetry<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      return await factory()
    } catch (err) {
      if (isChunkLoadError(err) && maybeReloadForChunk()) {
        // Reload tetiklendi; React'e asılı promise ver (unmount olacak)
        return new Promise(() => {}) as Promise<{ default: T }>
      }
      throw err
    }
  })
}
