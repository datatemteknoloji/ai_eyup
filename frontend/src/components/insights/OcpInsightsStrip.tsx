import React from 'react'
import { Link } from 'react-router-dom'
import { Gauge, Recycle, ShieldCheck, GitCompare } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { fmt, useInsights } from './insightsKit'

function Card({ to, icon, title, value, sub, tone }: { to: string; icon: React.ReactNode; title: string; value: React.ReactNode; sub: string; tone: string }) {
  return (
    <Link to={to} className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-3 hover:border-blue-500/40 transition-colors block">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-slate-400">{icon}{title}</div>
      <div className={`text-xl font-bold font-mono mt-1 ${tone}`}>{value}</div>
      <div className="text-[11px] text-slate-500 truncate">{sub}</div>
    </Link>
  )
}

/** OpenShift envanter sayfası — karar katmanı özet kartları (kapasite, geri kazanım, sağlık, değişiklik). */
export default function OcpInsightsStrip() {
  const t = useT()
  const q = useInsights<any>('ocp-insights', '/summary', { refetch: 300_000 })
  const ch = useInsights<any>('ocp-insights', '/changes?days=7&limit=500', { refetch: 300_000 })
  if (q.isError || !q.data || !(q.data.clusters || []).length) return null
  const clusters: any[] = q.data.clusters
  const by = q.data.findings?.by_category || {}
  const worst = Math.max(0, ...clusters.flatMap(c => [c.request_pct?.cpu || 0, c.request_pct?.memory || 0]))
  const n1Fail = clusters.filter(c => c.n_plus_one?.status === 'fail').length
  const unusedGb = clusters.reduce((a, c) => a + (c.reclaim?.unused_gb || 0), 0)
  const unused = clusters.reduce((a, c) => a + (c.reclaim?.unused || 0) + (c.reclaim?.unbound || 0), 0)
  const health = ['health', 'drift', 'compliance'].reduce((a, c) => a + (by[c]?.critical || 0) + (by[c]?.high || 0), 0)
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card to="/openshift/capacity" icon={<Gauge size={13} />} title={t('nav_ocp_capacity')}
        value={`%${fmt(worst)}`} sub={t('oi_strip_n1', { n: n1Fail })}
        tone={n1Fail ? 'text-red-400' : worst > 85 ? 'text-amber-400' : 'text-emerald-400'} />
      <Card to="/openshift/reclaim" icon={<Recycle size={13} />} title={t('nav_ocp_reclaim')}
        value={`${fmt(unusedGb, 0)} GB`} sub={t('oi_strip_reclaim', { n: unused })} tone="text-blue-300" />
      <Card to="/openshift/health" icon={<ShieldCheck size={13} />} title={t('nav_ocp_health')}
        value={health} sub={t('oi_strip_health')} tone={health ? 'text-amber-400' : 'text-emerald-400'} />
      <Card to="/openshift/changes" icon={<GitCompare size={13} />} title={t('nav_ocp_changes')}
        value={ch.data?.count ?? '—'} sub={t('oi_strip_changes', { n: by.drift?.total ?? 0 })} tone="text-slate-200" />
    </div>
  )
}
