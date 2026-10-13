import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
const get = vi.fn()
const send = vi.fn()
let admin = true
vi.mock('../components/insights/insightsKit', () => ({
  apiGet: (...a: any[]) => get(...a),
  apiSend: (...a: any[]) => send(...a),
  useRole: () => ({ isAdmin: admin, isOperator: admin }),
}))

import PolicyOverrides from '../components/insights/PolicyOverrides'

const clusters = [
  { hypervisor_id: 1, hypervisor: 'vc01', cluster: 'PROD' },
  { hypervisor_id: 1, hypervisor: 'vc01', cluster: 'TEST' },
  { hypervisor_id: 2, hypervisor: 'vc02', cluster: 'X' },
]
const spec = {
  memory: { label: 'Memory', min: 50, max: 99, default: 85 },
  cpu: { label: 'CPU', min: 30, max: 99, default: 80 },
}

function mockApi(overrides: Record<string, Record<string, number>>, glob = { memory: 85, cpu: 80 }) {
  get.mockImplementation(async (_b: string, path: string) => {
    if (path.startsWith('/capacity/policy/overrides')) return { ok: true, overrides }
    return { ok: true, spec, values: glob }
  })
}

describe('E7 — cluster/instance eşik override arayüzü', () => {
  beforeEach(() => { get.mockReset(); send.mockReset().mockResolvedValue({ ok: true }); admin = true })

  it('değer kaynağını gösterir: cluster override > instance override > genel > varsayılan', async () => {
    mockApi({ '': { memory: 80 }, TEST: { memory: 95 } }, { memory: 85, cpu: 70 })
    render(<PolicyOverrides clusters={clusters} />)
    await waitFor(() => expect(screen.getByTestId('ov-src-memory').textContent).toBe('vi_ov_src_instance'))
    expect(screen.getByTestId('ov-src-cpu').textContent).toBe('vi_ov_src_global')           // global 70 ≠ varsayılan 80
    fireEvent.change(screen.getByTestId('ov-scope'), { target: { value: 'TEST' } })
    await waitFor(() => expect(screen.getByTestId('ov-src-memory').textContent).toBe('vi_ov_src_cluster'))
    expect((screen.getByTestId('ov-memory').querySelector('input') as HTMLInputElement).value).toBe('95')
    fireEvent.change(screen.getByTestId('ov-scope'), { target: { value: 'PROD' } })
    await waitFor(() => expect(screen.getByTestId('ov-src-memory').textContent).toBe('vi_ov_src_instance'))
    expect((screen.getByTestId('ov-memory').querySelector('input') as HTMLInputElement).value).toBe('80')
  })

  it('cluster seçimi yalnız seçili instance\'ın cluster\'larını listeler', async () => {
    mockApi({})
    render(<PolicyOverrides clusters={clusters} />)
    await waitFor(() => screen.getByTestId('ov-scope'))
    const opts = Array.from((screen.getByTestId('ov-scope') as HTMLSelectElement).options).map(o => o.value)
    expect(opts).toEqual(['', 'PROD', 'TEST'])
  })

  it('kaydet: yalnız miras alınandan farklı anahtarlar override olarak gönderilir', async () => {
    mockApi({})
    render(<PolicyOverrides clusters={clusters} />)
    await waitFor(() => screen.getByTestId('ov-scope'))
    fireEvent.change(screen.getByTestId('ov-scope'), { target: { value: 'TEST' } })
    const mem = screen.getByTestId('ov-memory').querySelector('input') as HTMLInputElement
    fireEvent.change(mem, { target: { value: '92' } })
    fireEvent.click(screen.getByText('vi_ov_save'))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(send.mock.calls[0].slice(0, 4)).toEqual(['virt-insights', '/capacity/policy/override', 'PUT',
      { hypervisor_id: 1, cluster: 'TEST', values: { memory: 92 } }])
  })

  it('kaldır: DELETE çağrısı cluster ve anahtarla yapılır', async () => {
    mockApi({ TEST: { memory: 95 } })
    render(<PolicyOverrides clusters={clusters} />)
    await waitFor(() => screen.getByTestId('ov-scope'))
    fireEvent.change(screen.getByTestId('ov-scope'), { target: { value: 'TEST' } })
    await waitFor(() => screen.getByTestId('ov-del-memory'))
    fireEvent.click(screen.getByTestId('ov-del-memory'))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(send.mock.calls[0][1]).toBe('/capacity/policy/override?hypervisor_id=1&key=memory&cluster=TEST')
    expect(send.mock.calls[0][2]).toBe('DELETE')
  })

  it('yönetici değilse alanlar kilitli, kaydet/kaldır yok', async () => {
    admin = false
    mockApi({ TEST: { memory: 95 } })
    render(<PolicyOverrides clusters={clusters} />)
    await waitFor(() => screen.getByTestId('ov-scope'))
    fireEvent.change(screen.getByTestId('ov-scope'), { target: { value: 'TEST' } })
    await waitFor(() => expect(screen.getByTestId('ov-src-memory').textContent).toBe('vi_ov_src_cluster'))
    expect((screen.getByTestId('ov-memory').querySelector('input') as HTMLInputElement).disabled).toBe(true)
    expect(screen.queryByTestId('ov-del-memory')).toBeNull()
    expect(screen.queryByText('vi_ov_save')).toBeNull()
    expect(screen.getByText('vi_ov_admin_only')).toBeTruthy()
  })
})
