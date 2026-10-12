import { Link } from 'react-router-dom'
import { useT } from '../../i18n/LocaleProvider'
import { MethodBadge } from './MethodBadge'
import { useInsights, useRole } from './insightsKit'

/** Referans paketi durum kartı (G.4): paket yok / güncel / güncel değil — ve bunun "yok" ≠ "temiz" olduğu. */
export function ReferencePacksCard() {
  const t = useT()
  const { isAdmin } = useRole()
  const q = useInsights<any>('virt-insights', '/reference')
  const pk: any[] = q.data?.packages || []
  if (!pk.length) return null
  const label: Record<string, string> = { cve_feed: t('vi_ref_cve'), kb_feed: t('vi_ref_kb'), upgrade_matrix: t('vi_ref_upg') }
  const tone: Record<string, string> = {
    ok: 'text-emerald-400', stale: 'text-amber-300', missing: 'text-slate-400', unknown: 'text-amber-200',
  }
  const stateText = (p: any) => p.state === 'ok' ? t('g_ref_st_ok', { d: Math.floor(p.age_days ?? 0) })
    : p.state === 'stale' ? t('g_ref_st_stale', { d: Math.floor(p.age_days ?? 0), th: p.stale_threshold_days })
      : p.state === 'missing' ? t('g_ref_st_missing') : t('g_ref_st_unknown')
  const anyBad = pk.some(p => p.state !== 'ok')
  return (
    <div className="bg-cyber-card border border-white/[0.06] rounded-lg p-4 space-y-3" data-testid="reference-packs-card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">{t('vi_ref_title')}</h2>
        <Link to={isAdmin ? '/virt/health?tab=settings' : '/virt/health?tab=vuln'} className="text-xs text-blue-400 hover:underline">{t('g_ref_open')}</Link>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {pk.map(p => (
          <div key={p.kind} className="rounded border border-white/[0.06] px-3 py-2">
            <div className="text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              {label[p.kind] || p.kind}<MethodBadge id={`ref.pack.${p.kind}`} at={p.generated_at || p.uploaded_at} />
            </div>
            <div className={`text-sm mt-1 ${tone[p.state] || 'text-slate-400'}`}>{stateText(p)}</div>
            {p.generated_at && <div className="text-[11px] text-slate-500 mt-0.5">{t('g_ref_generated')}: {new Date(p.generated_at).toLocaleDateString()}</div>}
          </div>
        ))}
      </div>
      {anyBad && <div className="text-[11px] text-slate-500">{t('g_ref_absent_note')}</div>}
    </div>
  )
}
