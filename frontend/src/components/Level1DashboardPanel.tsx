/**
 * Ana dashboard › Level 1 bölümü: bağlı kullanıcılar, son işlem yapılan sunucular,
 * son işlemler, 7 günlük eğilim ve dikkat gerektirenler.
 * Veri: ainew `/level1/dashboard` (Dropt özeti; kullanıcı listesi yalnız Level 1 kullanıcıları).
 * Otomatik yenileme YOK — periyodik istek Dropt oturumunu "hareketli" tutup boşta
 * zaman aşımını ve "bağlı kullanıcı" bilgisini bozar; elle yenile düğmesi var.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Server, Users, Wrench, XCircle } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useLocale, useT } from '../i18n/LocaleProvider'

type L1User = { username: string; role: string; last_seen_at: string | null; login_at: string | null; online: boolean; sessions: number; is_me: boolean }
type L1Server = { server_id: number; hostname: string; ip: string; last_action: string; last_status: string; last_message: string; username: string; at: string | null; op_count: number }
type L1Op = { id: number; title: string; module: string; action: string; status: string; dry_run: boolean; username: string; at: string | null; hosts: string[]; host_count: number; error: string }
type L1Data = {
  online_window_minutes: number
  users: L1User[]
  recent_servers: L1Server[]
  recent_ops: L1Op[]
  stats: {
    jobs_24h: number; jobs_7d: number; running_now: number; failed_24h: number; success_rate_7d: number | null
    servers_total: number; servers_by_status: Record<string, number>
    top_operators_7d: { username: string; count: number }[]
    top_actions_7d: { action: string; count: number }[]
    daily_7d: { date: string; success: number; failed: number; other: number }[]
  }
  attention: {
    failed_jobs: { id: number; title: string; username: string; at: string | null; error: string }[]
    problem_servers: { server_id: number; hostname: string; ip: string; status: string; message: string }[]
  }
}

async function fetchDashboard(): Promise<L1Data> {
  const r = await fetch(`${API_BASE_URL}/level1/dashboard`)
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`)
  }
  return r.json()
}

function useAgo() {
  const { locale } = useLocale()
  const rtf = new Intl.RelativeTimeFormat(locale === 'en' ? 'en' : 'tr', { numeric: 'auto' })
  return (iso: string | null) => {
    if (!iso) return '—'
    const sec = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
    const abs = Math.abs(sec)
    if (abs < 60) return rtf.format(Math.round(sec / 1), 'second')
    if (abs < 3600) return rtf.format(Math.round(sec / 60), 'minute')
    if (abs < 86400) return rtf.format(Math.round(sec / 3600), 'hour')
    return rtf.format(Math.round(sec / 86400), 'day')
  }
}

const STATUS_CLS: Record<string, string> = {
  success: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-red-500/15 text-red-300',
  partial: 'bg-amber-500/15 text-amber-300',
  running: 'bg-sky-500/15 text-sky-300',
  info: 'bg-slate-500/20 text-slate-300',
}
const chip = (s: string) => STATUS_CLS[s] || 'bg-slate-500/20 text-slate-300'

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: string }) {
  return (
    <div className="cyber-card p-4">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-1 tabular-nums ${tone || 'text-white'}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function Level1DashboardPanel() {
  const t = useT()
  const ago = useAgo()
  const q = useQuery<L1Data>({
    queryKey: ['level1-dashboard'],
    queryFn: fetchDashboard,
    staleTime: 60_000,
    retry: 1,
  })
  const d = q.data

  if (q.isLoading) {
    return (
      <div className="cyber-card p-5 text-sm text-slate-500 inline-flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {t('l1d_loading')}
      </div>
    )
  }
  if (q.isError || !d) {
    return (
      <div className="cyber-card p-5 text-sm text-red-300 flex items-center justify-between">
        <span>{t('l1d_error')}</span>
        <button type="button" onClick={() => q.refetch()} className="text-xs text-slate-200 underline">{t('l1d_refresh')}</button>
      </div>
    )
  }

  const online = d.users.filter((u) => u.online)
  const offline = d.users.filter((u) => !u.online)
  const s = d.stats
  const ready = s.servers_by_status.ready || 0
  const maxDay = Math.max(1, ...s.daily_7d.map((x) => x.success + x.failed + x.other))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white inline-flex items-center gap-2">
          <Wrench size={15} /> {t('l1d_title')}
        </h2>
        <button type="button" onClick={() => q.refetch()} disabled={q.isFetching}
          className="px-2.5 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-[11px] text-slate-200 inline-flex items-center gap-1.5 disabled:opacity-50">
          <RefreshCw size={12} className={q.isFetching ? 'animate-spin' : ''} /> {t('l1d_refresh')}
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <Kpi label={t('l1d_kpi_online')} value={online.length} sub={t('l1d_kpi_online_sub', { m: d.online_window_minutes })} tone="text-emerald-300" />
        <Kpi label={t('l1d_kpi_jobs24')} value={s.jobs_24h} sub={t('l1d_kpi_jobs7', { n: s.jobs_7d })} />
        <Kpi label={t('l1d_kpi_rate')} value={s.success_rate_7d == null ? '—' : `%${s.success_rate_7d}`} sub={t('l1d_kpi_rate_sub')} tone={s.success_rate_7d != null && s.success_rate_7d < 80 ? 'text-amber-300' : 'text-white'} />
        <Kpi label={t('l1d_kpi_running')} value={s.running_now} tone={s.running_now ? 'text-sky-300' : 'text-white'} />
        <Kpi label={t('l1d_kpi_failed')} value={s.failed_24h} tone={s.failed_24h ? 'text-red-300' : 'text-white'} />
        <Kpi label={t('l1d_kpi_servers')} value={`${ready}/${s.servers_total}`} sub={t('l1d_kpi_servers_sub')} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="cyber-card p-5">
          <h3 className="text-xs font-medium text-white mb-3 inline-flex items-center gap-2"><Users size={14} /> {t('l1d_users')}</h3>
          {d.users.length === 0 ? <div className="text-xs text-slate-500">—</div> : (
            <ul className="space-y-1.5">
              {[...online, ...offline].map((u) => (
                <li key={u.username} className="flex items-center justify-between text-xs">
                  <span className="inline-flex items-center gap-2 min-w-0">
                    <span className={`w-2 h-2 rounded-full ${u.online ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                    <span className={`truncate ${u.online ? 'text-slate-100' : 'text-slate-400'}`}>{u.username}{u.is_me ? ` (${t('l1d_me')})` : ''}</span>
                    <span className="text-[10px] text-slate-500">{u.role}</span>
                  </span>
                  <span className="text-[11px] text-slate-500 whitespace-nowrap">
                    {u.online ? t('l1d_online_since', { at: ago(u.login_at) }) : t('l1d_last_seen', { at: ago(u.last_seen_at) })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="cyber-card p-5">
          <h3 className="text-xs font-medium text-white mb-3 inline-flex items-center gap-2"><Server size={14} /> {t('l1d_servers')}</h3>
          {d.recent_servers.length === 0 ? <div className="text-xs text-slate-500">{t('l1d_no_activity')}</div> : (
            <ul className="space-y-2">
              {d.recent_servers.map((x) => (
                <li key={x.server_id} className="text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-100 truncate">{x.hostname || x.ip}</span>
                    <span className="inline-flex items-center gap-2 whitespace-nowrap">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${chip(x.last_status)}`}>{x.last_status}</span>
                      <span className="text-[11px] text-slate-500">{ago(x.at)}</span>
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 truncate">{x.username} · {x.last_action.replace(/^job\.run\./, '')} · {t('l1d_op_count', { n: x.op_count })}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="cyber-card p-5 overflow-x-auto">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-medium text-white">{t('l1d_ops')}</h3>
          <Link to="/level1/jobs" className="text-[11px] text-sky-400 hover:text-sky-300">{t('l1d_all_jobs')}</Link>
        </div>
        {d.recent_ops.length === 0 ? <div className="text-xs text-slate-500">{t('l1d_no_activity')}</div> : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-1 pr-3">{t('l1d_col_op')}</th><th className="pr-3">{t('l1d_col_user')}</th>
                <th className="pr-3">{t('l1d_col_hosts')}</th><th className="pr-3">{t('l1d_col_status')}</th><th className="text-right">{t('l1d_col_when')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {d.recent_ops.map((o) => (
                <tr key={o.id} className="text-slate-300">
                  <td className="py-1.5 pr-3"><span className="text-slate-100">{o.title}</span> <span className="text-[10px] text-slate-500">{o.module}/{o.action}{o.dry_run ? ' · dry-run' : ''}</span></td>
                  <td className="pr-3">{o.username}</td>
                  <td className="pr-3 text-slate-400">{o.hosts.join(', ')}{o.host_count > o.hosts.length ? ` +${o.host_count - o.hosts.length}` : ''}{o.host_count === 0 ? '—' : ''}</td>
                  <td className="pr-3"><span className={`px-1.5 py-0.5 rounded-full text-[10px] ${chip(o.status)}`}>{o.status}</span></td>
                  <td className="text-right text-slate-500 whitespace-nowrap">{ago(o.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="cyber-card p-5">
          <h3 className="text-xs font-medium text-white mb-3">{t('l1d_trend')}</h3>
          <div className="flex items-end gap-2 h-24">
            {s.daily_7d.map((x) => {
              const tot = x.success + x.failed + x.other
              return (
                <div key={x.date} className="flex-1 flex flex-col items-center justify-end h-full" title={`${x.date}: ${x.success} ✓ / ${x.failed} ✗`}>
                  <div className="w-full flex flex-col-reverse rounded overflow-hidden" style={{ height: `${(tot / maxDay) * 100}%`, minHeight: tot ? 3 : 0 }}>
                    <div className="bg-emerald-500" style={{ flex: x.success }} />
                    <div className="bg-red-500" style={{ flex: x.failed }} />
                    <div className="bg-slate-500" style={{ flex: x.other }} />
                  </div>
                  <span className="text-[9px] text-slate-600 mt-1">{x.date.slice(8)}</span>
                </div>
              )
            })}
          </div>
        </div>

        <div className="cyber-card p-5">
          <h3 className="text-xs font-medium text-white mb-3">{t('l1d_top')}</h3>
          <div className="text-[10px] text-slate-500 mb-1">{t('l1d_top_users')}</div>
          <ul className="space-y-0.5 mb-3">
            {s.top_operators_7d.length === 0 && <li className="text-xs text-slate-600">—</li>}
            {s.top_operators_7d.map((o) => <li key={o.username} className="flex justify-between text-xs text-slate-300"><span>{o.username}</span><span className="tabular-nums text-slate-500">{o.count}</span></li>)}
          </ul>
          <div className="text-[10px] text-slate-500 mb-1">{t('l1d_top_actions')}</div>
          <ul className="space-y-0.5">
            {s.top_actions_7d.length === 0 && <li className="text-xs text-slate-600">—</li>}
            {s.top_actions_7d.map((o) => <li key={o.action} className="flex justify-between text-xs text-slate-300"><span>{o.action}</span><span className="tabular-nums text-slate-500">{o.count}</span></li>)}
          </ul>
        </div>

        <div className="cyber-card p-5">
          <h3 className="text-xs font-medium text-white mb-3 inline-flex items-center gap-2"><AlertTriangle size={14} className="text-amber-300" /> {t('l1d_attention')}</h3>
          {d.attention.failed_jobs.length === 0 && d.attention.problem_servers.length === 0 ? (
            <div className="text-xs text-emerald-300 inline-flex items-center gap-1.5"><CheckCircle2 size={13} /> {t('l1d_all_good')}</div>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {d.attention.failed_jobs.map((j) => (
                <li key={`j${j.id}`} className="text-slate-300 inline-flex items-start gap-1.5"><XCircle size={12} className="text-red-400 mt-0.5 shrink-0" />
                  <span>{j.title} <span className="text-slate-500">· {j.username} · {ago(j.at)}</span></span></li>
              ))}
              {d.attention.problem_servers.map((p) => (
                <li key={`s${p.server_id}`} className="text-slate-300 inline-flex items-start gap-1.5"><Server size={12} className="text-amber-300 mt-0.5 shrink-0" />
                  <span>{p.hostname} <span className="text-slate-500">· {p.status}</span></span></li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
