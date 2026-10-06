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

/** Sanallaştırma panosu — karar katmanı özet kartları (kapasite, geri kazanım, sağlık, değişiklik). */
export default function VirtInsightsStrip() {
  const t = useT()
  const q = useInsights<any>('virt-insights', '/summary', { refetch: 300_000 })
  const ch = useInsights<any>('virt-insights', '/changes?days=7&limit=500', { refetch: 300_000 })
  if (q.isError || !q.data) return null
  const by = q.data.findings?.by_category || {}
  const health = ['health', 'hardware', 'vuln', 'known_issue', 'upgrade', 'compliance']
    .reduce((a, c) => a + (by[c]?.critical || 0) + (by[c]?.high || 0), 0)
  const cap = q.data.capacity || {}
  const rc = q.data.reclaim || {}
  const reclaimGb = (rc.orphans?.size_gb || 0) + (rc.snapshots?.space_gb || 0) + (rc.isos?.size_gb || 0)
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card to="/virt/capacity" icon={<Gauge size={13} />} title={t('nav_virt_capacity')}
        value={cap.clusters ? `${cap.n1_fail}/${cap.clusters}` : '—'} sub={t('vi_strip_n1')}
        tone={cap.n1_fail ? 'text-red-400' : 'text-emerald-400'} />
      <Card to="/virt/reclaim" icon={<Recycle size={13} />} title={t('nav_virt_reclaim')}
        value={`${fmt(rc.powered_off?.memory_gb, 0)} GB`} sub={t('vi_strip_reclaim', { gb: fmt(reclaimGb, 0), n: rc.powered_off?.count ?? 0 })}
        tone="text-blue-300" />
      <Card to="/virt/health" icon={<ShieldCheck size={13} />} title={t('nav_virt_health')}
        value={health} sub={t('vi_strip_health')} tone={health ? 'text-amber-400' : 'text-emerald-400'} />
      <Card to="/virt/changes" icon={<GitCompare size={13} />} title={t('nav_virt_changes')}
        value={ch.data?.count ?? '—'} sub={t('vi_strip_changes', { n: by.drift?.total ?? 0 })} tone="text-slate-200" />
    </div>
  )
}
