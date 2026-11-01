import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, string>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))

import ServerEditPanel from '../components/ServerEditPanel'

let calls: { url: string; method: string; body: any }[] = []
let bmcState: any
const stub = (credBody: any = { success: true, ai_ready: true }) => {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (u: string, init?: any) => {
    const url = String(u)
    const method = init?.method || 'GET'
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body) : undefined })
    const ok = (j: any) => ({ ok: true, status: 200, json: async () => j })
    if (url.includes('/hw/bmc/server-account/') && method === 'GET') return ok(bmcState)
    if (url.includes('/hw/bmc/')) return ok({ ok: true })
    if (url.endsWith('/credentials')) return ok(credBody)
    return ok({ id: 7 })
  }))
}

const server = {
  id: 7, name: 'srv1', hostname: 'srv1.local', ip_address: '10.0.0.7', server_type: 'PHYSICAL',
  cpu_cores: 8, memory_gb: 32, ssh_username: 'root', connection_config: { username: 'root', port: 22, password: '********' },
}

const mount = (props: Partial<{ isAdmin: boolean; server: any }> = {}) => {
  const onSaved = vi.fn()
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ServerEditPanel server={props.server || server} isAdmin={props.isAdmin ?? true} onSaved={onSaved} onClose={onClose} />
    </QueryClientProvider>,
  )
  return { onSaved, onClose }
}

beforeEach(() => {
  bmcState = { ok: true, exists: false, endpoint_id: null, bmc_ip: null, ip_source: null, account: null, resolved: null, status: null, auth_halted: false }
})

describe('Linux sunucu düzenleme paneli', () => {
  it('değişiklik yoksa hiçbir istek atılmaz', async () => {
    stub()
    mount({ isAdmin: false })
    fireEvent.click(screen.getByTestId('se-save'))
    expect((await screen.findByTestId('se-msg')).textContent).toBe('se_no_changes')
    expect(calls.length).toBe(0)
  })

  it('yalnız DEĞİŞEN alanlar PUT edilir; connection_config asla gönderilmez', async () => {
    stub()
    const { onSaved } = mount({ isAdmin: false })
    fireEvent.change(screen.getByTestId('se-name'), { target: { value: 'srv-new' } })
    fireEvent.change(screen.getByTestId('se-mem'), { target: { value: '64' } })
    fireEvent.click(screen.getByTestId('se-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    const put = calls.find(c => c.method === 'PUT')!
    expect(put.url.endsWith('/servers/7')).toBe(true)
    expect(put.body).toEqual({ name: 'srv-new', memory_gb: 64 })
    expect(JSON.stringify(calls.map(c => c.body))).not.toContain('connection_config')
    expect(calls.some(c => c.url.endsWith('/credentials'))).toBe(false)
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ name: 'srv-new', memory_gb: 64 }))
  })

  it('boş ad kaydedilmez', async () => {
    stub()
    mount({ isAdmin: false })
    fireEvent.change(screen.getByTestId('se-name'), { target: { value: '  ' } })
    fireEvent.click(screen.getByTestId('se-save'))
    expect((await screen.findByRole('alert')).textContent).toBe('se_name_required')
    expect(calls.length).toBe(0)
  })

  it('SSH parolası girilirse /credentials çağrılır; boş alanlar gönderilmez; sonuç AI Ready gösterilir', async () => {
    stub({ success: true, ai_ready: true })
    mount({ isAdmin: false })
    fireEvent.change(screen.getByTestId('se-ssh-pass'), { target: { value: 'pw1' } })
    fireEvent.click(screen.getByTestId('se-save'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/servers/7/credentials'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/credentials'))!.body).toEqual({ password: 'pw1' })
    expect(calls.some(c => c.method === 'PUT')).toBe(false)
    expect((await screen.findByTestId('se-msg')).textContent).toBe('se_ssh_ok')
    expect((screen.getByTestId('se-ssh-pass') as HTMLInputElement).value).toBe('')
  })

  it('SSH bağlanamazsa uyarı gösterilir (bilgiler yine kaydedilmiştir)', async () => {
    stub({ success: true, ai_ready: false })
    mount({ isAdmin: false })
    fireEvent.change(screen.getByTestId('se-ssh-user'), { target: { value: 'ops' } })
    fireEvent.click(screen.getByTestId('se-save'))
    expect((await screen.findByRole('alert')).textContent).toBe('se_ssh_fail')
    expect(calls.find(c => c.url.endsWith('/credentials'))!.body).toEqual({ username: 'ops' })
  })

  it('operatör BMC bölümünü görmez, yalnız bilgi satırı görür; sanal sunucuda hiçbiri yok', () => {
    stub()
    mount({ isAdmin: false })
    expect(screen.queryByTestId('se-bmc')).toBeNull()
    expect(screen.getByTestId('se-bmc-admin-only')).toBeTruthy()
    expect(calls.some(c => c.url.includes('/hw/bmc'))).toBe(false)
  })

  it('sanal sunucuda BMC bölümü hiç çıkmaz', () => {
    stub()
    mount({ isAdmin: true, server: { ...server, server_type: 'VIRTUAL' } })
    expect(screen.queryByTestId('se-bmc')).toBeNull()
    expect(screen.queryByTestId('se-bmc-admin-only')).toBeNull()
  })
})

