import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { fmtResource, LOAD_COLORS, RESOURCE_ACCENT, ResourceGauge } from './ResourceCharts'

/** `/hypervisors/capacity-overview` yanıtı. Envanter (vCPU/RAM) ve fiziksel (host) kapasite, kaynak bazında. */
export type InventorySource = {
  key: string; kind: string; label: string; type: string; type_label: string; demo: boolean
  servers: number; cpu_cores: number; memory_gb: number
  /** Durum dökümü (servers.status): açık / kapalı / uyarı+kritik. Eski yanıtlarda yok. */
  online?: number; offline?: number; attention?: number
}
export type PhysicalSource = {
  hypervisor_id: number; name: string; type: string; type_label: string; demo: boolean
  hosts: number; cpu_cores: number; cpu_total_ghz: number | null; cpu_used_ghz: number | null; cpu_pct: number | null
  mem_total_gb: number | null; mem_used_gb: number | null; mem_pct: number | null
  storage_total_gb: number | null; storage_used_gb: number | null; storage_pct: number | null; datastores: number
}
type PhysicalTotal = Omit<PhysicalSource, 'hypervisor_id' | 'name' | 'type' | 'type_label' | 'demo' | 'datastores'> & { hypervisors: number }
export type CapacityOverview = {
  inventory: {
    sources: InventorySource[]
    total: { servers: number; cpu_cores: number; memory_gb: number }
    total_real: { servers: number; cpu_cores: number; memory_gb: number }
  }
  physical: { sources: PhysicalSource[]; total: PhysicalTotal; total_real: PhysicalTotal }
  has_demo: boolean
}

export function useCapacityOverview(enabled = true) {
  return useQuery<CapacityOverview>({
    queryKey: ['capacity-overview'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/capacity-overview`)
      if (!r.ok) throw new Error('capacity-overview')
      return r.json()
    },
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

const nf = (n: number, digits = 0) => n.toLocaleString('tr-TR', { maximumFractionDigits: digits })

function barColor(pct: number | null, accent: string): string {
  if (pct == null) return 'transparent'
  return pct >= 90 ? LOAD_COLORS.crit : pct >= 75 ? LOAD_COLORS.warn : accent
}

function DemoBadge() {
  const t = useT()
  return <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-fuchsia-500/15 text-fuchsia-400 border border-fuchsia-500/30 shrink-0">{t('cap_demo')}</span>
}

/** Tek satır: ad (+DEMO) · çubuk · sağda değer; altta açıklama. `pct` yoksa «veri yok». */
export function BreakdownRow({ label, demo, typeLabel, pct, accent, value, sub }: {
  label: string; demo?: boolean; typeLabel?: string; pct: number | null; accent: string; value: ReactNode; sub?: ReactNode
}) {
  const t = useT()
  return (
    <li className={demo ? 'opacity-70' : ''}>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1.5 min-w-0">
          <span className="text-slate-200 truncate" title={label}>{label}</span>
          {demo && <DemoBadge />}
        </span>
        <span className="text-white font-medium tabular-nums shrink-0">{pct == null && value == null ? t('cap_no_data') : value}</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-1">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct ?? 0)}%`, background: barColor(pct, accent) }} />
      </div>
      {(sub || typeLabel) && <div className="text-[10px] text-slate-500 mt-0.5">{[typeLabel, sub].filter(Boolean).join(' · ')}</div>}
    </li>
  )
}

/**
 * «Toplam CPU/Bellek nereden geliyor?» — `servers` envanterinin vCPU/RAM toplamı, kaynak bazında.
 * `onlyHypervisors`: sanallaştırma sayfası (Linux/Windows hypervisor dışı satırlar gizli).
 */
export function InventoryBreakdownCard({ data, metric, onlyHypervisors = false }: {
  data: CapacityOverview | undefined; metric: 'cpu' | 'memory'; onlyHypervisors?: boolean
}) {
  const t = useT()
  if (!data) return null
  const accent = metric === 'cpu' ? RESOURCE_ACCENT.cpu : RESOURCE_ACCENT.memory
  const rows = data.inventory.sources.filter(s => !onlyHypervisors || s.kind === 'hypervisor')
  const val = (s: { cpu_cores: number; memory_gb: number }) => (metric === 'cpu' ? s.cpu_cores : s.memory_gb)
  const sum = (items: typeof rows) => items.reduce((acc, s) => acc + val(s), 0)
  const total = sum(rows)
  const real = sum(rows.filter(s => !s.demo))
  const unit = metric === 'cpu' ? 'vCPU' : 'GB'
  const fmt = (n: number) => (metric === 'cpu' ? `${nf(n)} ${unit}` : fmtResource(n, 'GB'))
  const hasDemo = rows.some(s => s.demo)
  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5" data-testid={`cap-inv-${metric}`}>
      <h3 className="text-sm font-medium text-white">{t(metric === 'cpu' ? 'cap_src_cpu' : 'cap_src_mem')}</h3>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">{t('cap_inv_hint')}</p>
      <ul className="space-y-2.5">
        {rows.map(s => (
          <BreakdownRow
            key={s.key}
            label={s.label}
            demo={s.demo}
            typeLabel={s.type_label || undefined}
            pct={total > 0 ? (val(s) / total) * 100 : 0}
            accent={accent}
            value={`${fmt(val(s))} · %${nf(total > 0 ? (val(s) / total) * 100 : 0)}`}
            sub={t('cap_servers_n', { n: nf(s.servers) })}
          />
        ))}
      </ul>
      <div className="flex justify-between text-xs mt-3 pt-3 border-t border-white/[0.06]">
        <span className="text-slate-400">{t('cap_total')}</span>
        <span className="text-white font-semibold tabular-nums">{fmt(total)}</span>
      </div>
      {hasDemo && (
        <div className="flex justify-between text-xs mt-1">
          <span className="text-slate-400">{t('cap_total_real')}</span>
          <span className="text-white font-semibold tabular-nums">{fmt(real)}</span>
        </div>
      )}
    </div>
  )
}

