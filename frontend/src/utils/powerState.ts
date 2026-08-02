/**
 * Sunucu/VM güç durumu normalizasyonu.
 *
 * Farklı kaynaklar farklı formatlarda "açık" değeri döner:
 * - vCenter SOAP QuickStats:  "poweredOn"   (camelCase)
 * - vCenter REST API:         "POWERED_ON"  (upper + underscore)
 * - Prometheus `up` metriği:  "up" / "1"
 * - Genel durum metni:        "running"
 *
 * Bu farklı formatlar daha önce Servers.tsx ve Hypervisors.tsx içinde ayrı ayrı
 * (ve bir noktada eksik) karşılaştırılıyordu; bu da POWERED_ON bir VM'in
 * "Kapalı" görünmesine yol açan bir bug'a sebep oldu (bkz. QA raporu 2026-08-02).
 * Tüm karşılaştırmalar artık tek bu fonksiyondan geçiyor.
 */
const POWERED_ON_VALUES = new Set(['powered_on', 'poweredon', 'up', 'running', '1'])

export function isPoweredOn(state: string | null | undefined): boolean {
  if (!state) return false
  return POWERED_ON_VALUES.has(state.trim().toLowerCase())
}

/**
 * Bir VM/hypervisor kaydının "açık" olup olmadığını, hem ayrık `status` alanına
 * (örn. "ONLINE"/"OFFLINE") hem de serbest metin `power_state`/`vm_power_state`
 * alanına bakarak belirler. Hypervisors.tsx içinde bu kontrol 6 farklı yerde
 * birbirinden hafif farklı biçimlerde (bazısı 'running' içeriyor, bazısı yalnızca
 * 'on' alt dizesine bakıyor) tekrarlanıyordu — tek bir yerden yönetilir.
 */
export function isVmOnline(status: string | null | undefined, powerState: string | null | undefined): boolean {
  if (status && status.toUpperCase() === 'ONLINE') return true
  if (!powerState) return false
  const normalized = powerState.trim().toLowerCase()
  return isPoweredOn(normalized) || normalized.includes('on')
}
