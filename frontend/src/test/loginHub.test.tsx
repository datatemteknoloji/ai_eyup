import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => ({ login_hub_virt: 'Sanallaştırma', login_hub_physical: 'Fiziksel', login_hub_virtual: 'Sanal' } as Record<string, string>)[k] ?? k,
}))

import LoginHub from '../components/login/LoginHub'

const nodes = (c: HTMLElement) => Array.from(c.querySelectorAll('[data-node]')).map(n => n.getAttribute('data-node'))

describe('LoginHub diyagramı', () => {
  it('Linux/Windows ortak yapısı ve sanallaştırma alt dalları var; eski düz vSphere/OLVM üst düğümleri yok', () => {
    const { container } = render(<LoginHub appName="ainew" logoUrl={null} ariaLabel="x" />)
    const n = nodes(container)
    for (const id of ['linux', 'windows', 'exadata', 'virt', 'physical', 'virtual', 'hp', 'dell', 'vsphere', 'openshift', 'olvm'])
      expect(n).toContain(id)
    const txt = container.textContent || ''
    for (const w of ['Linux', 'Windows', 'Exadata', 'Sanallaştırma', 'Fiziksel', 'Sanal', 'HP', 'Dell', 'vSphere', 'OpenShift', 'OLVM', 'ainew'])
      expect(txt).toContain(w)
    // ortak yapı TEK kez (Linux ve Windows aynı çerçeveye iner)
    expect(container.querySelectorAll('[data-node="shared-frame"]').length).toBe(1)
    expect(container.querySelector('[data-line="linux-group"]')).toBeTruthy()
    expect(container.querySelector('[data-line="windows-group"]')).toBeTruthy()
  })

  it('HP ve Dell «Fiziksel»in bir üstündedir ve Fiziksel ikisine de bağlıdır', () => {
    const { container } = render(<LoginHub appName="ainew" logoUrl={null} ariaLabel="x" />)
    const y = (id: string) => Number(container.querySelector(`[data-node="${id}"] rect`)!.getAttribute('y'))
    expect(y('hp')).toBeLessThan(y('physical'))
    expect(y('dell')).toBeLessThan(y('physical'))
    expect(y('hp')).toBe(y('dell'))                                                   // aynı düzey
    expect(y('virtual')).toBe(y('physical'))                                          // Sanal, Fiziksel ile aynı düzeyde
    expect(container.querySelector('[data-line="physical-hp"]')).toBeTruthy()
    expect(container.querySelector('[data-line="physical-dell"]')).toBeTruthy()
    // Sanal, HP/Dell'e BAĞLI DEĞİL (yalnız sanallaştırmaya akar)
    expect(container.querySelector('[data-line="virtual-hp"]')).toBeNull()
  })

  it('«Sanal» tek bağlantı çubuğuyla sanallaştırma kümesinin tamamına bağlanır', () => {
    const { container } = render(<LoginHub appName="ainew" logoUrl={null} ariaLabel="x" />)
    expect(container.querySelectorAll('[data-line="vm-bar"]').length).toBe(1)          // tek çubuk
    expect(container.querySelectorAll('[data-line="vm-flow"]').length).toBe(1)         // tek akış çizgisi
    const bar = container.querySelector('[data-line="vm-bar"]')!
    const y1 = Number(bar.getAttribute('y1')), y2 = Number(bar.getAttribute('y2'))
    const ys = ['vsphere', 'openshift', 'olvm'].map(id => {
      const r = container.querySelector(`[data-node="${id}"] rect`)!
      return Number(r.getAttribute('y')) + Number(r.getAttribute('height')) / 2
    })
    for (const y of ys) {                                                                // çubuk üç alt dalın hepsini kapsar
      expect(y).toBeGreaterThanOrEqual(y1)
      expect(y).toBeLessThanOrEqual(y2)
      expect(container.querySelector(`[data-line="tick-${['vsphere', 'openshift', 'olvm'][ys.indexOf(y)]}"]`)).toBeTruthy()
    }
    // akış «Sanal» düğümünden başlar ve çubuğa biter
    const d = container.querySelector('[data-line="vm-flow"]')!.getAttribute('d')!
    const sanal = container.querySelector('[data-node="virtual"] rect')!
    expect(d.startsWith(`M${Number(sanal.getAttribute('x')) + Number(sanal.getAttribute('width'))},`)).toBe(true)
    expect(d.endsWith(`H${bar.getAttribute('x1')}`)).toBe(true)
  })

  it('giriş öncesi sayı/ölçüm göstermez', () => {
    const { container } = render(<LoginHub appName="ainew" logoUrl={null} ariaLabel="x" />)
    expect(/\d/.test((container.textContent || '').replace(/ainew/, ''))).toBe(false)
  })
})