/**
 * KPI kartının üzerine gelince açılan kaynak dökümü (fare + klavye odağı). Kart `tip` boşsa olduğu gibi çizilir.
 * `align`: kart ekranın sağ yarısındaysa `right` (balon kartın sağ kenarına hizalanır, taşmaz).
 */
export function HoverTip({ tip, align = 'left', testId, children }: {
  tip: ReactNode; align?: 'left' | 'right'; testId?: string; children: ReactNode
}) {
  if (!tip) return <>{children}</>
  return (
    <div className="relative group/tip outline-hidden *:first:h-full" tabIndex={0} data-testid={testId}>
      {children}
      <div
        role="tooltip"
        data-testid={testId ? `${testId}-tip` : undefined}
        className={`pointer-events-none absolute top-full z-50 mt-2 hidden w-80 max-w-[90vw] rounded-xl border border-white/10 bg-slate-900/95 p-3 shadow-xl backdrop-blur-sm group-hover/tip:block group-focus-within/tip:block ${align === 'right' ? 'right-0' : 'left-0'}`}
      >
        {tip}
      </div>
    </div>
  )
}

const TIP_MAX_ROWS = 12

/** Döküm balonu: başlık + (ad · değer) satırları + toplam. Satır sayısı sınırlıdır (+N daha). */
function TipList({ title, rows, totalLabel, totalValue, extra }: {
  title: string
  rows: { key: string; label: string; sub?: string; demo?: boolean; value: ReactNode }[]
  totalLabel: string; totalValue: ReactNode
  extra?: { label: string; value: ReactNode }
}) {
  const t = useT()
  const shown = rows.slice(0, TIP_MAX_ROWS)
  const rest = rows.length - shown.length
  return (
    <div className="text-xs">
      <div className="text-[11px] font-medium text-slate-300 mb-2">{title}</div>
      <ul className="space-y-1.5">
        {shown.map(r => (
          <li key={r.key} className={`flex items-start justify-between gap-3 ${r.demo ? 'opacity-70' : ''}`}>
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="text-slate-200 truncate" title={r.label}>{r.label}</span>
                {r.demo && <DemoBadge />}
              </span>
              {r.sub && <span className="block text-[10px] text-slate-500">{r.sub}</span>}
            </span>
            <span className="text-white font-medium tabular-nums shrink-0">{r.value}</span>
          </li>
        ))}
      </ul>
      {rest > 0 && <div className="text-[10px] text-slate-500 mt-1.5">{t('cap_tip_more', { n: rest })}</div>}
      <div className="flex justify-between mt-2.5 pt-2 border-t border-white/[0.08]">
        <span className="text-slate-400">{totalLabel}</span>
        <span className="text-white font-semibold tabular-nums">{totalValue}</span>
      </div>
      {extra && (
        <div className="flex justify-between mt-1">
          <span className="text-slate-400">{extra.label}</span>
          <span className="text-white font-semibold tabular-nums">{extra.value}</span>
        </div>
      )}
    </div>
  )
}

/**
 * «1563 sunucu / 7958 CPU / 30467 GB nereden geliyor?» balonu — `servers` envanterinin kaynak bazında dökümü
 * (hypervisor başına VM'ler + hypervisor dışı Linux/Windows). `onlyHypervisors`: sanallaştırma sayfası.
 */
