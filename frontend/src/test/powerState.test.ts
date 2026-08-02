import { describe, it, expect } from 'vitest'
import { isPoweredOn, isVmOnline } from '../utils/powerState'

describe('isPoweredOn', () => {
  it('kabul eder: vCenter REST API formatı (POWERED_ON, upper+underscore)', () => {
    expect(isPoweredOn('POWERED_ON')).toBe(true)
  })

  it('kabul eder: vCenter SOAP QuickStats formatı (poweredOn, camelCase)', () => {
    // Bu tam olarak QA'da bulunan bug'ın senaryosu: backend "poweredOn" döndürüyordu,
    // frontend sadece "POWERED_ON" bekliyordu ve VM yanlışlıkla "Kapalı" gösteriliyordu.
    expect(isPoweredOn('poweredOn')).toBe(true)
  })

  it('kabul eder: Prometheus "up" ve "running" değerleri', () => {
    expect(isPoweredOn('up')).toBe(true)
    expect(isPoweredOn('running')).toBe(true)
  })

  it('reddeder: kapalı/bilinmeyen durumlar', () => {
    expect(isPoweredOn('poweredOff')).toBe(false)
    expect(isPoweredOn('POWERED_OFF')).toBe(false)
    expect(isPoweredOn('down')).toBe(false)
    expect(isPoweredOn(null)).toBe(false)
    expect(isPoweredOn(undefined)).toBe(false)
    expect(isPoweredOn('')).toBe(false)
  })

  it('baş/son boşlukları tolere eder', () => {
    expect(isPoweredOn('  poweredOn  ')).toBe(true)
  })
})

describe('isVmOnline', () => {
  it('status ONLINE ise power_state ne olursa olsun true döner', () => {
    expect(isVmOnline('ONLINE', undefined)).toBe(true)
    expect(isVmOnline('online', null)).toBe(true)
  })

  it('status OFFLINE ama power_state açık gösteriyorsa yine true döner (power_state öncelikli sinyal)', () => {
    expect(isVmOnline('OFFLINE', 'poweredOn')).toBe(true)
  })

  it('hem status hem power_state kapalıysa false döner', () => {
    expect(isVmOnline('OFFLINE', 'poweredOff')).toBe(false)
    expect(isVmOnline(undefined, undefined)).toBe(false)
  })

  it('status yoksa sadece power_state ile karar verir', () => {
    expect(isVmOnline(undefined, 'running')).toBe(true)
    expect(isVmOnline(undefined, 'shutdown')).toBe(false)
  })
})
