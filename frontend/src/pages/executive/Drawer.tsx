import { useEffect } from 'react'
import type { Area, AttentionItem, View } from './types'
import { MUTED, linkButton, statusColor } from './shared'

export type DrawerTarget = Area | AttentionItem | 'idle'

/** Sağ çekmece: modül ayrıntısı, dikkat satırı ayrıntısı veya atıl kayıt listesi. */
export function Drawer({ target, view, onClose }: { target: DrawerTarget; view: View | null | undefined; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <>
    {/* Boşluğa tıklayınca kapanır; Esc de kapatır. */}
    <div data-testid="drawer-backdrop" onClick={onClose} aria-hidden style={{ position: 'fixed', inset: 0, zIndex: 19, background: 'rgba(15,23,42,0.25)' }} />
    <aside role="dialog" aria-modal="true" style={{ position: 'fixed', top: 0, right: 0, height: '100%', width: 420, maxWidth: '100%', overflow: 'auto', background: 'var(--theme-card)', color: 'var(--theme-card-foreground)', borderLeft: '1px solid var(--theme-border)', padding: 16, zIndex: 20 }}>
      <button type="button" onClick={onClose} style={linkButton}>Kapat</button>
      {target === 'idle' ? (
        <>
          <h2 className="font-semibold mt-2">İlk 10 atıl kayıt</h2>
          <p className="text-sm">{view?.idle?.note}</p>
          <table className="w-full text-sm mt-2">
            <tbody>
              {(view?.idle?.top || []).map((row) => (
                <tr key={row.name}><td>{row.name}</td><td>{row.category}</td><td>{row.amount}</td><td>{row.age}</td></tr>
              ))}
            </tbody>
          </table>
          {(view?.idle?.top || []).length === 0 && <p className="text-sm">Listelenecek kayıt yok.</p>}
        </>
      ) : 'metrics' in target ? (
        <>
          <h2 className="font-semibold mt-2">{target.name}</h2>
          <p style={{ color: statusColor(target.status) }}>{target.status}{target.score != null ? ` · skor ${target.score}` : ''}</p>
          <p className="text-sm mt-2">{target.reason}</p>
          {(target.issues || []).map((issue) => (
            <p key={issue.problem} className="text-sm mt-2">{issue.problem} Olası çözüm: {issue.action}</p>
          ))}
          <ul className="text-sm mt-3 space-y-1">
            {target.metrics.map((metric) => (
              <li key={metric.label} className="flex justify-between gap-2"><span style={{ color: MUTED }}>{metric.label}</span><span>{metric.value}</span></li>
            ))}
          </ul>
          {(target.events || []).length > 0 && (
            <ul className="text-sm mt-3 space-y-1">
              {(target.events || []).map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
          <table className="w-full text-sm mt-3">
            <thead><tr style={{ color: MUTED }}><th className="text-left">Ad</th><th>Durum</th><th>Kritik</th><th>Uyarı</th><th>Kullanım</th></tr></thead>
            <tbody>
              {(target.assets || []).map((asset) => (
                <tr key={asset.name}><td>{asset.name}</td><td>{asset.status}</td><td>{asset.critical}</td><td>{asset.warning}</td><td>{asset.usage}</td></tr>
              ))}
            </tbody>
          </table>
          {(target.assets || []).length === 0 && <p className="text-sm mt-2">Adlandırılmış varlık bu pakette yok.</p>}
        </>
      ) : (
        <>
          <h2 className="font-semibold mt-2">{target.title}</h2>
          <p>{target.problem}</p>
          <p className="text-sm mt-2" style={{ color: MUTED }}>
            {[target.kind && target.environment ? `${target.kind} · ${target.environment}` : target.environment || target.area, target.cluster].filter(Boolean).join(' · ')}
          </p>
          {target.extra > 0 && <p className="text-sm mt-2">Bu varlıkta {target.extra} bulgu daha açık.</p>}
          <p className="text-sm mt-2">Olası çözüm: {target.action}</p>
          {target.age_days > 0 && <p className="text-sm mt-2">{target.age_days} gündür açık</p>}
        </>
      )}
    </aside>
    </>
  )
}