export function InventoryTip({ data, metric, onlyHypervisors = false }: {
  data: CapacityOverview | undefined; metric: 'servers' | 'cpu' | 'memory'; onlyHypervisors?: boolean
}) {
  const t = useT()
  if (!data) return null
  const rows = data.inventory.sources.filter(s => !onlyHypervisors || s.kind === 'hypervisor')
  if (rows.length === 0) return null
  const val = (s: { servers: number; cpu_cores: number; memory_gb: number }) =>
    metric === 'servers' ? s.servers : metric === 'cpu' ? s.cpu_cores : s.memory_gb
  const fmt = (n: number) => (metric === 'servers' ? nf(n) : metric === 'cpu' ? `${nf(n)} vCPU` : fmtResource(n, 'GB'))
  const sum = (items: typeof rows) => items.reduce((acc, s) => acc + val(s), 0)
  const hasDemo = rows.some(s => s.demo)
  const title = t(metric === 'servers' ? 'cap_src_servers' : metric === 'cpu' ? 'cap_src_cpu' : 'cap_src_mem')
  return (
    <TipList
      title={title}
      rows={rows.map(s => ({
        key: s.key, label: s.label, demo: s.demo, value: fmt(val(s)),
        sub: [s.type_label, metric === 'servers' ? undefined : t('cap_servers_n', { n: nf(s.servers) })].filter(Boolean).join(' · ') || undefined,
      }))}
      totalLabel={t('cap_total')} totalValue={fmt(sum(rows))}
      extra={hasDemo ? { label: t('cap_total_real'), value: fmt(sum(rows.filter(s => !s.demo))) } : undefined}
    />
  )
}

/** Balon içeriği: veri yok / döküm boşsa `null` (HoverTip boş kutu açmaz). */
export function inventoryTip(data: CapacityOverview | undefined, metric: 'servers' | 'cpu' | 'memory', onlyHypervisors = false): ReactNode {
  if (!data || data.inventory.sources.filter(s => !onlyHypervisors || s.kind === 'hypervisor').length === 0) return null
  return <InventoryTip data={data} metric={metric} onlyHypervisors={onlyHypervisors} />
}

/** Hypervisor KPI balonu: tanımlı hypervisor adları (+ tür ve varsa host sayısı). */
export function HypervisorNamesTip({ hypervisors, data, typeLabel }: {
  hypervisors: { id?: number; name: string; type?: string }[]
  data?: CapacityOverview
  typeLabel?: (type: string) => string
}) {
  const t = useT()
  if (hypervisors.length === 0) return null
  const phys = new Map((data?.physical.sources ?? []).map(s => [s.name, s]))
  const demo = new Set((data?.inventory.sources ?? []).filter(s => s.demo).map(s => s.label))
  return (
    <TipList
      title={t('cap_tip_hv_title')}
      rows={hypervisors.map(h => {
        const p = phys.get(h.name)
        return {
          key: String(h.id ?? h.name), label: h.name, demo: demo.has(h.name),
          sub: (typeLabel ? typeLabel((h.type || '').toLowerCase()) : (p?.type_label || h.type)) || undefined,
          value: p ? t('cap_tip_hosts_n', { n: nf(p.hosts) }) : '',
        }
      })}
      totalLabel={t('cap_total')} totalValue={nf(hypervisors.length)}
    />
  )
}

type Basis = 'cpu' | 'memory' | 'storage'

function physicalCell(s: PhysicalSource | PhysicalTotal, basis: Basis, t: ReturnType<typeof useT>) {
  if (basis === 'cpu') {
    const sub = s.cpu_total_ghz != null
      ? `${nf(s.cpu_used_ghz ?? 0, 1)} / ${nf(s.cpu_total_ghz, 1)} GHz`
      : t('cap_cores_n', { n: nf(s.cpu_cores) })
    return { pct: s.cpu_pct, sub }
  }
  if (basis === 'memory') {
    return { pct: s.mem_pct, sub: s.mem_total_gb != null ? `${fmtResource(s.mem_used_gb ?? 0, 'GB')} / ${fmtResource(s.mem_total_gb, 'GB')}` : undefined }
  }
  return { pct: s.storage_pct, sub: s.storage_total_gb != null ? `${fmtResource(s.storage_used_gb ?? 0, 'GB')} / ${fmtResource(s.storage_total_gb, 'GB')}` : undefined }
}

/**
 * Sanallaştırma sayfası ölçer kartının altlığı: her hypervisor'un kullanım %'si ve kullanılan/toplam.
 * Üstteki ölçer tüm host'ların toplamıdır; burada kaynağı görünür.
 */
export function HypervisorUsageList({ data, basis }: { data: CapacityOverview | undefined; basis: Basis }) {
  const t = useT()
  if (!data) return null
  const accent = basis === 'cpu' ? RESOURCE_ACCENT.cpu : basis === 'memory' ? RESOURCE_ACCENT.memory : RESOURCE_ACCENT.disk
  return (
    <ul className="space-y-2.5 mt-4 pt-3 border-t border-white/[0.06]" data-testid={`hv-usage-${basis}`}>
      {data.physical.sources.map(s => {
        const cell = physicalCell(s, basis, t)
        return (
          <BreakdownRow
            key={s.hypervisor_id}
            label={s.name}
            demo={s.demo}
            typeLabel={s.type_label}
            pct={cell.pct}
            accent={accent}
            value={cell.pct == null ? t('cap_no_data') : `%${nf(cell.pct)}`}
            sub={cell.sub}
          />
        )
      })}
    </ul>
  )
}

