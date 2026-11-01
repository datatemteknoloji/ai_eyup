import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, p?: Record<string, any>) => (p ? `${k}${JSON.stringify(p)}` : k),
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))
let role: string | null = 'admin'
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => (role ? { user: { role, modules: ['hardware'] } } : null),
}))

import { HwLogsTab } from '../components/hardware/HwLogsTab'
import { HwBmcTab } from '../components/hardware/HwBmcTab'
import BmcSettingsTab from '../components/hardware/BmcSettingsTab'

const wrap = (ui: React.ReactElement) => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider></MemoryRouter>,
)

const OVERVIEW = {
  ok: true, flags: { ipmi_inband: true, bmc_redfish: false },
  profiles: [
    { id: 1, name: 'Global', scope: 'global', vendor: null, username: 'ro', has_password: true, verify_tls: false },
    { id: 7, name: 'lab', scope: 'host', vendor: null, username: 'lab', has_password: true, verify_tls: true },
  ],
  counts: { total: 2, no_ip: 1, by_status: { auth_halted: 1, no_ip: 1 } },
  endpoints: [
    { id: 11, target: { kind: 'hw', id: 5, name: 'dl380-01' }, host_class: 'physical', vendor: 'hpe', bmc_ip: '10.0.0.5', ip_source: 'portal', enabled: true,
      resolved: { id: 1, name: 'Global', level: 'global', username: 'ro' }, status: 'auth_failed', auth_halted: true, last_error: 'HTTP 401', last_run_at: null, ipmi_status: 'no_sudo' },
    { id: 12, target: { kind: 'server', id: 9, name: 'lnx-9' }, host_class: 'physical', vendor: null, bmc_ip: null, ip_source: 'discovered', enabled: true,
      resolved: null, status: 'no_ip', auth_halted: false, last_error: null, last_run_at: null, ipmi_status: null },
  ],
}

let calls: { url: string; method: string; body: any }[] = []
const stub = (routes: Record<string, any>, errors: Record<string, [number, string]> = {}) => {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (u: string, init?: any) => {
    const url = String(u)
    const method = init?.method || 'GET'
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body) : undefined })
    for (const [k, [code, detail]] of Object.entries(errors)) if (url.includes(k)) return { ok: false, status: code, json: async () => ({ detail }) }
    const key = Object.keys(routes).find(k => url.includes(k))
    return { ok: true, status: 200, json: async () => (key ? routes[key] : {}) }
  }))
}

beforeEach(() => { role = 'admin' })

