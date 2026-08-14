/** Genel Bakış — Atlas tarzı kapasite donut, detaylı node, SC, Multus, MTV hazırlık. */
import {
  Server, HardDrive, Network, ShieldCheck, AlertTriangle, CheckCircle2, XCircle,
} from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'

function ClusterCapacity({ cap }: { cap: any }) {
  const t = useT()
  const cpuPct = cap.cpu_cores && cap.cpu_used_cores != null
    ? (cap.cpu_used_cores / cap.cpu_cores) * 100 : null
  const memPct = cap.memory_gb && cap.memory_used_gb != null
    ? (cap.memory_used_gb / cap.memory_gb) * 100 : null

  const Donut = ({ pct, label, used, total, unit }: any) => {
    const p = pct == null ? 0 : Math.max(0, Math.min(100, pct))
    const r = 34
    const circ = 2 * Math.PI * r
    const color = pct == null ? '#475569' : p > 85 ? '#ef4444' : p > 70 ? '#f59e0b' : '#38bdf8'
    return (
      <div className="flex items-center gap-3">
        <div className="relative w-[86px] h-[86px] flex-shrink-0">
          <svg viewBox="0 0 88 88" className="w-full h-full -rotate-90">
            <circle cx="44" cy="44" r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
            <circle
              cx="44" cy="44" r={r} fill="none" stroke={color} strokeWidth="8"
              strokeDasharray={`${(p / 100) * circ} ${circ}`}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute inset-0 grid place-items-center text-xs font-semibold text-slate-200">
            {pct == null ? '—' : `${Math.round(p)}%`}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">{label}</div>
          <div className="text-sm text-white font-medium">
            {used ?? '—'} / {total ?? '—'} {unit}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 items-center">
        <Donut pct={cpuPct} label="CPU" used={cap.cpu_used_cores} total={cap.cpu_cores} unit="core" />
        <Donut pct={memPct} label={t('memory')} used={cap.memory_used_gb} total={cap.memory_gb} unit="GB" />
        <div className="text-xs space-y-1">
          <div className="text-slate-500">Nodes</div>
          <div className="text-lg text-white font-semibold">
            {cap.nodes_ready ?? '—'}/{cap.nodes_total ?? '—'}
            <span className="text-xs text-slate-500 font-normal ml-1">ready</span>
          </div>
        </div>
        <div className="text-xs space-y-1">
          <div className="text-slate-500">Pods</div>
          <div className="text-lg text-white font-semibold">
            {cap.pods_running ?? '—'}
            <span className="text-xs text-slate-500 font-normal ml-1">running</span>
          </div>
          {cap.metrics_available === false && (
            <div className="text-[10px] text-amber-400/80">{t('ocp_metrics_req')}</div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function OcpOverviewPanel({
  overview,
  onGoMtv,
}: {
  overview: any
  onGoMtv?: () => void
}) {
  const t = useT()
  const ov = overview
  const nodes = ov.nodes || []
  const scs = ov.storage_classes || []
  const nads = ov.network_attachment_definitions
  const missing = ov.migration_missing || []

  return (
    <div className="space-y-4">
      {ov.capacity && <ClusterCapacity cap={ov.capacity} />}

      <div className={`rounded-xl border p-4 ${
        ov.migration_ready ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-amber-500/30 bg-amber-500/5'
      }`}>
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck size={16} className={ov.migration_ready ? 'text-emerald-400' : 'text-amber-400'} />
          <h3 className="text-sm font-semibold text-slate-100">{t('ocp_mtv_ready')}</h3>
          {onGoMtv && (
            <button type="button" onClick={onGoMtv} className="ml-auto text-[11px] text-rose-300 hover:underline">
              {t('ocp_go_mtv')}
            </button>
          )}
        </div>
        {ov.migration_ready ? (
          <p className="text-xs text-emerald-300/90">
            {t('ocp_mtv_ok')}
          </p>
        ) : (
          <p className="text-xs text-amber-200/90 flex items-start gap-1.5">
            <AlertTriangle size={14} className="mt-px flex-shrink-0" />
            <span>
              {t('ocp_mtv_missing', { list: missing.length ? missing.join(', ') : t('ocp_unknown_missing') })}
            </span>
          </p>
        )}
        <div className="flex gap-2 flex-wrap mt-3">
          {(ov.operators || []).map((o: any) => (
            <span
              key={o.group}
              title={o.group}
              className={`flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg border ${
                o.installed
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border-white/[0.08] bg-cyber-deep text-slate-500'
              }`}
            >
              {o.installed ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
              {(o.label || o.group || '').split('(')[0].trim()}
            </span>
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
            <Server size={16} className="text-sky-400" /> {t('ocp_nodes')}
            <span className="text-xs text-slate-500">({nodes.length})</span>
          </h3>
          <div className="space-y-1.5">
            {nodes.map((n: any) => {
              const cpuPct = n.usage && n.cpu
                ? Math.min(100, (Number(n.usage.cpu_cores ?? (n.usage.cpu_millicores || 0) / 1000) / Number(n.cpu)) * 100)
                : (n.cpu_request_pct ?? null)
              const memPct = n.usage && n.memory_gb
                ? Math.min(100, (Number(n.usage.memory_gb) / Number(n.memory_gb)) * 100)
                : (n.memory_request_pct ?? null)
              const bar = (p: number | null) =>
                p == null ? 'bg-slate-600' : p > 85 ? 'bg-red-500' : p > 70 ? 'bg-amber-500' : 'bg-sky-500'
              const cpuUsed = n.usage?.cpu_cores != null
                ? Number(n.usage.cpu_cores).toFixed(2)
                : n.usage?.cpu_millicores != null
                  ? (n.usage.cpu_millicores / 1000).toFixed(2)
                  : null
              const tipParts = [
                n.internal_ip && `InternalIP: ${n.internal_ip}`,
                n.external_ip && `ExternalIP: ${n.external_ip}`,
                n.hostname && n.hostname !== n.name && `Hostname: ${n.hostname}`,
                !n.internal_ip && !n.external_ip && t('ocp_ip_none'),
              ].filter(Boolean)
              const tip = tipParts.join('\n')
              return (
                <div
                  key={n.name}
                  className="rounded-lg border border-white/[0.05] bg-cyber-deep/50 px-2.5 py-2 group relative"
                  title={tip}
                >
                  <div className="flex items-center gap-2 text-xs">
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${n.ready ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    <span className="text-slate-100 font-medium truncate" title={tip}>{n.name}</span>
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-400 flex-shrink-0 cursor-default"
                      title={tip}
                    >
                      {(n.roles || []).join('/') || t('ocp_worker')}
                    </span>
                    {/* Hover kart — native title + görünür ipucu */}
                    <div className="pointer-events-none absolute left-2 top-full z-20 mt-1 hidden min-w-[12rem] rounded-lg border border-white/[0.1] bg-cyber-card px-2.5 py-2 text-[11px] text-slate-200 shadow-xl group-hover:block">
                      <div className="font-medium text-slate-100 mb-1">{n.name}</div>
                      <div className="text-slate-400">{(n.roles || []).join('/') || t('ocp_worker')}</div>
                      {n.internal_ip ? (
                        <div className="mt-1 font-mono text-cyan-300/90">IP {n.internal_ip}</div>
                      ) : (
                        <div className="mt-1 text-slate-500">{t('ocp_no_ip')}</div>
                      )}
                      {n.external_ip && (
                        <div className="font-mono text-slate-400">Ext {n.external_ip}</div>
                      )}
                    </div>
                    {(n.pressure || []).length > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
                        {n.pressure.join(', ')}
                      </span>
                    )}
                    <span className="text-slate-500 ml-auto flex-shrink-0">{n.cpu} CPU · {n.memory_gb} GB</span>
                  </div>
                  {(cpuPct != null || memPct != null) && (
                    <div className="grid grid-cols-2 gap-3 mt-2">
                      {[
                        ['CPU', cpuPct, cpuUsed != null ? t('ocp_cores_used', { used: cpuUsed, total: n.cpu }) : t('ocp_req_cpu', { n: Math.round(cpuPct || 0) })],
                        ['Memory', memPct, n.usage?.memory_gb != null ? t('ocp_mem_used', { used: n.usage.memory_gb, total: n.memory_gb }) : t('ocp_req_cpu', { n: Math.round(memPct || 0) })],
                      ].map(([lbl, pct, sub]: any) => (
                        <div key={lbl}>
                          <div className="flex justify-between text-[10px] mb-0.5">
                            <span className="text-slate-500">{lbl}</span>
                            <span className="text-slate-400 tabular-nums">
                              {pct == null ? '—' : `%${Math.round(pct)}`}
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-cyber-deep overflow-hidden">
                            <div className={`h-full rounded-full ${bar(pct)}`} style={{ width: `${pct || 0}%` }} />
                          </div>
                          <p className="text-[10px] text-slate-600 mt-0.5">{sub}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {ov.kubevirt_vms != null && (
            <p className="text-xs text-slate-500 mt-2">
              {t('ocp_kubevirt_vm_n', { n: ov.kubevirt_vms })}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
              <HardDrive size={16} className="text-violet-400" /> {t('ocp_sc_list')}
              <span className="text-xs text-slate-500">({scs.length})</span>
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {scs.map((sc: any) => (
                <span
                  key={sc.name}
                  title={sc.provisioner}
                  className={`text-[11px] px-2 py-0.5 rounded-lg border ${
                    sc.default
                      ? 'border-violet-500/40 bg-violet-500/10 text-violet-300'
                      : 'border-white/[0.08] bg-cyber-deep text-slate-400'
                  }`}
                >
                  {sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}
                </span>
              ))}
              {scs.length === 0 && <span className="text-xs text-slate-600">{t('ocp_no_sc')}</span>}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
              <Network size={16} className="text-emerald-400" /> {t('ocp_nads')}
            </h3>
            {nads === null || nads === undefined ? (
              <p className="text-xs text-slate-600">{t('ocp_no_multus')}</p>
            ) : nads.length === 0 ? (
              <p className="text-xs text-slate-600">{t('ocp_no_nad')}</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {nads.map((n: any) => (
                  <span
                    key={n.name}
                    className="text-[11px] px-2 py-0.5 rounded-lg border border-white/[0.08] bg-cyber-deep text-slate-400"
                    title={`${n.namespaces || 1} namespace`}
                  >
                    {n.name}
                    {(n.namespaces || 0) > 1 && <span className="text-slate-600"> ×{n.namespaces}</span>}
                  </span>
                ))}
              </div>
            )}
          </div>
          {ov.namespaces && (
            <p className="text-xs text-slate-500 pt-1 border-t border-white/[0.06]">
              {t('ocp_ns_line', { n: ov.namespaces.total ?? '—' })}
              {ov.namespaces.user?.length > 0 && (
                <> · {t('ocp_user_ns', { list: ov.namespaces.user.slice(0, 6).join(', ') + (ov.namespaces.user.length > 6 ? '…' : '') })}</>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
