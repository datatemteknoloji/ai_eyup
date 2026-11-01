import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k),
  readStoredLocale: () => 'tr',
}))

import UserManager from '../pages/UserManager'

const MODULES = [
  'executive', 'linux', 'windows', 'virtualization', 'exadata', 'openshift', 'ai_automation', 'integrations', 'level1',
  'applications', 'knowledge', 'custom_reports', 'monitoring', 'centrify', 'automation', 'hardware',
].map((id, i) => ({ id, name: id === 'hardware' ? 'Donanım' : id, description: '', icon: id === 'hardware' ? 'HardDrive' : 'Server', color: id === 'hardware' ? 'slate' : 'green', sort_order: i, is_active: true }))
const USERS = [
  { id: 1, username: 'admin', email: null, full_name: 'Yönetici', role: 'admin', is_active: true, last_login: null, created_at: null },
  { id: 2, username: 'op1', email: null, full_name: 'op1', role: 'operator', is_active: true, last_login: null, created_at: null },
]
const UMODS = [
  { user_id: 1, username: 'admin', full_name: null, role: 'admin', is_active: true, modules: [] },
  { user_id: 2, username: 'op1', full_name: null, role: 'operator', is_active: true, modules: ['linux'] },
]

function mockApi() {
  const puts: any[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
    const body = (j: any) => ({ ok: true, json: async () => j })
    if (init?.method === 'PUT') { puts.push({ url, body: JSON.parse(init.body) }); return body({ ok: true }) }
    if (url.endsWith('/auth/users')) return body({ users: USERS })
    if (url.endsWith('/modules/users')) return body(UMODS)
    if (url.endsWith('/modules/')) return body(MODULES)
    return body({})
  }))
  return puts
}

describe('Kullanıcı Yönetimi — modül yetkileri', () => {
  it('16 modülün TAMAMI yatay kaydırma gerektirmeden, satır içinde görünür (Donanım dahil)', async () => {
    mockApi()
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><UserManager /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByTestId('usr-mod-2-hardware')).toBeInTheDocument())
    for (const m of MODULES) expect(screen.getByTestId(`usr-mod-2-${m.id}`)).toBeInTheDocument()
    expect(screen.getByTestId('usr-mod-2-hardware').textContent).toContain('Donanım')
    expect(screen.getByTestId('usr-mod-2-linux')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('usr-mod-2-hardware')).toHaveAttribute('aria-pressed', 'false')
    // tablo artık modül başına sütun açmaz → yatay taşma yok
    expect(document.querySelectorAll('thead th').length).toBeLessThanOrEqual(3)
    // admin satırı: tek «tam erişim» etiketi, anahtar yok
    expect(screen.queryByTestId('usr-mod-1-hardware')).toBeNull()
  })

  it('Donanım yetkisi tek tıkla atanır (mevcut yetkiler korunur)', async () => {
    const puts = mockApi()
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><UserManager /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByTestId('usr-mod-2-hardware')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('usr-mod-2-hardware'))
    await waitFor(() => expect(puts.length).toBe(1))
    expect(puts[0].url).toContain('/modules/users/2')
    expect(puts[0].body.module_ids.sort()).toEqual(['hardware', 'linux'])
  })
})