describe('Linux sunucu düzenleme paneli — BMC (admin)', () => {
  it('yeni hesap: kullanıcı+parola birlikte gerekir; yarım girişte istek yok', async () => {
    stub()
    mount()
    fireEvent.change(await screen.findByTestId('se-bmc-user'), { target: { value: 'ADMIN' } })
    fireEvent.click(screen.getByTestId('se-bmc-save'))
    expect((await screen.findByTestId('se-bmc-msg')).textContent).toBe('ph_bmc_pair')
    expect(calls.some(c => c.method === 'POST')).toBe(false)
  })

  it('IP + hesap girilince /hw/bmc/server-account çağrılır (parola yalnız girilince)', async () => {
    stub()
    mount()
    fireEvent.change(await screen.findByTestId('se-bmc-ip'), { target: { value: ' 10.9.9.9 ' } })
    fireEvent.change(screen.getByTestId('se-bmc-user'), { target: { value: 'ADMIN' } })
    fireEvent.change(screen.getByTestId('se-bmc-pass'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByTestId('se-bmc-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/hw/bmc/server-account'))).toBe(true))
    expect(calls.find(c => c.method === 'POST')!.body).toEqual({
      server_id: 7, bmc_ip: '10.9.9.9', username: 'ADMIN', password: 'pw', verify_tls: false,
    })
  })

  it('mevcut hesapta parola boş bırakılırsa null gider (mevcut korunur); test düğmesi uç nokta kimliğiyle çağrılır', async () => {
    bmcState = {
      ok: true, exists: true, endpoint_id: 55, bmc_ip: '10.1.1.1', ip_source: 'manual',
      account: { username: 'ro', has_password: true, verify_tls: false }, resolved: { username: 'ro', level: 'host', private: true },
      status: 'ok', auth_halted: false,
    }
    stub()
    mount()
    const user = await screen.findByTestId('se-bmc-user') as HTMLInputElement
    expect(user.value).toBe('ro')
    expect(screen.getByTestId('se-bmc-current').textContent).toContain('ro')
    fireEvent.change(user, { target: { value: 'ro2' } })
    fireEvent.click(screen.getByTestId('se-bmc-save'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true))
    expect(calls.find(c => c.method === 'POST')!.body).toMatchObject({ username: 'ro2', password: null, bmc_ip: '10.1.1.1' })
    // kaydedildikten sonra (dirty=false) test serbest
    await waitFor(() => expect((screen.getByTestId('se-bmc-test') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByTestId('se-bmc-test'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/hw/bmc/endpoints/55/test'))).toBe(true))
  })

  it('kimlik reddedilmişse durdurma uyarısı gösterilir', async () => {
    bmcState = {
      ok: true, exists: true, endpoint_id: 9, bmc_ip: '10.1.1.1', ip_source: 'discovered',
      account: null, resolved: { username: 'g', level: 'global', private: false }, status: 'auth_failed', auth_halted: true,
    }
    stub()
    mount()
    expect((await screen.findByTestId('se-bmc-halted')).textContent).toBe('se_bmc_halted')
  })
})