describe('Donanım Logları sekmesi', () => {
  const OV = {
    ok: true, enabled: true, available: true,
    items: [
      { id: 'l1', severity: 'critical', category: 'memory', source: 'ipmi_sel', message: 'Uncorrectable ECC', occurrences: 3, last_seen_at: '2026-10-27T10:00:00Z', host_class: 'physical', target: { kind: 'server', id: 1, name: 'lnx-1' } },
      { id: 'a2', severity: 'warning', category: 'psu', source: 'portal_alert', message: 'PSU redundancy lost', occurrences: 1, last_seen_at: '2026-10-27T09:00:00Z', host_class: 'chassis', target: { kind: 'enclosure', id: 2, name: 'encl-A' } },
    ],
    counts: { by_class: { physical: 1, chassis: 1 }, by_source: {}, by_severity: {} },
    sources: [
      { key: 'esxi_sel', enabled: false, entries: 0, hosts: 0 },
      { key: 'ipmi_sel', enabled: true, entries: 1, hosts: 1 },
      { key: 'bmc_redfish', enabled: false, entries: 0, hosts: 0 },
      { key: 'portal_alert', enabled: true, entries: 1, hosts: 1 },
    ],
    last_run_at: null, last_run_errors: 0,
  }

  it('satırlar, kaynak/sınıf çipleri; kapalı kaynak açıkça «kapalı»; sınıf tıklaması isteği değiştirir', async () => {
    stub({ '/hw/log-overview': OV })
    wrap(<HwLogsTab />)
    await waitFor(() => expect(screen.getAllByTestId('hw-logs-row')).toHaveLength(2))
    expect(screen.getByTestId('hw-logs-src-bmc_redfish').textContent).toContain('hwl_src_off')
    expect(screen.getByTestId('hw-logs-src-ipmi_sel').textContent).not.toContain('hwl_src_off')
    expect(screen.getByTestId('hw-logs-class-all').textContent).toContain('2')
    expect(screen.queryByTestId('hw-logs-class-esxi')).toBeNull()
    fireEvent.click(screen.getByTestId('hw-logs-class-chassis'))
    await waitFor(() => expect(calls.slice(-1)[0].url).toContain('host_class=chassis'))
    fireEvent.click(screen.getByTestId('hw-logs-src-ipmi_sel'))
    await waitFor(() => expect(calls.slice(-1)[0].url).toContain('source=ipmi_sel'))
  })

  it('hiç log kaynağı açık değilse ve kayıt yoksa nedeni söyler (boş ≠ sağlıklı)', async () => {
    stub({ '/hw/log-overview': { ...OV, items: [], enabled: true, available: false, sources: OV.sources.map(s => ({ ...s, enabled: s.key === 'portal_alert', entries: 0 })) } })
    wrap(<HwLogsTab />)
    await waitFor(() => expect(screen.getByTestId('hw-logs-disabled')).toBeInTheDocument())
    expect(screen.queryByTestId('hw-logs-row')).toBeNull()
  })

  it('kaynak açık ama kayıt yoksa «boş» mesajı (devre dışı değil)', async () => {
    stub({ '/hw/log-overview': { ...OV, items: [], available: false } })
    wrap(<HwLogsTab />)
    await waitFor(() => expect(screen.getByTestId('hw-logs-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('hw-logs-disabled')).toBeNull()
  })
})

describe('BMC sekmesi', () => {
  it('admin: satırlar, çözümlenen kimlik, auth_halted rozeti, bayrak durumu', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    expect(screen.getByTestId('hwb-flag-ipmi').textContent).toBe('hwl_src_on')
    expect(screen.getByTestId('hwb-flag-redfish').textContent).toBe('hwl_src_off')
    expect(screen.getByTestId('hwb-status-badge-auth_halted')).toBeInTheDocument()
    expect(screen.getAllByTestId('hwb-cred')[0].textContent).toContain('ro')
    expect(screen.getAllByTestId('hwb-cred')[1].textContent).toContain('hwb_no_cred')
    expect(document.body.textContent).not.toMatch(/secret|"password"/)
  })

  it('durum çipi satırları süzer', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getByTestId('hwb-status-no_ip'))
    expect(screen.getAllByTestId('hwb-row')).toHaveLength(1)
  })

  it('admin: IP elle girilir (PUT bmc_ip), «sil» boş string gönderir', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW, '/hw/bmc/endpoints/12': { ok: true } })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('hwb-ip-edit')[1])
    fireEvent.change(screen.getByTestId('hwb-ip-input'), { target: { value: ' 10.1.1.1 ' } })
    fireEvent.click(screen.getByTestId('hwb-ip-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT' && c.url.endsWith('/endpoints/12'))).toBe(true))
    expect(calls.find(c => c.method === 'PUT')!.body).toEqual({ bmc_ip: '10.1.1.1' })
  })

  it('test butonu tek istek atar; 429 bekleme mesajı satırda görünür', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW }, { '/endpoints/11/test': [429, 'Çok sık deneme'] })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('hwb-test')[0])
    await waitFor(() => expect(screen.getByTestId('hwb-test-msg').textContent).toContain('Çok sık deneme'))
    expect(calls.filter(c => c.url.includes('/test'))).toHaveLength(1)
  })

  it('IP yok / kimlik yok satırında test butonu devre dışı', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    expect(screen.getAllByTestId('hwb-test')[1]).toBeDisabled()
  })

  it('toplu seçim: profil ata → /endpoints/bulk {ids, profile_id}', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW, '/endpoints/bulk': { ok: true } })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('hwb-check')[0])
    fireEvent.click(screen.getAllByTestId('hwb-check')[1])
    const bar = await screen.findByTestId('hwb-bulk')
    fireEvent.change(bar.querySelector('select')!, { target: { value: '7' } })
    fireEvent.click(screen.getByTestId('hwb-bulk-apply'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/endpoints/bulk'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/endpoints/bulk'))!.body).toEqual({ ids: [11, 12], profile_id: 7 })
  })

  it('admin olmayan: yazma denetimleri yok (düzenle/test/toplu/yeni profil)', async () => {
    role = 'viewer'
    stub({ '/hw/bmc/overview': OVERVIEW })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    expect(screen.queryByTestId('hwb-ip-edit')).toBeNull()
    expect(screen.queryByTestId('hwb-test')).toBeNull()
    expect(screen.queryByTestId('hwb-check')).toBeNull()
    expect(screen.queryByTestId('hwb-new-profile')).toBeNull()
    expect(screen.getAllByTestId('hwb-enabled')[0]).toBeDisabled()
  })

  it('host profili ekleme: parola gövdede, alanlar boşken kaydet devre dışı', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW, '/hw/bmc/profiles': { ok: true } })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getByTestId('hwb-new-profile')).toBeInTheDocument())
    expect(screen.getByTestId('hwb-np-save')).toBeDisabled()
    const inputs = screen.getByTestId('hwb-new-profile').querySelectorAll('input')
    fireEvent.change(inputs[0], { target: { value: 'lab2' } })
    fireEvent.change(inputs[1], { target: { value: 'root' } })
    fireEvent.change(inputs[2], { target: { value: 'pw' } })
    fireEvent.click(screen.getByTestId('hwb-np-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/hw/bmc/profiles'))).toBe(true))
    expect(calls.find(c => c.method === 'POST')!.body).toMatchObject({ scope: 'host', name: 'lab2', username: 'root', password: 'pw', verify_tls: false })
  })
})

