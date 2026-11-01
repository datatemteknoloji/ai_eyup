import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const state = { hasHw: true }
vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: false, hasRealBackup: false, demoActive: false, hasHw: state.hasHw, hwDemoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k) }))

import HwServerCard from '../components/hardware/HwServerCard'
import HwBadge from '../components/hardware/HwBadge'
import IncidentHardwareCard from '../components/hardware/IncidentHardwareCard'
import { canAccessPath } from '../config/routeAccess'

const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const SERVER = {
  id: 1, health: 'critical', bmc_ip: '10.1.1.9', bmc_type: 'iDRAC', bmc_version: '5.10', model: 'PowerEdge R740', serial: 'ABC1234',
  form_factor: 'rack', enclosure_name: null, bay: null, warranty: { end_date: '2026-01-01', expired: true, days_remaining: -10 },
  web_url: 'https://ome.example', recent_alerts: [], manager: { name: 'OME', version: '4.7.0' }, collected_at: '2026-10-23T10:00:00Z',
}

function mockFetch(body: any, ok = true) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok, json: async () => body })))
}

describe('Donanım kartı (çekmece / host paneli)', () => {
  beforeEach(() => { state.hasHw = true; vi.unstubAllGlobals() })

  it('entegrasyon yoksa (capability yok) hiç istek atmaz ve render etmez', async () => {
    state.hasHw = false
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    wrap(<HwServerCard kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(f).not.toHaveBeenCalled()
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
  })

  it('eşleşme yoksa veya 403 ise render edilmez', async () => {
    mockFetch({ available: false, reason: 'no_match' })
    const { unmount } = wrap(<HwServerCard kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
    unmount()
    mockFetch({ detail: 'forbidden' }, false)
    wrap(<HwServerCard kind="server" id={2} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
  })

  it('eşleşme varsa alanları gösterir; konsol/güç düğmesi yoktur', async () => {
    mockFetch({ available: true, demo: false, server: SERVER })
    wrap(<HwServerCard kind="server" id={1} />)
    await waitFor(() => expect(screen.getByTestId('hw-server-card')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-server-card').textContent || ''
    expect(txt).toContain('10.1.1.9')
    expect(txt).toContain('ABC1234')
    expect(txt).toContain('hw_warranty_expired')
    expect(screen.queryByRole('button')).toBeNull()               // uzaktan konsol / güç / LED düğmesi YOK
    expect(screen.getByTestId('hw-health-critical')).toBeInTheDocument()
  })

  it('DEMO verisi etiketlenir ve konsol bağlantısı vermez', async () => {
    mockFetch({ available: true, demo: true, server: SERVER })
    wrap(<HwServerCard kind="esxi" id={3} />)
    await waitFor(() => expect(screen.getByTestId('hw-demo-banner')).toBeInTheDocument())
    expect(screen.queryByText(/hw_open_console/)).toBeNull()
  })
})

describe('Donanım rota erişimi', () => {
  const has = (mods: string[]) => (id: string) => mods.includes(id)
  it('/hardware yalnız hardware modülü (veya admin) ile', () => {
    expect(canAccessPath('/hardware', has(['linux', 'integrations']), false)).toBe(false)
    expect(canAccessPath('/hardware', has(['hardware']), false)).toBe(true)
    expect(canAccessPath('/hardware', has([]), true)).toBe(true)
  })
  it('/integrations/hardware yalnız admin', () => {
    expect(canAccessPath('/integrations/hardware', has(['integrations', 'hardware']), false)).toBe(false)
    expect(canAccessPath('/integrations/hardware', has([]), true)).toBe(true)
  })
})

describe('İki seviyeli yetki: kısıtlı (restricted) donanım kartı', () => {
  beforeEach(() => { state.hasHw = true; vi.unstubAllGlobals() })

  it('hardware modülü olmayan kullanıcıda BMC, seri ve konsol bağlantısı görünmez', async () => {
    const { bmc_ip, bmc_type, bmc_version, serial, web_url, manager, ...safe } = SERVER as any
    mockFetch({ available: true, demo: false, restricted: true, server: { ...safe, restricted: true } })
    wrap(<HwServerCard kind="server" id={1} />)
    await waitFor(() => expect(screen.getByTestId('hw-server-card')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-server-card').textContent || ''
    expect(txt).not.toContain('10.1.1.9')
    expect(txt).not.toContain('ABC1234')
    expect(txt).not.toContain('hw_col_bmc')
    expect(txt).not.toContain('hw_col_serial')
    expect(txt).not.toContain('hw_open_console')
    expect(txt).toContain('PowerEdge R740')                       // model / sağlık / garanti özeti kalır
    expect(screen.getByTestId('hw-health-critical')).toBeInTheDocument()
  })
})

describe('Liste rozeti (HwBadge)', () => {
  beforeEach(() => { state.hasHw = true; vi.unstubAllGlobals() })
  const items = {
    '1': { health: 'critical', critical_alerts: 2, connected: true, warranty_expired: false },
    '2': { health: 'ok', critical_alerts: 0, connected: true, warranty_expired: false },
    '3': { health: 'ok', critical_alerts: 0, connected: true, warranty_expired: true },
    '4': { health: 'warning', critical_alerts: 0, connected: true, warranty_expired: false },
  }
  it('yalnız sorun varken görünür (kritik / uyarı / garanti bitti); sağlıklıda gürültü yok', async () => {
    mockFetch({ enabled: true, items })
    wrap(<><HwBadge kind="server" id={1} /><HwBadge kind="server" id={2} /><HwBadge kind="server" id={3} /><HwBadge kind="server" id={4} /><HwBadge kind="server" id={99} /></>)
    await waitFor(() => expect(screen.getAllByTestId('hw-badge').length).toBe(3))
    const txt = screen.getAllByTestId('hw-badge').map(e => e.textContent)
    expect(txt).toEqual(expect.arrayContaining([expect.stringContaining('hw_badge_critical'), expect.stringContaining('hw_badge_warranty'), expect.stringContaining('hw_badge_warning')]))
  })
  it('entegrasyon yoksa istek atmaz, render etmez', async () => {
    state.hasHw = false
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    wrap(<HwBadge kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(f).not.toHaveBeenCalled()
    expect(screen.queryByTestId('hw-badge')).toBeNull()
  })
})

describe('Incident «İlgili donanım» kartı', () => {
  beforeEach(() => { state.hasHw = true; vi.unstubAllGlobals() })
  it('donanım olayı + etki alanı (VM, iş servisi, HA riski) gösterir; BMC/seri yok', async () => {
    mockFetch({ enabled: true, items: [{
      hw_server_id: 5, name: 'esx01-hw', vendor: 'dell', model: 'PowerEdge R740', health: 'critical', connected: true, enclosure: null,
      alerts: [{ severity: 'critical', message: 'PSU 1 failed' }],
      impact: { vm_count: 3, vm_powered_on: 2, services: [{ name: 'ERP', tier: 'critical', vm_count: 2 }], cluster: { name: 'PROD', hosts: 2, healthy_hosts: 1, ha_risk: true } },
    }] })
    wrap(<IncidentHardwareCard incidentId={7} />)
    await waitFor(() => expect(screen.getByTestId('incident-hw-card')).toBeInTheDocument())
    const txt = screen.getByTestId('incident-hw-card').textContent || ''
    expect(txt).toContain('esx01-hw')
    expect(txt).toContain('PSU 1 failed')
    expect(txt).toContain('ERP (critical)')
    expect(txt).toContain('hw_impact_ha_risk')
    expect(screen.getByTestId('hw-impact')).toBeInTheDocument()
  })
  it('ilgili donanım yoksa veya entegrasyon yoksa render edilmez', async () => {
    mockFetch({ enabled: true, items: [] })
    const { unmount } = wrap(<IncidentHardwareCard incidentId={7} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('incident-hw-card')).toBeNull()
    unmount()
    state.hasHw = false
    wrap(<IncidentHardwareCard incidentId={8} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('incident-hw-card')).toBeNull()
  })
})
