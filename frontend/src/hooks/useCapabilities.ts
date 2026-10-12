import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

/** Backend capability registry (GET /capabilities). Opsiyonel entegrasyon yoksa küme boş döner. */
export function useCapabilities() {
  const q = useQuery<{ capabilities: string[]; has_backup: boolean }>({
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
  return { capabilities: caps, hasBackup: caps.includes('backup'), isLoading: q.isLoading }
}