describe('BMC sekmesi — makineye özel hesap', () => {
  const OV2 = {
    ...OVERVIEW,
    endpoints: [
      { ...OVERVIEW.endpoints[0], id: 21, target: { kind: 'server', id: 3, name: 'own-1' }, profile_id: 70,
        resolved: { id: 70, name: 'endpoint:21', level: 'host', private: true, username: 'root' },
        account: { username: 'root', has_password: true, verify_tls: false }, auth_halted: false, status: 'ok' },
      { ...OVERVIEW.endpoints[1], id: 22, target: { kind: 'server', id: 4, name: 'bare-2' }, account: null },
    ],
  }

  it('özel hesap «bu makineye özel» etiketiyle görünür; parola alanı boş ve «mevcut korunur» ipucu taşır', async () => {
    stub({ '/hw/bmc/overview': OV2 })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    expect(screen.getAllByTestId('hwb-cred')[0].textContent).toContain('hwb_level_private')
    fireEvent.click(screen.getAllByTestId('hwb-acct-edit')[0])
    expect((screen.getByTestId('hwb-acct-user') as HTMLInputElement).value).toBe('root')
    const pass = screen.getByTestId('hwb-acct-pass') as HTMLInputElement
    expect(pass.value).toBe('')
    expect(pass.placeholder).toBe('hwi_pass_keep')
    expect(screen.getByTestId('hwb-acct-save')).not.toBeDisabled()        // mevcut parola korunacağı için boş parola yeter
  })

  it('hesapsız satırda yeni hesap: kullanıcı+parola gerekir; PUT /endpoints/{id}/account gövdesi doğru', async () => {
    stub({ '/hw/bmc/overview': OV2, '/endpoints/22/account': { ok: true } })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('hwb-acct-edit')[1])
    expect(screen.getByTestId('hwb-acct-save')).toBeDisabled()
    fireEvent.change(screen.getByTestId('hwb-acct-user'), { target: { value: ' ADMIN ' } })
    expect(screen.getByTestId('hwb-acct-save')).toBeDisabled()            // parola yok
    fireEvent.change(screen.getByTestId('hwb-acct-pass'), { target: { value: 'pw1' } })
    fireEvent.click(screen.getByTestId('hwb-acct-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT' && c.url.endsWith('/endpoints/22/account'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/endpoints/22/account'))!.body).toEqual({ username: 'ADMIN', password: 'pw1', verify_tls: false })
  })

  it('«Hesabı sil» onaydan sonra {clear:true} gönderir; hesapsız satırda bu düğme yok', async () => {
    stub({ '/hw/bmc/overview': OV2, '/endpoints/21/account': { ok: true } })
    vi.stubGlobal('confirm', () => true)
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('hwb-acct-edit')[1])
    expect(screen.queryByTestId('hwb-acct-clear')).toBeNull()
    fireEvent.click(screen.getAllByTestId('hwb-acct-edit')[0])
    fireEvent.click(screen.getByTestId('hwb-acct-clear'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/endpoints/21/account'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/endpoints/21/account'))!.body).toEqual({ clear: true })
  })

  it('admin olmayan «Hesap» düğmesini görmez', async () => {
    role = 'viewer'
    stub({ '/hw/bmc/overview': OV2 })
    wrap(<HwBmcTab />)
    await waitFor(() => expect(screen.getAllByTestId('hwb-row')).toHaveLength(2))
    expect(screen.queryByTestId('hwb-acct-edit')).toBeNull()
  })
})