/** Ana dashboard «Toplam kapasite» kartı: ortam başına fiziksel CPU / bellek / depolama (TB) ve kullanım. */
export function PhysicalCapacityCard({ data }: { data: CapacityOverview | undefined }) {
  const t = useT()
  if (!data || data.physical.sources.length === 0) return null
  const { sources, total, total_real } = data.physical
  const cell = (s: PhysicalSource | PhysicalTotal, basis: Basis) => {
    const c = physicalCell(s, basis, t)
    const totalVal = basis === 'cpu' ? null : basis === 'memory' ? s.mem_total_gb : s.storage_total_gb
    return (
      <td className="py-2 pr-3 align-top">
        {basis === 'cpu' ? (
          <div className="text-white font-medium tabular-nums">{t('cap_cores_n', { n: nf(s.cpu_cores) })}</div>
        ) : (
          <div className="text-white font-medium tabular-nums">{totalVal == null ? <span className="text-slate-500 font-normal">{t('cap_no_data')}</span> : fmtResource(totalVal, 'GB')}</div>
        )}
        <div className="text-[10px] text-slate-500 tabular-nums">
          {c.pct == null ? (basis === 'cpu' ? c.sub : '') : `%${nf(c.pct)} · ${c.sub ?? ''}`}
        </div>
      </td>
    )
  }
  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5" data-testid="cap-physical">
      <h3 className="text-sm font-medium text-white">{t('cap_title')}</h3>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">{t('cap_phys_hint')}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-400 text-left">
              <th className="py-1 pr-3 font-normal">{t('cap_col_env')}</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_hosts')}</th>
              <th className="py-1 pr-3 font-normal">CPU</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_mem')}</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_storage')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {sources.map(s => (
              <tr key={s.hypervisor_id} className={s.demo ? 'opacity-70' : ''}>
                <td className="py-2 pr-3 align-top">
                  <div className="flex items-center gap-1.5">
                    <span className="text-slate-200">{s.name}</span>{s.demo && <DemoBadge />}
                  </div>
                  <div className="text-[10px] text-slate-500">{s.type_label}</div>
                </td>
                <td className="py-2 pr-3 align-top text-white tabular-nums">{nf(s.hosts)}</td>
                {cell(s, 'cpu')}{cell(s, 'memory')}{cell(s, 'storage')}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-white/[0.12]">
            <tr>
              <td className="py-2 pr-3 text-slate-300 font-medium">{data.has_demo ? t('cap_total_real') : t('cap_total')}</td>
              <td className="py-2 pr-3 text-white tabular-nums">{nf(total_real.hosts)}</td>
              {cell(total_real, 'cpu')}{cell(total_real, 'memory')}{cell(total_real, 'storage')}
            </tr>
            {data.has_demo && (
              <tr className="opacity-70">
                <td className="py-1 pr-3 text-slate-400">{t('cap_total_all')}</td>
                <td className="py-1 pr-3 text-white tabular-nums">{nf(total.hosts)}</td>
                {cell(total, 'cpu')}{cell(total, 'memory')}{cell(total, 'storage')}
              </tr>
            )}
          </tfoot>
        </table>
      </div>
      <p className="text-[10px] text-slate-500 mt-3">{t('cap_phys_note')}</p>
    </div>
  )
}

type CapRow = {
  key: string; label: string; typeLabel: string; demo: boolean
  phys?: PhysicalSource; inv?: InventorySource
}

/** Ortam satırları: fiziksel (host) + envanter (VM) AYNI satırda; yalnız birinde olan ortam kaybolmaz. */
export function buildCapacityRows(data: CapacityOverview, opts: { physical: boolean; free: boolean }): CapRow[] {
  const invHv = new Map<number, InventorySource>()
  const free: InventorySource[] = []
  for (const s of data.inventory.sources) {
    if (s.kind === 'hypervisor') invHv.set(Number(s.key.replace('hv:', '')), s)
    else free.push(s)
  }
  const rows: CapRow[] = []
  const used = new Set<number>()
  if (opts.physical) {
    for (const p of data.physical.sources) {
      const inv = invHv.get(p.hypervisor_id)
      used.add(p.hypervisor_id)
      rows.push({ key: `hv:${p.hypervisor_id}`, label: p.name, typeLabel: p.type_label, demo: p.demo, phys: p, inv })
    }
  }
  for (const [id, inv] of invHv) {
    if (used.has(id)) continue
    rows.push({ key: inv.key, label: inv.label, typeLabel: inv.type_label, demo: inv.demo, inv })
  }
  if (opts.free) for (const inv of free) rows.push({ key: inv.key, label: inv.label, typeLabel: '', demo: inv.demo, inv })
  return rows
}

/**
 * Ana dashboard «Toplam kapasite» — TEK kart: ortam başına fiziksel kapasite/kullanım (host'lar) ile VM'lere/sunuculara
 * DAĞITILAN vCPU/RAM aynı satırda. (Eskiden «Toplam CPU/Bellek kaynağa göre» ayrı kartlardı.) Dağıtılan değer fiziksel
 * kapasite değildir; oran = dağıtılan / fiziksel (overcommit). Veri `capacity-overview` (DB'den anlık, 60 sn).
 * `physical`: sanallaştırma kapsamı (host verisi), `free`: Linux/Windows (hypervisor dışı) satırları.
 */
export function TotalCapacityCard({ data, physical = true, free = true }: {
  data: CapacityOverview | undefined; physical?: boolean; free?: boolean
}) {
  const t = useT()
  if (!data) return null
  const rows = buildCapacityRows(data, { physical, free })
  if (rows.length === 0) return null
  const real = rows.filter(r => !r.demo)
  const hasDemo = rows.some(r => r.demo)
  const sumInv = (items: CapRow[], k: 'cpu_cores' | 'memory_gb' | 'servers') => items.reduce((a, r) => a + (r.inv?.[k] ?? 0), 0)
  const aggPhys = physical ? { real: data.physical.total_real, all: data.physical.total } : null

  const dec = (n: number) => nf(n, n >= 10 ? 0 : 1)
  const tdCls = 'py-2 pr-3 align-top'
  const used = (pct: number | null | undefined, extra?: string) => pct == null ? null : (
    <div className="text-[10px] text-slate-400 tabular-nums" data-line="used">{t('cap_l_used')} %{nf(pct)}{extra ? ` (${extra})` : ''}</div>
  )
  /** CPU: fiziksel (çekirdek · GHz) / anlık kullanım / dağıtılan vCPU (+ çekirdek başına). Ayrıntı: hücre üzerine gelince. */
  const cpuCell = (r: { phys?: PhysicalSource | PhysicalTotal; allocCpu?: number; physCores?: number; ratioAlloc?: number }) => {
    const p = r.phys
    const cores = r.physCores ?? p?.cpu_cores
    const ghzTot = p?.cpu_total_ghz ?? null
    const per = r.ratioAlloc && cores ? r.ratioAlloc / cores : null
    const tip = [
      p ? (ghzTot != null ? t('cap_tt_phys_cpu', { cores: nf(cores ?? 0), ghz: nf(ghzTot, 1) }) : t('cap_tt_phys_cpu_nog', { cores: nf(cores ?? 0) })) : null,
      p?.cpu_pct != null ? (ghzTot != null ? t('cap_tt_used', { used: `${nf(p.cpu_used_ghz ?? 0, 1)} GHz`, total: `${nf(ghzTot, 1)} GHz`, pct: nf(p.cpu_pct) }) : t('cap_tt_used_pct', { pct: nf(p.cpu_pct) })) : null,
      r.allocCpu != null ? t('cap_tt_alloc_cpu', { v: nf(r.allocCpu) }) : null,
      per != null ? t('cap_tt_ratio_cpu', { r: dec(per) }) : null,
    ].filter(Boolean).join('\n')
    return (
      <td className={tdCls} title={tip || undefined}>
        <div className="text-white font-medium tabular-nums">
          {p ? (ghzTot != null ? t('cap_cores_ghz', { n: nf(cores ?? 0), g: nf(ghzTot, 1) }) : t('cap_cores_n', { n: nf(cores ?? 0) })) : <span className="text-slate-500 font-normal">—</span>}
        </div>
        {p && used(p.cpu_pct, ghzTot != null ? `${nf(p.cpu_used_ghz ?? 0, 1)} GHz` : undefined)}
        {r.allocCpu != null && (
          <div className="text-[10px] text-cyan-300 tabular-nums" data-alloc="cpu">
            {t('cap_l_alloc')} {nf(r.allocCpu)} vCPU{per != null ? ` · ${t('cap_per_core', { r: dec(per) })}` : ''}
          </div>
        )}
      </td>
    )
  }
  /** Bellek: fiziksel / anlık kullanım / dağıtılan GB (+ fiziksele oran). */
  const memCell = (r: { phys?: PhysicalSource | PhysicalTotal; allocMem?: number; physGb?: number | null; ratioAlloc?: number }) => {
    const p = r.phys
    const gb = r.physGb ?? p?.mem_total_gb ?? null
    const ratio = r.ratioAlloc && gb ? r.ratioAlloc / gb : null
    const tip = [
      gb != null ? t('cap_tt_phys_mem', { v: fmtResource(gb, 'GB') }) : null,
      p?.mem_pct != null && gb != null ? t('cap_tt_used', { used: fmtResource(p.mem_used_gb ?? 0, 'GB'), total: fmtResource(gb, 'GB'), pct: nf(p.mem_pct) }) : null,
      r.allocMem != null ? t('cap_tt_alloc_mem', { v: fmtResource(r.allocMem, 'GB') }) : null,
      ratio != null ? t('cap_tt_ratio_mem', { r: dec(ratio) }) : null,
    ].filter(Boolean).join('\n')
    return (
      <td className={tdCls} title={tip || undefined}>
        <div className="text-white font-medium tabular-nums">{gb == null ? <span className="text-slate-500 font-normal">{p ? t('cap_no_data') : '—'}</span> : fmtResource(gb, 'GB')}</div>
        {p && used(p.mem_pct, p.mem_used_gb != null ? fmtResource(p.mem_used_gb, 'GB') : undefined)}
        {r.allocMem != null && (
          <div className="text-[10px] text-cyan-300 tabular-nums" data-alloc="memory">
            {t('cap_l_alloc')} {fmtResource(r.allocMem, 'GB')}{ratio != null ? ` · ${t('cap_ratio_mem', { r: dec(ratio) })}` : ''}
          </div>
        )}
      </td>
    )
  }
  const stCell = (p?: PhysicalSource | PhysicalTotal) => {
    if (!p) return <td className={`${tdCls} text-slate-500`}>—</td>
    const tot = p.storage_total_gb
    const tip = tot != null ? [
      t('cap_tt_phys_st', { v: fmtResource(tot, 'GB') }),
      p.storage_pct != null ? t('cap_tt_used', { used: fmtResource(p.storage_used_gb ?? 0, 'GB'), total: fmtResource(tot, 'GB'), pct: nf(p.storage_pct) }) : null,
    ].filter(Boolean).join('\n') : undefined
    return (
      <td className={tdCls} title={tip}>
        <div className="text-white font-medium tabular-nums">{tot == null ? <span className="text-slate-500 font-normal">{t('cap_no_data')}</span> : fmtResource(tot, 'GB')}</div>
        {used(p.storage_pct, p.storage_used_gb != null ? fmtResource(p.storage_used_gb, 'GB') : undefined)}
      </td>
    )
  }
  const totalRow = (label: string, items: CapRow[], agg: PhysicalTotal | null, cls = '') => {
    // overcommit: yalnız fiziksel host verisi olan ortamların dağıtılanı / fiziksel toplam (Linux/Windows satırları hariç)
    const withPhys = items.filter(r => r.phys && r.inv)
    const rCpu = sumInv(withPhys, 'cpu_cores')
    const rMem = sumInv(withPhys, 'memory_gb')
    return (
    <tr className={cls}>
      <td className="py-2 pr-3 text-slate-300 font-medium">{label}
        <div className="text-[10px] text-slate-500 font-normal">{t('cap_servers_n', { n: nf(sumInv(items, 'servers')) })}</div>
      </td>
      <td className="py-2 pr-3 text-white tabular-nums align-top">{agg ? nf(agg.hosts) : '—'}</td>
      {cpuCell({ phys: agg ?? undefined, allocCpu: sumInv(items, 'cpu_cores'), physCores: agg ? agg.cpu_cores : undefined, ratioAlloc: agg ? rCpu : undefined })}
      {memCell({ phys: agg ?? undefined, allocMem: sumInv(items, 'memory_gb'), physGb: agg?.mem_total_gb, ratioAlloc: agg ? rMem : undefined })}
      {stCell(agg ?? undefined)}
    </tr>
    )
  }
  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5" data-testid="cap-total">
      <h3 className="text-sm font-medium text-white">{t('cap_title')}</h3>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">{t('cap_total_hint')}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-400 text-left">
              <th className="py-1 pr-3 font-normal">{t('cap_col_env')}</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_hosts')}</th>
              <th className="py-1 pr-3 font-normal">CPU</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_mem')}</th>
              <th className="py-1 pr-3 font-normal">{t('cap_col_storage')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]" data-testid="cap-total-rows">
            {rows.map(r => (
              <tr key={r.key} className={r.demo ? 'opacity-70' : ''} data-testid="cap-total-row">
                <td className="py-2 pr-3 align-top">
                  <div className="flex items-center gap-1.5"><span className="text-slate-200">{r.label}</span>{r.demo && <DemoBadge />}</div>
                  <div className="text-[10px] text-slate-500">{[r.typeLabel, r.inv ? t('cap_servers_n', { n: nf(r.inv.servers) }) : ''].filter(Boolean).join(' · ')}</div>
                </td>
                <td className="py-2 pr-3 align-top text-white tabular-nums">{r.phys ? nf(r.phys.hosts) : '—'}</td>
                {cpuCell({ phys: r.phys, allocCpu: r.inv?.cpu_cores, ratioAlloc: r.phys && r.inv ? r.inv.cpu_cores : undefined })}
                {memCell({ phys: r.phys, allocMem: r.inv?.memory_gb, ratioAlloc: r.phys && r.inv ? r.inv.memory_gb : undefined })}
                {stCell(r.phys)}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-white/[0.12]">
            {totalRow(hasDemo ? t('cap_total_real') : t('cap_total'), real, aggPhys?.real ?? null)}
            {hasDemo && totalRow(t('cap_total_all'), rows, aggPhys?.all ?? null, 'opacity-70')}
          </tfoot>
        </table>
      </div>
      <p className="text-[10px] text-slate-500 mt-3">{t('cap_phys_note')}</p>
    </div>
  )
}

/**
 * «40 host» KPI balonu: host'lar hypervisor TÜRÜNE göre (VMware / OLVM / OpenShift Virt …) — veri `capacity-overview`
 * `physical.sources` (DB'deki hypervisor kayıtlarından üretilir; yeni tür eklenince kendiliğinden görünür).
 */
export function HostTypesTip({ data }: { data: CapacityOverview | undefined }) {
  const t = useT()
  if (!data || data.physical.sources.length === 0) return null
  const groups = new Map<string, { label: string; demo: boolean; hosts: number; hypervisors: number }>()
  for (const s of data.physical.sources) {
    const key = `${s.type}|${s.demo ? 1 : 0}`
    const g = groups.get(key) ?? { label: s.type_label || s.type || '—', demo: s.demo, hosts: 0, hypervisors: 0 }
    g.hosts += s.hosts
    g.hypervisors += 1
    groups.set(key, g)
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].hosts - a[1].hosts).map(([key, g]) => ({
    key, label: g.label, demo: g.demo, value: t('cap_tip_hosts_n', { n: nf(g.hosts) }),
    sub: t('cap_tip_hv_n', { n: nf(g.hypervisors) }),
  }))
  const total = data.physical.sources.reduce((acc, s) => acc + s.hosts, 0)
  return <TipList title={t('cap_tip_host_types')} rows={rows} totalLabel={t('cap_total')} totalValue={nf(total)} />
}

const ratioText = (r: number) => `${r >= 10 ? Math.round(r) : r.toFixed(1)}×`

/**
 * Sanallaştırma sayfası kaynak kartı (CPU / Bellek / Depolama): üstte tüm host'ların FİZİKSEL kullanımı (ölçer),
 * altta hypervisor başına kullanım + (CPU/Bellek) VM'lere DAĞITILAN vCPU/RAM. Dağıtılan / fiziksel oranı (overcommit) toplamda.
 * Tüm veri `capacity-overview`dan gelir (60 sn'de bir yenilenir); fiziksel verisi olmayan hypervisor satırı kaybolmaz.
 */
export function VirtCapacityCard({ data, basis }: { data: CapacityOverview | undefined; basis: Basis }) {
  const t = useT()
  if (!data) return null
  const { sources, total } = data.physical
  const invAll = data.inventory.sources.filter(s => s.kind === 'hypervisor')
  if (sources.length === 0 && invAll.length === 0) return null
  const accent = basis === 'cpu' ? RESOURCE_ACCENT.cpu : basis === 'memory' ? RESOURCE_ACCENT.memory : RESOURCE_ACCENT.disk
  const label = t(basis === 'cpu' ? 'hv_cpu_usage' : basis === 'memory' ? 'hv_mem_usage' : 'hv_disk_usage')

  // Ölçer: tüm host'ların toplamı (MHz/GB); MHz vermeyen kaynaklarda yalnız yüzde.
  let gauge = { used: 0, total: 100, unit: '%' }
  if (basis === 'cpu') gauge = total.cpu_total_ghz ? { used: (total.cpu_used_ghz ?? 0) * 1000, total: total.cpu_total_ghz * 1000, unit: 'MHz' } : { used: total.cpu_pct ?? 0, total: 100, unit: '%' }
  else if (basis === 'memory') gauge = total.mem_total_gb ? { used: total.mem_used_gb ?? 0, total: total.mem_total_gb, unit: 'GB' } : { used: total.mem_pct ?? 0, total: 100, unit: '%' }
  else gauge = total.storage_total_gb ? { used: total.storage_used_gb ?? 0, total: total.storage_total_gb, unit: 'GB' } : { used: total.storage_pct ?? 0, total: 100, unit: '%' }

  const inv = new Map(invAll.map(s => [s.key, s]))
  const alloc = (s: InventorySource) => (basis === 'cpu' ? `${nf(s.cpu_cores)} vCPU` : fmtResource(s.memory_gb, 'GB'))
  const rows = sources.map(s => {
    const cell = physicalCell(s, basis, t)
    const a = inv.get(`hv:${s.hypervisor_id}`)
    const sub = [
      cell.sub,
      basis === 'storage' ? t('vcc_ds_n', { n: nf(s.datastores) }) : (a ? t('vcc_alloc', { v: alloc(a) }) : undefined),
    ].filter(Boolean).join(' · ')
    return { key: `p${s.hypervisor_id}`, label: s.name, demo: s.demo, typeLabel: s.type_label, pct: cell.pct, value: cell.pct == null ? t('cap_no_data') : `%${nf(cell.pct)}`, sub }
  })
  const physIds = new Set(sources.map(s => `hv:${s.hypervisor_id}`))
  const extra = basis === 'storage' ? [] : invAll.filter(a => !physIds.has(a.key)).map(a => ({
    key: a.key, label: a.label, demo: a.demo, typeLabel: a.type_label, pct: null as number | null,
    value: alloc(a), sub: t('vcc_no_phys'),
  }))

  // Dağıtılan / fiziksel (yalnız her iki verisi de olan hypervisor'ler)
  let ratio: number | null = null
  if (basis !== 'storage') {
    let a = 0; let p = 0
    for (const s of sources) {
      const i = inv.get(`hv:${s.hypervisor_id}`)
      if (!i) continue
      a += basis === 'cpu' ? i.cpu_cores : i.memory_gb
      p += basis === 'cpu' ? s.cpu_cores : (s.mem_total_gb ?? 0)
    }
    ratio = p > 0 && a > 0 ? a / p : null
  }

  return (
    <div data-testid={`vcc-${basis}`}>
      <ResourceGauge label={label} used={gauge.used} total={gauge.total} unit={gauge.unit} accent={accent}
        footer={(
          <>
            {ratio != null && (
              <div className="flex justify-between text-xs mt-3" data-testid={`vcc-ratio-${basis}`}>
                <span className="text-slate-400">{t(basis === 'cpu' ? 'vcc_ratio_cpu' : 'vcc_ratio_mem')}</span>
                <span className="text-white font-semibold tabular-nums">{ratioText(ratio)}</span>
              </div>
            )}
            <ul className="space-y-2.5 mt-4 pt-3 border-t border-white/[0.06]" data-testid={`vcc-list-${basis}`}>
              {[...rows, ...extra].map(r => (
                <BreakdownRow key={r.key} label={r.label} demo={r.demo} typeLabel={r.typeLabel || undefined}
                  pct={r.pct} accent={accent} value={r.value} sub={r.sub} />
              ))}
            </ul>
          </>
        )} />
    </div>
  )
}

const ENV_ROWS_VISIBLE = 6

/**
 * Ana dashboard «Sunucu Durumu» zenginleştirmesi: ORTAM (hypervisor / hypervisor dışı Linux-Windows) başına açık / kapalı / uyarı.
 * Veri `capacity-overview` `inventory.sources` (servers.status, DB'den anlık). Eski yanıtta durum alanları yoksa hiçbir şey çizmez.
 */
export function EnvStatusBreakdown({ data }: { data: CapacityOverview | undefined }) {
  const t = useT()
  const [all, setAll] = useState(false)
  if (!data) return null
  const rows = data.inventory.sources.filter(s => s.online != null)
  if (rows.length === 0) return null
  const sorted = [...rows].sort((a, b) => Number(a.demo) - Number(b.demo) || b.servers - a.servers)
  const shown = all ? sorted : sorted.slice(0, ENV_ROWS_VISIBLE)
  return (
    <div className="mt-5 pt-4 border-t border-white/[0.06]" data-testid="env-status">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">{t('dash_env_status_title')}</div>
      <ul className="space-y-2.5">
        {shown.map(s => {
          const on = s.online ?? 0
          const off = s.offline ?? 0
          const att = s.attention ?? 0
          const other = Math.max(0, s.servers - on - off - att)
          const pct = (n: number) => (s.servers > 0 ? (n / s.servers) * 100 : 0)
          return (
            <li key={s.key} data-testid="env-status-row" className={s.demo ? 'opacity-70' : ''}>
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="text-slate-200 truncate" title={s.label}>{s.label}</span>
                  {s.demo && <DemoBadge />}
                </span>
                <span className="text-slate-400 tabular-nums shrink-0">
                  <span className="text-green-400">{nf(on)}</span> {t('dash_env_on')} · <span className="text-slate-300">{nf(off)}</span> {t('dash_env_off')}
                  {att > 0 && <> · <span className="text-orange-400">{nf(att)}</span> {t('dash_env_attn')}</>}
                </span>
              </div>
              <div className="flex h-1.5 rounded-full overflow-hidden bg-slate-800 mt-1" aria-hidden>
                <div style={{ width: `${pct(on)}%`, background: '#22c55e' }} />
                <div style={{ width: `${pct(att)}%`, background: '#f97316' }} />
                <div style={{ width: `${pct(off)}%`, background: '#64748b' }} />
                <div style={{ width: `${pct(other)}%`, background: '#1e293b' }} />
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">{[s.type_label, t('cap_servers_n', { n: nf(s.servers) })].filter(Boolean).join(' · ')}</div>
            </li>
          )
        })}
      </ul>
      {sorted.length > ENV_ROWS_VISIBLE && (
        <button type="button" data-testid="env-status-more" onClick={() => setAll(v => !v)}
          className="mt-3 text-xs text-blue-300 hover:text-blue-200">
          {all ? t('hv_host_less') : t('hv_host_more', { n: sorted.length - ENV_ROWS_VISIBLE })}
        </button>
      )}
    </div>
  )
}
