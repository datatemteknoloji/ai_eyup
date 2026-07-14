/** Entegrasyonlar modülünden envanter yazma istekleri için zorunlu başlık */
export const INVENTORY_SOURCE_HEADER = { 'X-Inventory-Source': 'integrations' } as const

export function inventoryHeaders(extra?: Record<string, string>): Record<string, string> {
  return { ...INVENTORY_SOURCE_HEADER, ...extra }
}
