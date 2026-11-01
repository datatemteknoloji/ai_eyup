import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))
let role: string | null = 'admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => (role ? { user: { role } } : null),
}))

import PhysicalHostsPage from '../pages/PhysicalHostsPage'

let calls: { url: string; method: string; body: any }[] = []
const stub = (bmcStatus = 200, bmcBody: any = { ok: true }) => {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (u: string, init?: any) => {
    const url = String(u)
    const method = init?.method || 'GET'
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body) : undefined })
    if (url.includes('/hw/bmc/server-account')) return { ok: bmcStatus < 400, status: bmcStatus, json: async () => bmcBody }
    if (url.endsWith('/servers/') && method === 'POST') return { ok: true, status: 201, json: async () => ({ id: 42, name: 'p1' }) }
    return { ok: true, status: 200, json: async () => [] }
  }))
}
const wrap = () => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PhysicalHostsPage /></QueryClientProvider></MemoryRouter>,
)
const open = async () => { fireEvent.click(await screen.findByText('ph_new_host')) }
const fillBase = () => {
  const [name] = document.querySelectorAll('input[type="text"][required]')
  fireEvent.change(name, { target: { value: 'p1' } })
  const ip = document.querySelectorAll('input[type="text"][required]')[1]
  fireEvent.change(ip, { target: { value: '10.0.0.7' } })
}

beforeEach(() => { role = 'admin' })

describe('Fiziksel sunucu ekle — isteğe bağlı BMC', () => {
  it('BMC alanları boşsa yalnız sunucu oluşur; BMC çağrısı YOK', async () => {
    stub()
    wrap()
    await open()
    fillBase()
    fireEvent.click(screen.getByText('add'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/servers/') && c.method === 'POST')).toBe(true))
    await new Promise(r => setTimeout(r, 30))
    expect(calls.some(c => c.url.includes('/hw/bmc/'))).toBe(false)
  })

  it('IP + hesap girilirse sunucu oluşturulduktan sonra server-account çağrılır (yeni sunucu id\'siyle)', async () => {
    stub()
    wrap()
    await open()
    fillBase()
    fireEvent.change(screen.getByTestId('ph-bmc-ip'), { target: { value: ' 10.9.9.9 ' } })
    fireEvent.change(screen.getByTestId('ph-bmc-user'), { target: { value: 'ADMIN' } })
    fireEvent.change(screen.getByTestId('ph-bmc-pass'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByText('add'))
    await waitFor(() => expect(calls.some(c => c.url.includes('/hw/bmc/server-account'))).toBe(true))
    expect(calls.find(c => c.url.includes('/hw/bmc/server-account'))!.body).toEqual({ server_id: 42, bmc_ip: '10.9.9.9', username: 'ADMIN', password: 'pw' })
    // sıra: önce sunucu, sonra BMC
    const order = calls.filter(c => c.method === 'POST').map(c => (c.url.includes('/hw/bmc/') ? 'bmc' : 'server'))
    expect(order).toEqual(['server', 'bmc'])
  })

  it('kullanıcı adı ve parola birlikte girilmeli: yarım hesapta hiçbir istek atılmaz', async () => {
    stub()
    wrap()
    await open()
    fillBase()
    fireEvent.change(screen.getByTestId('ph-bmc-user'), { target: { value: 'ADMIN' } })
    fireEvent.click(screen.getByText('add'))
    expect((await screen.findByRole('alert')).textContent).toContain('ph_bmc_pair')
    expect(calls.some(c => c.method === 'POST')).toBe(false)
  })

  it('BMC kaydı başarısız olursa sunucu geri alınmaz; uyarı gösterilir', async () => {
    stub(422, { detail: 'Geçersiz BMC adresi' })
    wrap()
    await open()
    fillBase()
    fireEvent.change(screen.getByTestId('ph-bmc-ip'), { target: { value: 'bad host' } })
    fireEvent.click(screen.getByText('add'))
    const warn = await screen.findByTestId('ph-bmc-warn')
    expect(warn.textContent).toContain('Geçersiz BMC adresi')
    expect(calls.filter(c => c.url.endsWith('/servers/') && c.method === 'POST')).toHaveLength(1)
  })

  it('admin olmayan: BMC bölümü hiç görünmez', async () => {
    role = 'operator'
    stub()
    wrap()
    await open()
    expect(screen.queryByTestId('ph-bmc')).toBeNull()
  })
})
