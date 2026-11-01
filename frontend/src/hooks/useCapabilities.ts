import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

/** Backend capability registry (GET /capabilities). Opsiyonel entegrasyon yoksa küme boş döner. */
export function useCapabilities() {
  const q = useQuery<{ capabilities: string[]; has_backup: boolean; demo_active?: boolean; has_hw?: boolean; hw_demo_active?: boolean; has_automic?: boolean; has_centrify?: boolean }>({
    queryKey: ['capabilities'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/capabilities`)
      if (!r.ok) return { capabilities: [], has_backup: false }
      return r.json()
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  })
  const caps = q.data?.capabilities ?? []
  // F.0: DEMO ("backup_demo") yalnız Yedekleme ekranını görünür kılar; gerçek 'backup' yeteneği değildir.
  const demoActive = !!q.data?.demo_active || caps.includes('backup_demo')
  // Donanım (OME/OneView): gerçek sağlayıcı yoksa menü/kart hiç görünmez; DEMO yalnız bayrak açıkken etiketli görünür.
  const hwDemoActive = !!q.data?.hw_demo_active || caps.includes('hw_demo')
  return {
    capabilities: caps,
    hasHw: caps.includes('hw') || hwDemoActive,
    hwDemoActive,
    hasBackup: caps.includes('backup') || demoActive,
    hasAutomic: !!q.data?.has_automic || caps.includes('automic'),
    hasCentrify: !!q.data?.has_centrify || caps.includes('centrify'),
    hasRealBackup: caps.includes('backup'),
    demoActive,
    isLoading: q.isLoading,
  }
}
