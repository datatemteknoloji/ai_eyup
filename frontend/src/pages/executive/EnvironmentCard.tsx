import { useState } from 'react'
import type { EnvCard } from './types'
import { ResourceGauge, RESOURCE_ACCENT } from '../../components/dashboard/ResourceCharts'
import { MiniBar, MUTED, cardStyle, linkButton, statusColor, trCount } from './shared'

function EnvGauge({ label, value, accent }: { label: string; value: number | null; accent: string }) {
  if (value == null) {
    return (
      <div className="flex items-center justify-between text-xs" style={{ color: MUTED }}>
        <span>{label}</span><span>ölçülemedi</span>
      </div>
    )
  }
  return <ResourceGauge compact label={label} used={value} total={100} unit="%" accent={accent} />
}

/** Ortam kartı: üç çubuk (işlemci, bellek, depolama; sanallaştırma sayfasındaki ResourceGauge) + sayılar + «Küme ve hostlar» ağacı. Her bilgi tek yerde. */
export function EnvironmentCard({ env, attentionCount }: { env: EnvCard; attentionCount: number }) {
  const [open, setOpen] = useState(false)
  const tree = env.tree || []
  return (
    <article style={cardStyle} className="min-w-0">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold truncate" title={env.name}>{env.name}</h2>
        <span className="text-sm font-semibold" style={{ color: statusColor(env.status) }}>{env.status}</span>
      </div>
      <p className="text-xs" style={{ color: MUTED }}>
        {env.kind}{attentionCount > 0 ? ` · ${trCount(attentionCount)} kayıt dikkat bekliyor` : ''}
      </p>
      <div className="mt-3 space-y-3">
        <EnvGauge label="İşlemci" value={env.cpu} accent={RESOURCE_ACCENT.cpu} />
        <EnvGauge label="Bellek" value={env.memory} accent={RESOURCE_ACCENT.memory} />
        <EnvGauge label="Depolama" value={env.storage ?? null} accent={RESOURCE_ACCENT.disk} />
      </div>
      <p className="text-sm mt-3">
        {trCount(env.clusters)} küme · {trCount(env.hosts)} host · {trCount(env.vms)} sanal makine
      </p>
      {tree.length > 0 && (
        <>
          <button type="button" className="text-sm mt-2" aria-expanded={open} onClick={() => setOpen((v) => !v)} style={linkButton}>
            {open ? 'Küme ve hostları gizle' : 'Küme ve hostları göster'}
          </button>
          {open && (
            <div className="mt-2 space-y-3" data-testid="env-tree">
              {tree.map((cluster) => (
                <div key={cluster.name}>
                  <p className="text-sm font-semibold">
                    {cluster.name}
                    <span className="font-normal" style={{ color: MUTED }}> · {trCount(cluster.hosts)} host</span>
                  </p>
                  <ul className="text-sm space-y-1 mt-1">
                    {(cluster.host_list || []).map((host) => (
                      <li key={host.name} className="flex items-center justify-between gap-2">
                        <span className="truncate" title={host.name}>
                          {host.problem && <span style={{ color: 'var(--warning)' }} aria-label="sorunlu">● </span>}
                          {host.name}
                        </span>
                        <span className="flex items-center gap-2 shrink-0 text-xs" style={{ color: MUTED }}>
                          <MiniBar value={host.cpu} accent={RESOURCE_ACCENT.cpu} />{host.cpu == null ? '—' : `%${Math.round(host.cpu)}`}
                          <MiniBar value={host.memory} accent={RESOURCE_ACCENT.memory} />{host.memory == null ? '—' : `%${Math.round(host.memory)}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {(cluster.host_list || []).length > 0 && (
                    <p className="text-xs mt-1" style={{ color: MUTED }}>İlk çubuk işlemci, ikincisi bellek.</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </article>
  )
}