describe('Ayarlar → BMC', () => {
  it('parola önceden doldurulmaz; boş parolayla kayıtlı profil güncellenebilir; global gövdesi scope=global', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW, '/hw/bmc/profiles': { ok: true } })
    wrap(<BmcSettingsTab />)
    await waitFor(() => expect((screen.getByTestId('bmcset-global-user') as HTMLInputElement).value).toBe('ro'))
    expect((screen.getByTestId('bmcset-global-pass') as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('bmcset-global-save')).not.toBeDisabled()
    expect(screen.getByTestId('bmcset-dell-save')).toBeDisabled()          // kayıtsız + parola yok
    fireEvent.click(screen.getByTestId('bmcset-global-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true))
    expect(calls.find(c => c.method === 'POST')!.body).toMatchObject({ scope: 'global', username: 'ro', password: '' })
  })

  it('Dell kartı vendor=dell gönderir; TLS kapalıyken uyarı gösterilir', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW, '/hw/bmc/profiles': { ok: true } })
    wrap(<BmcSettingsTab />)
    await waitFor(() => expect(screen.getByTestId('bmcset-dell')).toBeInTheDocument())
    expect(screen.getByTestId('bmcset-dell').textContent).toContain('bmcset_tls_warn')
    fireEvent.change(screen.getByTestId('bmcset-dell-user'), { target: { value: 'idrac' } })
    fireEvent.change(screen.getByTestId('bmcset-dell-pass'), { target: { value: 'x' } })
    fireEvent.click(screen.getByTestId('bmcset-dell-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true))
    expect(calls.find(c => c.method === 'POST')!.body).toMatchObject({ scope: 'vendor', vendor: 'dell', username: 'idrac', password: 'x' })
  })

  it('sunucu hatası kartta gösterilir', async () => {
    stub({ '/hw/bmc/overview': OVERVIEW }, { '/hw/bmc/profiles': [422, 'Kullanıcı adı gerekli'] })
    wrap(<BmcSettingsTab />)
    await waitFor(() => expect((screen.getByTestId('bmcset-global-user') as HTMLInputElement).value).toBe('ro'))
    fireEvent.click(screen.getByTestId('bmcset-global-save'))
    await waitFor(() => expect(screen.getByTestId('bmcset-global').textContent).toContain('Kullanıcı adı gerekli'))
  })
})
