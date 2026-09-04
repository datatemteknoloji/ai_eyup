import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import HypervisorChatPage from './HypervisorChat'
import LinuxChatPage from './Chat'
import WindowsChatPage from './WindowsChat'
import ServerComparePanel from './ServerComparePanel'
import {
  BarChart3, Zap, Server, TrendingUp, DollarSign,
  AlertTriangle, Cpu, ChevronRight, Clock,
  CheckCircle2, XCircle, Loader2, Download, Bot, FileDown, Eye, HardDrive,
  Activity, Layers, Target, Network, PackageOpen,
  Building2, ArrowUpRight, ArrowDownRight, Minus, Info, RefreshCw, Radar, Shield,
  GitCompare, FileBarChart2,
} from 'lucide-react'
import { exportMarkdownToPrintWindow } from '../utils/pdfExport'
import { chatMarkdownComponents } from '../components/chatMarkdown'
import type { PlatformKey } from '../config/platformAiops'
import {
  PLATFORM_REPORT_CATALOGS,
  PLATFORM_REPORT_TITLE_KEYS,
  PLATFORM_REPORT_SUBTITLE_KEYS,
  reportsApiBase,
} from '../config/infraReportCatalog'

const COLOR_MAP: Record<string, string> = {
  blue:    'bg-blue-500/10 text-blue-400 border-blue-500/20',
  purple:  'bg-sky-500/10 text-sky-400 border-sky-500/20',
  red:     'bg-red-500/10 text-red-400 border-red-500/20',
  green:   'bg-green-500/10 text-green-400 border-green-500/20',
  amber:   'bg-amber-500/10 text-amber-400 border-amber-500/20',
  teal:    'bg-teal-500/10 text-teal-400 border-teal-500/20',
  orange:  'bg-orange-500/10 text-orange-400 border-orange-500/20',
  slate:   'bg-slate-500/10 text-slate-400 border-slate-500/20',
  pink:    'bg-pink-500/10 text-pink-400 border-pink-500/20',
  cyan:    'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  indigo:  'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  yellow:  'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  lime:    'bg-lime-500/10 text-lime-400 border-lime-500/20',
}

const dateLoc = (locale: string) => locale === 'en' ? 'en-GB' : 'tr-TR'
const SEV_KEYS: Record<string, TranslationKey> = {
  Kritik: 'rpt_sev_critical', critical: 'rpt_sev_critical',
  Yüksek: 'rpt_sev_high',
  Uyarı: 'rpt_sev_warning', warning: 'rpt_sev_warning',
  Normal: 'rpt_sev_normal',
  Düşük: 'rpt_sev_low',
}
const QUALITY_KEYS: Record<string, TranslationKey> = {
  'İyi': 'rpt_quality_good',
  'Orta': 'rpt_quality_mid',
  'Düşük': 'rpt_quality_low',
}
function sevT(level: string, t: (k: TranslationKey, vars?: Record<string, string | number>) => string) {
  return SEV_KEYS[level] ? t(SEV_KEYS[level]) : level
}
function qualityT(level: string, t: (k: TranslationKey, vars?: Record<string, string | number>) => string) {
  return QUALITY_KEYS[level] ? t(QUALITY_KEYS[level]) : level
}


// ── Ortak UI Bileşenleri ─────────────────────────────────────────────────────

function ScoreGauge({ score, max = 100, label, size = 100 }: {
  score: number; max?: number; label?: string; size?: number
}) {
  const pct = Math.min(1, score / max)
  const r = 38; const cx = 50; const cy = 50
  const circumference = 2 * Math.PI * r
  const dashOffset = circumference * (1 - pct)
  const color = pct > 0.8 ? '#22c55e' : pct > 0.6 ? '#f59e0b' : pct > 0.4 ? '#f97316' : '#ef4444'
  return (
    <div className="flex flex-col items-center" style={{ width: size, height: size + 20 }}>
      <svg width={size} height={size} viewBox="0 0 100 100">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth="8" />
        <circle
          cx={cx} cy={cy} r={r} fill="none"
          stroke={color} strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 50 50)"
          style={{ transition: 'stroke-dashoffset 1s ease' }}
        />
        <text x="50" y="48" textAnchor="middle" fill="white" fontSize="18" fontWeight="bold">{score}</text>
        <text x="50" y="62" textAnchor="middle" fill="#64748b" fontSize="9">/{max}</text>
      </svg>
      {label && <span className="text-slate-400 text-xs text-center mt-1">{label}</span>}
    </div>
  )
}

function DataQualityBanner({ quality }: { quality: any }) {
  const t = useT()
  const { locale } = useLocale()
  if (!quality) return null
  const level = quality.quality_level || 'Orta'
  const levelStyles: Record<string, string> = {
    'İyi': 'border-green-500/30 bg-green-500/10 text-green-300',
    'Orta': 'border-amber-500/30 bg-amber-500/10 text-amber-200',
    'Düşük': 'border-red-500/30 bg-red-500/10 text-red-200',
  }
  const lastMetric = quality.last_host_metric_at
    ? new Date(quality.last_host_metric_at).toLocaleString(dateLoc(locale))
    : t('rpt_quality_none')
  return (
    <div className={`rounded-xl border p-4 ${levelStyles[level] || levelStyles['Orta']}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Info size={16} className="flex-shrink-0 mt-0.5 opacity-80" />
          <div>
            <p className="text-sm font-medium">{t('rpt_quality', { level: qualityT(level, t) })}</p>
            <p className="text-xs opacity-80 mt-1">
              {t('rpt_quality_line', { vm: quality.vm_total ?? 0, meta: quality.vm_metadata_completeness_pct ?? 0, hosts: quality.host_metrics_hosts ?? 0, last: lastMetric })}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="px-2 py-1 rounded-md bg-black/20">{t('rpt_hv_linked', { n: quality.vm_with_hypervisor_pct ?? 0 })}</span>
          <span className="px-2 py-1 rounded-md bg-black/20">{t('rpt_missing_disk', { n: quality.vm_missing_disk_count ?? 0 })}</span>
          <span className="px-2 py-1 rounded-md bg-black/20">{t('rpt_stale_sync', { n: quality.vm_stale_sync_count ?? 0 })}</span>
        </div>
      </div>
      {quality.warnings?.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs opacity-90 list-disc list-inside">
          {quality.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </div>
  )
}

function KpiCard({ label, value, sub, color = 'slate', icon, trend }: {
  label: string; value: string | number; sub?: string; color?: string
  icon?: React.ReactNode; trend?: 'up' | 'down' | 'flat'
}) {
  const colors: Record<string, string> = {
    blue: 'border-blue-500/30 bg-blue-500/5',
    green: 'border-green-500/30 bg-green-500/5',
    red: 'border-red-500/30 bg-red-500/5',
    amber: 'border-amber-500/30 bg-amber-500/5',
    purple: 'border-sky-500/30 bg-sky-500/5',
    slate: 'border-slate-700/50 bg-slate-800/40',
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    teal: 'border-teal-500/30 bg-teal-500/5',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color] || colors.slate}`}>
      <div className="flex items-start justify-between">
        <span className="text-slate-400 text-xs">{label}</span>
        <div className="flex items-center gap-1">
          {trend === 'up' && <ArrowUpRight size={12} className="text-green-400" />}
          {trend === 'down' && <ArrowDownRight size={12} className="text-red-400" />}
          {trend === 'flat' && <Minus size={12} className="text-slate-500" />}
          {icon && <span className="text-slate-500">{icon}</span>}
        </div>
      </div>
      <div className="mt-2 text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-slate-500 text-xs mt-1">{sub}</div>}
    </div>
  )
}

function ProgressBar({ pct, label, sub, showPct = true }: {
  pct: number; label: string; sub?: string; showPct?: boolean
}) {
  const color = pct > 85 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : pct > 50 ? 'bg-blue-500' : 'bg-green-500'
  const textColor = pct > 85 ? 'text-red-400' : pct > 70 ? 'text-amber-400' : 'text-blue-400'
  return (
    <div>
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-slate-300">{label}</span>
        <span className={`font-medium ${textColor}`}>{showPct ? `${pct}%` : sub}</span>
      </div>
      <div className="h-2 bg-slate-700/60 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-700`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
      {sub && showPct && <div className="text-slate-500 text-xs mt-0.5">{sub}</div>}
    </div>
  )
}

function SeverityBadge({ level }: { level: string }) {
  const t = useT()
  const map: Record<string, string> = {
    Kritik: 'bg-red-500/20 text-red-400 border-red-500/30',
    critical: 'bg-red-500/20 text-red-400 border-red-500/30',
    Yüksek: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    Uyarı: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    warning: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    Normal: 'bg-green-500/20 text-green-400 border-green-500/30',
    Düşük: 'bg-green-500/20 text-green-400 border-green-500/30',
  }
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${map[level] || 'bg-slate-700 text-slate-400 border-slate-600'}`}>
      {sevT(level, t)}
    </span>
  )
}

function HorzBar({ value, max, label, color = 'blue' }: {
  value: number; max: number; label?: string; color?: string
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  const colors: Record<string, string> = {
    blue: 'bg-blue-500', red: 'bg-red-500', green: 'bg-green-500',
    amber: 'bg-amber-500', purple: 'bg-sky-500', emerald: 'bg-emerald-500',
  }
  return (
    <div className="flex items-center gap-2 text-xs">
      {label && <span className="text-slate-400 w-28 truncate text-right">{label}</span>}
      <div className="flex-1 h-2 bg-slate-700/50 rounded-full overflow-hidden">
        <div className={`h-full ${colors[color] || colors.blue} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-slate-300 w-10 text-right font-medium">{value}</span>
    </div>
  )
}

function SectionHeader({ title, count, icon }: { title: string; count?: number; icon?: React.ReactNode }) {
  const t = useT()
  return (
    <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-700/40">
      <div className="flex items-center gap-2">
        {icon && <span className="text-slate-500">{icon}</span>}
        <h3 className="text-slate-200 text-sm font-semibold">{title}</h3>
      </div>
      {count !== undefined && (
        <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">{t('rpt_n_items', { n: count })}</span>
      )}
    </div>
  )
}

// ── Report Card ──────────────────────────────────────────────────────────────

function ReportCard({
  type, title, icon, color, desc,
  onGenerate, isLoading, lastGenerated, badge,
}: {
  type: string; title: string; icon: React.ReactNode; color: string; desc: string
  onGenerate: (type: string) => void
  isLoading: boolean
  lastGenerated?: string
  badge?: string
}) {
  const t = useT()
  const { locale } = useLocale()
  const cls = COLOR_MAP[color] || COLOR_MAP['slate']
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/80 transition-all group flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-lg border flex items-center justify-center flex-shrink-0 ${cls}`}>
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-white text-sm font-medium">{title}</h3>
            {badge && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-lime-500/15 text-lime-400 border border-lime-500/25">
                {badge}
              </span>
            )}
          </div>
          <p className="text-slate-400 text-xs mt-0.5 leading-relaxed">{desc}</p>
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 mt-auto pt-1 border-t border-slate-700/40">
        {lastGenerated
          ? <span className="text-[10px] text-slate-600 flex items-center gap-1">
              <Clock size={10} />
              {new Date(lastGenerated).toLocaleString(dateLoc(locale), { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
            </span>
          : <span className="text-[10px] text-slate-700">{t('rpt_never')}</span>
        }
        <button
          onClick={(e) => { e.stopPropagation(); onGenerate(type) }}
          disabled={isLoading}
          title={t('rpt_gen_title')}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600/20 text-blue-400 hover:bg-blue-600/40 hover:text-blue-300 border border-blue-500/20 transition-all disabled:opacity-50"
        >
          {isLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
          {isLoading ? t('rpt_fetching') : t('rpt_new')}
        </button>
      </div>
    </div>
  )
}

// ── Rapor Viewer ─────────────────────────────────────────────────────────────

function ReportViewer({ type, title, data, markdown, onClose, onRegenerate, regenerating, preferMarkdown }: {
  type: string; title: string; data: Record<string, unknown>; markdown?: string; onClose: () => void
  onRegenerate?: (type: string) => void; regenerating?: boolean
  preferMarkdown?: boolean
}) {
  const t = useT()
  const { locale } = useLocale()
  const [tab, setTab] = useState<'visual' | 'markdown' | 'raw'>(preferMarkdown ? 'markdown' : 'visual')
  const tabs = [
    { id: 'visual', label: t('rpt_visual'), Icon: BarChart3 },
    { id: 'markdown', label: t('rpt_md'), Icon: FileDown },
    { id: 'raw', label: t('rpt_json_tab'), Icon: null },
  ] as const

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div>
            <h2 className="text-white font-semibold text-lg">{title}</h2>
            <p className="text-slate-500 text-xs mt-0.5">
              {(data as any).generated_at
                ? t('rpt_generated', { dt: new Date((data as any).generated_at).toLocaleString(dateLoc(locale)) })
                : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {onRegenerate && (
              <button
                onClick={() => onRegenerate(type)}
                disabled={regenerating}
                title={t('rpt_regen_title')}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600/20 text-blue-400 hover:bg-blue-600/40 hover:text-blue-300 border border-blue-500/20 transition-all disabled:opacity-50"
              >
                {regenerating ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                {regenerating ? t('rpt_fetching') : t('rpt_new')}
              </button>
            )}
            <button
              onClick={() => {
                const content = markdown || `# ${title}\n\n${t('rpt_no_data_md')}`
                exportMarkdownToPrintWindow(content, {
                  title,
                  subtitle: t('rpt_generated', { dt: (data as any).generated_at?.slice(0, 16) || '' }),
                  filename: `${type}_${new Date().toISOString().split('T')[0]}`,
                })
              }}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-red-900/40 text-red-300 hover:bg-red-900/60 border border-red-700/30 transition-all"
            >
              <FileDown size={12} /> {t('rpt_pdf')}
            </button>
            <button
              onClick={() => {
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a'); a.href = url
                a.download = `${type}_${new Date().toISOString().split('T')[0]}.json`
                a.click(); URL.revokeObjectURL(url)
              }}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600 transition-all"
            >
              <Download size={12} /> {t('rpt_json')}
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl px-2 leading-none">×</button>
          </div>
        </div>
        {/* Tabs */}
        <div className="flex gap-1 px-6 pt-3 border-b border-slate-800">
          {tabs.map(tb => (
            <button key={tb.id} onClick={() => setTab(tb.id)}
              className={`text-xs px-4 py-2 rounded-t-lg transition-all border-b-2 -mb-px ${
                tab === tb.id
                  ? 'border-blue-500 text-blue-400 bg-slate-800/50'
                  : 'border-transparent text-slate-500 hover:text-white hover:bg-slate-800/30'
              }`}>
              <span className="inline-flex items-center gap-1.5">
                {tb.Icon && <tb.Icon size={12} strokeWidth={2} />}
                {tb.label}
              </span>
            </button>
          ))}
        </div>
        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {tab === 'visual' && <ReportSummaryView type={type} data={data} />}
          {tab === 'markdown' && (
            markdown
              ? <div className="chat-response-content prose prose-invert prose-sm max-w-none min-w-0
                  prose-headings:text-blue-300 prose-headings:font-semibold
                  prose-h1:text-xl prose-h2:text-base prose-h2:border-b prose-h2:border-slate-700 prose-h2:pb-1
                  prose-strong:text-white prose-code:text-pink-300 prose-code:bg-slate-800
                  prose-li:text-slate-300">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{markdown}</ReactMarkdown>
                </div>
              : <p className="text-slate-500 text-sm">{t('rpt_md_loading')}</p>
          )}
          {tab === 'raw' && (
            <pre className="text-xs text-slate-300 bg-slate-800/50 rounded-xl p-4 overflow-x-auto leading-relaxed">
              {JSON.stringify(data, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════
//  19 RAPOR GÖRSELİ
// ═══════════════════════════════════════════════════════════════════════════

function ExecSummaryView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const infra = d.infrastructure || {}
  const util = d.utilization || {}
  const health = d.health || {}
  const hosts = d.hosts_detail || []
  const rl = d.risk_level || 'Normal'
  const riskScore = rl === 'Kritik' ? 25 : rl === 'Yüksek' ? 58 : 88
  return (
    <div className="space-y-5">
      {/* Top row: gauge + KPIs */}
      <div className="grid grid-cols-4 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          <ScoreGauge score={riskScore} max={100} label={t('rpt_env_health')} size={96} />
          <SeverityBadge level={rl === 'Normal' ? 'Normal' : rl} />
        </div>
        <KpiCard label={t('rpt_esx_kvm')} value={infra.host_count ?? 0} color="blue" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_total_vm')} value={infra.vm_total ?? 0} color="slate" />
        <KpiCard label={t('rpt_running_vm')} value={infra.vm_powered_on ?? 0} sub={t('rpt_n_off', { n: infra.vm_powered_off ?? 0 })} color="green" icon={<Zap size={12} />} />
      </div>
      {/* Utilization row */}
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <SectionHeader title={t('rpt_avg_util')} icon={<Activity size={14} />} />
        <div className="space-y-3">
          <ProgressBar pct={util.avg_cpu_pct ?? 0} label={t('rpt_avg_cpu')} sub={t('rpt_highest', { name: util.highest_cpu_host ?? '-' })} />
          <ProgressBar pct={util.avg_mem_pct ?? 0} label={t('rpt_avg_mem')} sub={t('rpt_highest', { name: util.highest_mem_host ?? '-' })} />
          <ProgressBar pct={util.avg_storage_pct ?? 0} label={t('rpt_avg_disk')} />
        </div>
      </div>
      {/* Health alerts */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_crit_events')} value={health.active_critical_events ?? 0}
          color={(health.active_critical_events ?? 0) > 0 ? 'red' : 'green'}
          icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_warn_events')} value={health.active_warning_events ?? 0}
          color={(health.active_warning_events ?? 0) > 0 ? 'amber' : 'green'}
          icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_maint')} value={health.hosts_in_maintenance ?? 0}
          color={(health.hosts_in_maintenance ?? 0) > 0 ? 'amber' : 'green'}
          icon={<Server size={12} />} />
      </div>
      {/* Host detail */}
      {hosts.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_host_status')} count={hosts.length} icon={<Server size={14} />} />
          <div className="space-y-3">
            {hosts.map((h: any) => (
              <div key={h.host} className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/30">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${h.state === 'connected' ? 'bg-green-500' : 'bg-red-500'}`} />
                    <span className="text-white font-medium text-sm">{h.host}</span>
                    {h.maintenance && <SeverityBadge level="Uyarı" />}
                  </div>
                  <span className="text-slate-400 text-xs">{t('rpt_vm_free_mem', { run: h.vms_running, total: h.vms_total, gb: h.mem_free_gb })}</span>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <ProgressBar pct={h.cpu_pct} label="CPU" />
                  <ProgressBar pct={h.mem_pct} label={t('memory')} />
                  <ProgressBar pct={h.ds_pct} label="Disk" />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {(d.recommendations?.length ?? 0) > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4">
          <SectionHeader title={t('rpt_actions')} icon={<Target size={14} />} />
          <ul className="space-y-2 mt-2">
            {d.recommendations.map((rec: string, i: number) => (
              <li key={i} className="text-sm text-blue-100 flex items-start gap-2">
                <ChevronRight size={14} className="flex-shrink-0 mt-0.5 text-blue-400" />
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function CapacityView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const [dsTab, setDsTab] = useState<string | null>(null)
  const dsBreakdown: Record<string, any> = d.datastore_vm_disk || {}
  const dsList = Object.entries(dsBreakdown).sort((a: any, b: any) => (b[1].allocated_disk_gb || 0) - (a[1].allocated_disk_gb || 0))
  const items = d.capacity_items || []
  return (
    <div className="space-y-5">
      {d.warnings?.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3 flex gap-2">
          <AlertTriangle size={16} className="text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            {d.warnings.map((w: string, i: number) => (
              <p key={i} className="text-amber-300 text-sm">{w}</p>
            ))}
          </div>
        </div>
      )}
      {/* Overall */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_host_count')} value={items.length} color="blue" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_overall')} value={sevT(d.overall_status ?? 'Normal', t)}
          color={d.overall_status === 'Kritik' ? 'red' : d.overall_status === 'Uyarı' ? 'amber' : 'green'} />
        <KpiCard label={t('rpt_cap_warn')} value={d.warnings?.length ?? 0}
          color={(d.warnings?.length ?? 0) > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
      </div>
      {/* Host cards */}
      <div className="space-y-3">
        {items.map((item: any) => (
          <div key={item.host} className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
            <div className="flex items-center justify-between mb-3">
              <span className="text-white font-semibold">{item.host}</span>
              <div className="flex items-center gap-2">
                <span className="text-slate-400 text-xs">{item.vms_running}/{item.vms_total} VM</span>
                <SeverityBadge level={item.status} />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <ProgressBar pct={item.cpu?.used_pct ?? 0} label="CPU" sub={t('rpt_n_cores', { n: item.cpu?.cores ?? 0 })} />
                {item.cpu?.avg_30d !== null && (
                  <p className="text-slate-500 text-xs mt-1">{t('rpt_avg_30d', { n: item.cpu?.avg_30d })}</p>
                )}
              </div>
              <div>
                <ProgressBar pct={item.memory?.used_pct ?? 0} label={t('memory')} sub={t('rpt_gb_free', { n: item.memory?.free_gb ?? 0 })} />
                {item.memory?.days_to_80pct && (
                  <p className="flex items-center gap-1 text-amber-400 text-xs mt-1"><Zap size={11} strokeWidth={2} /> {t('rpt_days_80', { n: item.memory.days_to_80pct })}</p>
                )}
              </div>
              <div>
                <ProgressBar pct={item.storage?.used_pct ?? 0} label="Disk" sub={t('rpt_gb_free', { n: item.storage?.free_gb ?? 0 })} />
                {item.storage?.days_to_80pct && (
                  <p className="flex items-center gap-1 text-amber-400 text-xs mt-1"><Zap size={11} strokeWidth={2} /> {t('rpt_days_80', { n: item.storage.days_to_80pct })}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      {/* Datastore breakdown */}
      {dsList.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_ds_alloc')} icon={<HardDrive size={14} />} count={dsList.length} />
          <div className="flex flex-wrap gap-1.5 mb-3">
            {dsList.map(([ds, info]: any) => (
              <button key={ds} onClick={() => setDsTab(dsTab === ds ? null : ds)}
                className={`text-xs px-2.5 py-1 rounded-lg border transition-all ${
                  dsTab === ds ? 'bg-blue-600/30 border-blue-500/60 text-blue-300' : 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:text-white'
                }`}>
                {ds} <span className="opacity-60">({t('rpt_ds_vm_gb', { n: info.vm_count, gb: info.allocated_disk_gb })})</span>
              </button>
            ))}
          </div>
          <div className="space-y-2">
            {dsList.map(([ds, info]: any) => (
              <div key={ds} onClick={() => setDsTab(dsTab === ds ? null : ds)} className="cursor-pointer">
                <HorzBar value={info.allocated_disk_gb} max={Math.max(...dsList.map(([, v]: any) => v.allocated_disk_gb))} label={ds} color="blue" />
              </div>
            ))}
          </div>
          {dsTab && dsBreakdown[dsTab] && (
            <div className="mt-3 bg-slate-800/50 rounded-xl overflow-hidden text-xs border border-slate-700/30">
              <div className="px-3 py-2 border-b border-slate-700/50 text-slate-300 font-medium">
                {t('rpt_ds_alloc_line', { ds: dsTab, n: dsBreakdown[dsTab].vm_count, gb: dsBreakdown[dsTab].allocated_disk_gb })}
              </div>
              <table className="w-full">
                <thead><tr className="border-b border-slate-700/30 text-slate-500">
                  <th className="text-left px-3 py-1.5">VM</th>
                  <th className="text-right px-3 py-1.5">Disk (GB)</th>
                  <th className="text-right px-3 py-1.5">{t('rpt_power')}</th>
                </tr></thead>
                <tbody>
                  {(dsBreakdown[dsTab].vms || []).map((vm: any) => (
                    <tr key={vm.vm} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                      <td className="px-3 py-1.5 text-white">{vm.vm}</td>
                      <td className="px-3 py-1.5 text-right text-blue-400 font-medium">{vm.disk_gb}</td>
                      <td className="px-3 py-1.5 text-right">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${['POWERED_ON','up','running','poweredOn'].includes(vm.power_state) ? 'bg-green-500/20 text-green-400' : 'bg-slate-500/20 text-slate-500'}`}>
                          {vm.power_state}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Linux/Windows (bare-metal sunucu) ve Exadata (node envanteri) kapasite
// raporları host/VM/datastore kavramı içermez — `CapacityView` (virt) ile
// aynı görsel şemayı paylaşamaz, bu yüzden ayrı, sunucu/node bazlı bir görsel.
function ServerCapacityView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const servers: any[] = d.top_servers || []
  const nodes: any[] = d.nodes || []

  if (servers.length > 0 || d.sampled_servers !== undefined) {
    const maxCpu = Math.max(...servers.map((s) => s.cpu_usage_percent || 0), 1)
    return (
      <div className="space-y-5">
        <div className="grid grid-cols-4 gap-3">
          <KpiCard label={t('rpt_sampled')} value={d.sampled_servers ?? servers.length} color="blue" icon={<Server size={12} />} />
          <KpiCard label={t('rpt_high_cpu')} value={d.high_cpu_count ?? 0}
            color={(d.high_cpu_count ?? 0) > 0 ? 'red' : 'green'} icon={<Cpu size={12} />} />
          <KpiCard label={t('rpt_high_mem')} value={d.high_memory_count ?? 0}
            color={(d.high_memory_count ?? 0) > 0 ? 'amber' : 'green'} />
          <KpiCard label={t('rpt_high_disk')} value={d.high_disk_count ?? 0}
            color={(d.high_disk_count ?? 0) > 0 ? 'amber' : 'green'} icon={<HardDrive size={12} />} />
        </div>
        {servers.length > 0 ? (
          <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <SectionHeader title={t('rpt_top_cpu')} icon={<Cpu size={14} />} count={servers.length} />
            <div className="space-y-2 mt-2">
              {servers.map((s, i) => (
                <div key={i} className="grid grid-cols-[1fr_auto] items-center gap-3">
                  <HorzBar value={s.cpu_usage_percent || 0} max={maxCpu} label={s.server} color={s.cpu_usage_percent >= 85 ? 'red' : 'blue'} />
                  <span className="text-[10px] text-slate-500 whitespace-nowrap">
                    {t('rpt_mem_disk', { mem: s.memory_usage_percent ?? '—', disk: s.disk_root_usage_percent ?? '—' })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-slate-500 bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <Info size={14} /> {t('rpt_no_live_metrics')}
          </div>
        )}
      </div>
    )
  }

  // Exadata: node envanteri (çekirdek/Memory tahsisi) — canlı kullanım metriği yok.
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_total_node')} value={nodes.length} color="blue" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_total_vcpu')} value={nodes.reduce((a, n) => a + (n.cpu_cores || 0), 0)} color="slate" icon={<Cpu size={12} />} />
        <KpiCard label={t('rpt_total_mem_gb')} value={nodes.reduce((a, n) => a + (n.memory_gb || 0), 0)} color="slate" />
      </div>
      {nodes.length > 0 ? (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <SectionHeader title={t('rpt_node_inv')} icon={<HardDrive size={14} />} count={nodes.length} />
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/40">
                  <th className="text-left font-medium py-2 pr-3">Node</th>
                  <th className="text-left font-medium py-2 pr-3">{t('rpt_role')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('rpt_rack')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('col_status')}</th>
                  <th className="text-right font-medium py-2 pr-3">vCPU</th>
                  <th className="text-right font-medium py-2">Memory (GB)</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((n, i) => (
                  <tr key={i} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-2 pr-3 text-slate-200 font-medium whitespace-nowrap">{n.name}</td>
                    <td className="py-2 pr-3 text-slate-400">{n.role}</td>
                    <td className="py-2 pr-3 text-slate-400">{n.rack || '—'}</td>
                    <td className="py-2 pr-3"><SeverityBadge level={n.status || 'Normal'} /></td>
                    <td className="py-2 pr-3 text-right text-slate-300">{n.cpu_cores}</td>
                    <td className="py-2 text-right text-slate-300">{n.memory_gb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-slate-500 bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <Info size={14} /> {t('rpt_no_exa_nodes')}
        </div>
      )}
    </div>
  )
}

function RiskView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const risks = d.risks || {}
  const rs = d.risk_score ?? 0
  return (
    <div className="space-y-5">
      {/* Score + KPIs */}
      <div className="grid grid-cols-4 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          {/* Risk Dashboard'da "Güvenlik Skoru" yanıltıcıydı — bu skor CPU/Memory/storage/tools
              sağlığından türetiliyor, güvenlik açığı taraması değil. */}
          <ScoreGauge score={100 - rs} max={100} label={t('rpt_health_score')} size={96} />
          <SeverityBadge level={d.risk_level ?? 'Normal'} />
        </div>
        <KpiCard label={t('rpt_risk_score')} value={`${rs}/100`} color={rs > 60 ? 'red' : rs > 30 ? 'amber' : 'green'} icon={<Target size={12} />} />
        <KpiCard label={t('rpt_crit_events')} value={d.critical_event_count ?? 0} color={(d.critical_event_count ?? 0) > 0 ? 'red' : 'green'} />
        <KpiCard label={t('rpt_warn_events')} value={d.warning_event_count ?? 0} color={(d.warning_event_count ?? 0) > 0 ? 'amber' : 'green'} />
      </div>
      {/* Risk categories */}
      <div className="grid grid-cols-2 gap-3">
        {risks.high_cpu_hosts?.length > 0 && (
          <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-2">
              <Cpu size={14} className="text-red-400" />
              <span className="text-red-300 text-xs font-medium">{t('rpt_high_cpu_hosts')}</span>
              <span className="text-red-500 text-xs">({risks.high_cpu_hosts.length})</span>
            </div>
            {risks.high_cpu_hosts.map((h: any) => (
              <div key={h.host} className="flex justify-between text-xs py-1 border-b border-red-500/10 last:border-0">
                <span className="text-slate-300">{h.host}</span>
                <span className="text-red-400 font-medium">%{h.cpu_pct}</span>
              </div>
            ))}
          </div>
        )}
        {risks.high_memory_hosts?.length > 0 && (
          <div className="bg-orange-500/5 border border-orange-500/20 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-2">
              <Server size={14} className="text-orange-400" />
              <span className="text-orange-300 text-xs font-medium">{t('rpt_high_mem_hosts')}</span>
              <span className="text-orange-500 text-xs">({risks.high_memory_hosts.length})</span>
            </div>
            {risks.high_memory_hosts.map((h: any) => (
              <div key={h.host} className="flex justify-between text-xs py-1 border-b border-orange-500/10 last:border-0">
                <span className="text-slate-300">{h.host}</span>
                <span className="text-orange-400 font-medium">%{h.mem_pct} · {t('rpt_gb_free', { n: h.free_gb })}</span>
              </div>
            ))}
          </div>
        )}
        {risks.high_storage_hosts?.length > 0 && (
          <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-2">
              <HardDrive size={14} className="text-amber-400" />
              <span className="text-amber-300 text-xs font-medium">{t('rpt_high_disk_hosts')}</span>
            </div>
            {risks.high_storage_hosts.map((h: any) => (
              <div key={h.host} className="flex justify-between text-xs py-1 border-b border-amber-500/10 last:border-0">
                <span className="text-slate-300">{h.host}</span>
                <span className="text-amber-400 font-medium">%{h.ds_pct}</span>
              </div>
            ))}
          </div>
        )}
        {risks.no_tools_vms?.length > 0 && (
          <div className="bg-slate-700/20 border border-slate-600/30 rounded-xl p-3">
            <div className="flex items-center gap-2 mb-2">
              <Zap size={14} className="text-slate-400" />
              <span className="text-slate-300 text-xs font-medium">{t('rpt_tools_missing')}</span>
              <span className="text-slate-500 text-xs">({risks.no_tools_vms.length})</span>
            </div>
            {risks.no_tools_vms.slice(0, 6).map((v: any) => (
              <div key={v.vm} className="flex justify-between text-xs py-0.5">
                <span className="text-slate-400">{v.vm}</span>
                <span className="text-slate-500">{v.os || '-'}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* Top alarm servers */}
      {risks.top_alarm_servers?.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_top_alarm')} icon={<AlertTriangle size={14} />} />
          <div className="space-y-2">
            {risks.top_alarm_servers.map((s: any, i: number) => (
              <HorzBar key={i} value={s.events} max={Math.max(...risks.top_alarm_servers.map((x: any) => x.events))} label={s.server} color="red" />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Linux/Windows `risky_servers` ve Exadata `unhealthy_racks` — VM/tools/ESX
// kavramı olmayan platformlar için `RiskView` (virt) yerine bare-metal
// sunucu/rack bazlı basit bir risk listesi.
function ServerRiskView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const risky: any[] = d.risky_servers || []
  const racks: any[] = d.unhealthy_racks || []
  const isRackBased = !d.risky_servers && !!d.unhealthy_racks
  const maxEvt = Math.max(...risky.map((r) => r.event_count ?? r.events ?? 0), 1)

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={isRackBased ? 'Sorunlu Rack' : 'Riskli Sunucu'}
          value={isRackBased ? racks.length : risky.length}
          color={(isRackBased ? racks.length : risky.length) > 0 ? 'red' : 'green'}
          icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_events_48h')} value={d.total_active_events ?? d.active_events ?? 0} color="slate" icon={<Activity size={12} />} />
        <KpiCard label={t('rpt_crit_servers')} value={risky.filter((r) => (r.critical_count ?? 0) > 0).length}
          color="red" />
      </div>
      {!isRackBased && risky.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_riskiest_servers_48h')} icon={<AlertTriangle size={14} />} count={risky.length} />
          <div className="space-y-2 mt-2">
            {risky.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_auto] items-center gap-3">
                <HorzBar value={r.event_count ?? r.events ?? 0} max={maxEvt} label={r.server} color={(r.critical_count ?? 0) > 0 ? 'red' : 'amber'} />
                <span className="text-[10px] text-slate-500 whitespace-nowrap truncate max-w-[220px]" title={r.top_title || ''}>
                  {(r.critical_count ?? 0) > 0 ? `${r.critical_count} kritik · ` : ''}{r.top_title || ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {isRackBased && (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <SectionHeader title={t('rpt_bad_racks')} icon={<AlertTriangle size={14} />} count={racks.length} />
          {racks.length > 0 ? (
            <div className="px-4 pb-4 space-y-2">
              {racks.map((r, i) => (
                <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-slate-700/20 last:border-0">
                  <span className="text-slate-200 font-medium">{r.rack}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500">{r.datacenter || '—'}</span>
                    <SeverityBadge level={r.health} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="px-4 pb-4 text-sm text-slate-500 flex items-center gap-2">
              <CheckCircle2 size={14} className="text-green-400" /> {t('rpt_racks_ok')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function VmHealthView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const gdist = d.grade_distribution || {}
  const gradeColors: Record<string, { bg: string; text: string }> = {
    A: { bg: 'bg-green-500/20 border-green-500/40', text: 'text-green-400' },
    B: { bg: 'bg-blue-500/20 border-blue-500/40', text: 'text-blue-400' },
    C: { bg: 'bg-amber-500/20 border-amber-500/40', text: 'text-amber-400' },
    D: { bg: 'bg-orange-500/20 border-orange-500/40', text: 'text-orange-400' },
    F: { bg: 'bg-red-500/20 border-red-500/40', text: 'text-red-400' },
  }
  const allVms: any[] = d.vm_scores || []
  const [tab, setTab] = useState<string>('critical')
  return (
    <div className="space-y-5">
      {/* Score + grade dist */}
      <div className="flex gap-4 items-center">
        <div className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/30 flex flex-col items-center">
          <ScoreGauge score={d.avg_score ?? 0} max={100} label={t('rpt_avg_health')} size={96} />
          <p className="text-slate-500 text-xs mt-1">{d.total_vms ?? 0} VM</p>
        </div>
        <div className="flex-1 grid grid-cols-5 gap-2">
          {['A', 'B', 'C', 'D', 'F'].map(g => {
            const gc = gradeColors[g]
            return (
              <div key={g} className={`rounded-xl border p-3 text-center ${gc.bg} cursor-pointer`} onClick={() => setTab(g)}>
                <div className={`text-3xl font-bold ${gc.text}`}>{gdist[g] ?? 0}</div>
                <div className="text-slate-500 text-xs mt-1">{t('rpt_grade', { g })}</div>
              </div>
            )
          })}
        </div>
      </div>
      {/* VM list tabs */}
      <div>
        <div className="flex gap-1 mb-3">
          {(['critical', 'A', 'B', 'C', 'D', 'F'] as const).map(gradeTab => (
            <button key={gradeTab} onClick={() => setTab(gradeTab)}
              className={`text-xs px-3 py-1 rounded-lg transition-all ${tab === gradeTab ? 'bg-blue-600/30 text-blue-300 border border-blue-500/40' : 'bg-slate-800/40 text-slate-500 hover:text-white border border-slate-700/30'}`}>
              {gradeTab === 'critical' ? <span className="inline-flex items-center gap-1"><AlertTriangle size={11} strokeWidth={2} /> {t('rpt_sev_critical')}</span> : t('rpt_grade', { g: gradeTab })}
            </button>
          ))}
        </div>
        <div className="space-y-1.5">
          {(tab === 'critical' ? d.critical_vms || [] : allVms.filter((v: any) => v.grade === tab))
            .slice(0, 20).map((v: any) => {
              const gc = gradeColors[v.grade]
              return (
                <div key={v.vm} className="flex items-center gap-3 bg-slate-800/40 rounded-lg px-3 py-2 text-xs border border-slate-700/20">
                  <span className={`font-bold text-base w-6 text-center ${gc.text}`}>{v.grade}</span>
                  <div className="flex-1 min-w-0">
                    <span className="text-white">{v.vm}</span>
                    <span className="text-slate-500 ml-2">{v.hypervisor}</span>
                  </div>
                  <div className="w-20">
                    <ProgressBar pct={v.score} label="" showPct={false} sub={`${v.score}/100`} />
                  </div>
                  <span className="text-slate-500 truncate max-w-xs">{(v.issues || []).join(' · ')}</span>
                </div>
              )
            })}
        </div>
      </div>
    </div>
  )
}

function ResourceUsageView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const s = d.summary || {}
  const maxCpu = Math.max(...(d.top_cpu_consumers || []).map((v: any) => v.vcpu || 0), 1)
  const maxRam = Math.max(...(d.top_ram_consumers || []).map((v: any) => v.ram_gb || 0), 1)
  const maxDisk = Math.max(...(d.top_disk_consumers || []).map((v: any) => v.disk_gb || 0), 1)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label={t('rpt_running_vm')} value={s.powered_on_vms ?? 0} color="green" icon={<Zap size={12} />} />
        <KpiCard label={t('rpt_alloc_cpu')} value={`${s.total_allocated_vcpu ?? 0} vCPU`} color="blue" icon={<Cpu size={12} />} />
        <KpiCard label={t('rpt_alloc_mem')} value={`${s.total_allocated_ram_gb ?? 0} GB`} color="purple" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_alloc_disk')} value={`${s.total_allocated_disk_gb ?? 0} GB`} color="amber" icon={<HardDrive size={12} />} />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_top_cpu_short')} icon={<Cpu size={14} />} />
          <div className="space-y-2">
            {(d.top_cpu_consumers || []).map((v: any, i: number) => (
              <HorzBar key={i} value={v.vcpu} max={maxCpu} label={v.vm} color="blue" />
            ))}
          </div>
        </div>
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_top_mem_short')} icon={<Server size={14} />} />
          <div className="space-y-2">
            {(d.top_ram_consumers || []).map((v: any, i: number) => (
              <HorzBar key={i} value={v.ram_gb} max={maxRam} label={v.vm} color="purple" />
            ))}
          </div>
        </div>
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_top_disk_short')} icon={<HardDrive size={14} />} />
          <div className="space-y-2">
            {(d.top_disk_consumers || []).map((v: any, i: number) => (
              <HorzBar key={i} value={v.disk_gb} max={maxDisk} label={v.vm} color="amber" />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function SecurityView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const comp = d.vmware_tools || {}
  const hw = d.hw_version_distribution || {}
  const score = d.compliance_score ?? 0
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          <ScoreGauge score={score} max={100} label={t('rpt_compliance_score')} size={96} />
        </div>
        <KpiCard label={t('rpt_compliant_vm')} value={comp.compliant_count ?? 0} color="green" icon={<CheckCircle2 size={12} />} />
        <KpiCard label={t('rpt_tools_missing')} value={comp.non_compliant_count ?? 0}
          color={(comp.non_compliant_count ?? 0) > 0 ? 'red' : 'green'} icon={<XCircle size={12} />} />
        <KpiCard label={t('rpt_on_no_tools')} value={comp.powered_on_non_compliant ?? 0}
          color={(comp.powered_on_non_compliant ?? 0) > 0 ? 'red' : 'green'} />
      </div>
      {d.issues?.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-3 space-y-1.5">
          {d.issues.map((issue: string, i: number) => (
            <div key={i} className="flex items-start gap-2">
              <AlertTriangle size={13} className="text-red-400 flex-shrink-0 mt-0.5" />
              <span className="text-red-300 text-sm">{issue}</span>
            </div>
          ))}
        </div>
      )}
      {/* VMware Tools compliance bar */}
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <SectionHeader title={t('rpt_tools_comp')} icon={<Zap size={14} />} />
        <div className="flex items-center gap-4 mb-3">
          <div className="flex-1 h-4 bg-slate-700 rounded-full overflow-hidden flex">
            <div className="bg-green-500 h-full rounded-l-full" style={{ width: `${comp.compliance_pct ?? 0}%` }} />
            <div className="bg-red-500 h-full rounded-r-full flex-1" />
          </div>
          <span className="text-white font-bold text-sm">%{comp.compliance_pct ?? 0}</span>
        </div>
        {(comp.non_compliant_vms || []).length > 0 && (
          <div className="space-y-1 mt-2">
            <p className="text-slate-500 text-xs mb-2">{t('rpt_on_no_tools_list')}</p>
            {comp.non_compliant_vms.slice(0, 10).map((v: any) => (
              <div key={v.vm} className="flex justify-between text-xs">
                <span className="text-slate-300">{v.vm}</span>
                <span className="text-slate-500">{v.state}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* HW Version dist */}
      {Object.keys(hw).length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_hw_dist')} icon={<Layers size={14} />} />
          <div className="space-y-2">
            {Object.entries(hw).sort((a: any, b: any) => b[1] - a[1]).slice(0, 8).map(([k, v]: any) => (
              <HorzBar key={k} value={v} max={Math.max(...Object.values(hw) as number[])} label={k || 'Bilinmiyor'} color="teal" />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ConsolidationView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const poff = d.powered_off_vms || {}
  const pot = d.consolidation_potential || {}
  const over = d.oversized_vms || {}
  return (
    <div className="space-y-5">
      {/* Waste stats */}
      <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <PackageOpen size={16} className="text-amber-400" />
          <h3 className="text-amber-300 font-medium text-sm">{t('rpt_reclaim')}</h3>
        </div>
        <div className="grid grid-cols-4 gap-3">
          <div className="text-center">
            <div className="text-3xl font-bold text-amber-400">{poff.count ?? 0}</div>
            <div className="text-slate-500 text-xs mt-1">{t('rpt_off_vm')}</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-blue-400">{pot.reclaimable_vcpu ?? 0}</div>
            <div className="text-slate-500 text-xs mt-1">{t('rpt_reclaim_vcpu')}</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-sky-400">{pot.reclaimable_ram_gb ?? 0}</div>
            <div className="text-slate-500 text-xs mt-1">{t('rpt_reclaim_mem')}</div>
          </div>
          <div className="text-center">
            <div className="text-3xl font-bold text-emerald-400">{pot.reclaimable_disk_gb ?? 0}</div>
            <div className="text-slate-500 text-xs mt-1">{t('rpt_reclaim_disk')}</div>
          </div>
        </div>
      </div>
      {/* Powered off list */}
      {poff.vms?.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_powered_off')} count={poff.count} icon={<Server size={14} />} />
          <table className="w-full text-xs">
            <thead><tr className="border-b border-slate-700/40 text-slate-500">
              <th className="text-left pb-2">VM</th>
              <th className="text-right pb-2">vCPU</th>
              <th className="text-right pb-2">Memory (GB)</th>
              <th className="text-right pb-2">Disk (GB)</th>
            </tr></thead>
            <tbody>
              {poff.vms.slice(0, 15).map((v: any) => (
                <tr key={v.vm} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                  <td className="py-1.5 text-white">{v.vm}</td>
                  <td className="py-1.5 text-right text-slate-400">{v.cpu}</td>
                  <td className="py-1.5 text-right text-slate-400">{v.ram_gb}</td>
                  <td className="py-1.5 text-right text-slate-400">{v.disk_gb}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/* Oversized */}
      {over.vms?.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_over_vcpu')} count={over.count} icon={<Cpu size={14} />} />
          <div className="space-y-1.5">
            {over.vms.slice(0, 10).map((v: any) => (
              <div key={v.vm} className="flex items-center justify-between bg-slate-800/40 rounded-lg px-3 py-2 text-xs">
                <span className="text-white">{v.vm}</span>
                <div className="flex items-center gap-3">
                  <span className="text-blue-400">{v.cpu} vCPU</span>
                  <span className="text-slate-400">{v.ram_gb} GB Memory</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function LifecycleView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const hwDist = d.hw_version_distribution || {}
  const oldHw = d.old_hw_vms || {}
  const maxCount = Math.max(...(Object.values(hwDist) as number[]), 1)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_total_vm')} value={d.total_vms ?? 0} color="blue" />
        <KpiCard label={t('rpt_old_hw')} value={oldHw.count ?? 0}
          color={(oldHw.count ?? 0) > 0 ? 'amber' : 'green'}
          sub={t('rpt_threshold', { v: oldHw.threshold ?? 'vmx-14' })} />
        <KpiCard label={t('rpt_upgrade_rate')} value={`%${d.upgrade_needed_pct ?? 0}`}
          color={(d.upgrade_needed_pct ?? 0) > 20 ? 'red' : 'green'} />
      </div>
      {/* HW version chart */}
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <SectionHeader title={t('rpt_hw_dist')} icon={<Layers size={14} />} />
        <div className="space-y-2">
          {Object.entries(hwDist).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]: any) => {
            const isOld = k !== 'Bilinmiyor' && parseInt(k.replace(/[^0-9]/g, '') || '99') < 14
            return (
              <div key={k} className="flex items-center gap-2 text-xs">
                <span className={`w-24 text-right ${isOld ? 'text-amber-400' : 'text-slate-300'}`}>{k || 'Bilinmiyor'}</span>
                <div className="flex-1 h-2 bg-slate-700/50 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${isOld ? 'bg-amber-500' : 'bg-blue-500'}`}
                    style={{ width: `${(v / maxCount) * 100}%` }} />
                </div>
                <span className="text-slate-300 w-8 text-right">{v}</span>
                {isOld && <span className="inline-flex items-center gap-0.5 text-amber-500 text-[10px]"><AlertTriangle size={9} strokeWidth={2} /> eski</span>}
              </div>
            )
          })}
        </div>
      </div>
      {/* Old HW VMs */}
      {oldHw.vms?.length > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
          <SectionHeader title={t('rpt_need_upgrade')} count={oldHw.count} icon={<AlertTriangle size={14} />} />
          <div className="space-y-1">
            {oldHw.vms.slice(0, 20).map((v: any) => (
              <div key={v.vm} className="flex items-center justify-between text-xs py-1 border-b border-amber-500/10 last:border-0">
                <span className="text-slate-300">{v.vm}</span>
                <div className="flex items-center gap-2">
                  <span className="text-amber-400">{v.hw_version}</span>
                  <span className="text-slate-500">{v.era}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function AnomalyView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const topServers = d.top_anomaly_servers || []
  const topTypes = d.top_event_types || []
  const metricAnomalies = d.host_metric_anomalies || []
  const maxEvt = Math.max(...topServers.map((s: any) => s.total || 0), 1)
  const maxType = Math.max(...topTypes.map((t: any) => t.count || 0), 1)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label={t('rpt_period')} value={t('rpt_n_days', { n: d.period_days ?? 14 })} color="blue" icon={<Clock size={12} />} />
        <KpiCard label={t('rpt_total_events')} value={d.total_events ?? 0} color="slate" />
        <KpiCard label={t('rpt_crit_event')} value={d.critical_count ?? 0}
          color={(d.critical_count ?? 0) > 0 ? 'red' : 'green'} icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_virt_platform')} value={d.virt_platform_events ?? 0} color="purple" icon={<Layers size={12} />} />
      </div>
      {metricAnomalies.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_host_anom')} count={metricAnomalies.length} icon={<Activity size={14} />} />
          <div className="space-y-2">
            {metricAnomalies.slice(0, 8).map((h: any, i: number) => (
              <div key={i} className="flex items-start justify-between gap-3 text-xs bg-slate-800/50 rounded-lg p-2.5 border border-slate-700/30">
                <div>
                  <span className="text-white font-medium">{h.host}</span>
                  <div className="text-slate-400 mt-1">{h.issues?.join(' · ')}</div>
                </div>
                <SeverityBadge level={h.severity || 'Uyarı'} />
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        {topServers.length > 0 && (
          <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <SectionHeader title={t('rpt_top_anomaly')} icon={<Server size={14} />} />
            <div className="space-y-2">
              {topServers.slice(0, 10).map((s: any, i: number) => (
                <div key={i}>
                  <div className="flex justify-between text-xs mb-0.5">
                    <span className="text-slate-300 truncate">{s.server}</span>
                    <div className="flex gap-2 flex-shrink-0">
                      {s.critical > 0 && <span className="text-red-400">{t('rpt_n_crit', { n: s.critical })}</span>}
                      {s.warning > 0 && <span className="text-amber-400">{t('rpt_n_warn', { n: s.warning })}</span>}
                    </div>
                  </div>
                  <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden flex">
                    <div className="bg-red-500 h-full" style={{ width: `${(s.critical / maxEvt) * 100}%` }} />
                    <div className="bg-amber-500 h-full" style={{ width: `${(s.warning / maxEvt) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {topTypes.length > 0 && (
          <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <SectionHeader title={t('rpt_top_event_types')} icon={<Activity size={14} />} />
            <div className="space-y-2">
              {topTypes.map((t: any, i: number) => (
                <HorzBar key={i} value={t.count} max={maxType} label={t.type} color="pink" />
              ))}
            </div>
          </div>
        )}
      </div>
      {d.analysis_note && (
        <div className="flex items-start gap-2 text-xs text-slate-500 bg-slate-800/30 rounded-lg p-3">
          <Info size={12} className="flex-shrink-0 mt-0.5" />
          <span>{d.analysis_note}</span>
        </div>
      )}
    </div>
  )
}

function ForecastView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const forecasts = d.forecasts || []
  const colColor = (v: number) => v > 90 ? 'text-red-400 font-bold' : v > 80 ? 'text-amber-400' : v > 65 ? 'text-yellow-400' : 'text-green-400'
  return (
    <div className="space-y-5">
      {d.investment_needed && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 flex items-center gap-2">
          <AlertTriangle size={16} className="text-red-400" />
          <span className="text-red-300 text-sm font-medium">{t('rpt_cap_invest')}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        {forecasts.map((item: any) => (
          <div key={item.host} className="bg-slate-800/40 rounded-xl border border-slate-700/30 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700/40 flex items-center justify-between">
              <span className="text-white font-semibold">{item.host}</span>
              {(item.forecast_6m?.mem_pct > 85 || item.forecast_6m?.ds_pct > 85) && (
                <SeverityBadge level="Uyarı" />
              )}
            </div>
            <div className="p-4">
              <table className="w-full text-xs">
                <thead><tr className="text-slate-500">
                  <th className="text-left pb-2">{t('rpt_col_resource')}</th>
                  <th className="text-center pb-2">{t('rpt_now')}</th>
                  <th className="text-center pb-2">{t('rpt_3m')}</th>
                  <th className="text-center pb-2">{t('rpt_6m')}</th>
                  <th className="text-center pb-2">{t('rpt_12m')}</th>
                </tr></thead>
                <tbody>
                  {(['cpu', 'mem', 'ds'] as const).map(res => {
                    const labels: Record<string, string> = { cpu: 'CPU', mem: t('memory'), ds: 'Disk' }
                    const icons: Record<string, React.ReactNode> = { cpu: <Cpu size={10} />, mem: <Server size={10} />, ds: <HardDrive size={10} /> }
                    const curr = item.current?.[`${res}_pct`] ?? 0
                    const m3 = item.forecast_3m?.[`${res}_pct`] ?? 0
                    const m6 = item.forecast_6m?.[`${res}_pct`] ?? 0
                    const m12 = item.forecast_12m?.[`${res}_pct`] ?? 0
                    return (
                      <tr key={res} className="border-t border-slate-700/30">
                        <td className="py-2 flex items-center gap-1.5 text-slate-400">{icons[res]} {labels[res]}</td>
                        <td className={`py-2 text-center ${colColor(curr)}`}>%{curr}</td>
                        <td className={`py-2 text-center ${colColor(m3)}`}>%{m3}</td>
                        <td className={`py-2 text-center ${colColor(m6)}`}>%{m6}</td>
                        <td className={`py-2 text-center ${colColor(m12)}`}>%{m12}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {/* trend mini bar */}
              <div className="mt-3 space-y-1">
                {['mem', 'ds'].map(res => {
                  const curr = item.current?.[`${res}_pct`] ?? 0
                  const m12 = item.forecast_12m?.[`${res}_pct`] ?? 0
                  const label = res === 'mem' ? t('rpt_mem_12m') : t('rpt_disk_12m')
                  return <ProgressBar key={res} pct={m12} label={label} sub={t('rpt_now_pct', { n: curr })} />
                })}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FinanceView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const cur = d.currency || 'TL'
  const vms = d.top_cost_vms || []
  const maxCost = Math.max(...vms.map((v: any) => v.monthly_cost || 0), 1)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-5 flex flex-col items-center">
          <span className="text-slate-400 text-xs mb-2">{t('rpt_monthly_cost')}</span>
          <span className="text-4xl font-bold text-emerald-400">
            {(d.total_monthly_cost || 0).toLocaleString(dateLoc(locale))}
          </span>
          <span className="text-slate-400 text-sm mt-1">{cur}</span>
        </div>
        <div className="space-y-2">
          <KpiCard label={t('rpt_annual_cost')} value={`${(d.total_annual_cost || 0).toLocaleString(dateLoc(locale))} ${cur}`} color="emerald" />
          <KpiCard label={t('rpt_off_save')} value={t('rpt_per_month', { n: (d.powered_off_savings || 0).toLocaleString(dateLoc(locale)), cur })} color="amber" icon={<TrendingUp size={14} />} />
        </div>
      </div>
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <SectionHeader title={t('rpt_costliest_vms')} count={vms.length} icon={<DollarSign size={14} />} />
        <div className="space-y-2">
          {vms.slice(0, 12).map((v: any, i: number) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="text-slate-600 w-4 text-right">{i + 1}</span>
              <span className="text-slate-300 w-36 truncate">{v.vm}</span>
              <div className="flex-1 h-2 bg-slate-700/50 rounded-full overflow-hidden">
                <div className="bg-emerald-500 h-full rounded-full" style={{ width: `${(v.monthly_cost / maxCost) * 100}%` }} />
              </div>
              <span className="text-emerald-400 font-medium w-20 text-right">{v.monthly_cost?.toLocaleString(dateLoc(locale))} {cur}</span>
              <span className="text-slate-500 w-24 text-right">{v.vcpu}vCPU · {v.ram_gb}GB</span>
            </div>
          ))}
        </div>
      </div>
      {d.note && (
        <div className="flex items-start gap-2 text-xs text-slate-500">
          <Info size={12} className="flex-shrink-0 mt-0.5" />
          <span>{d.note}</span>
        </div>
      )}
    </div>
  )
}

function RiskiestAssetsView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const hosts = d.riskiest_hosts || []
  const vms = d.riskiest_vms || []
  const maxHostRisk = Math.max(...hosts.map((h: any) => h.risk_score || 0), 1)
  const maxVmRisk = Math.max(...vms.map((v: any) => v.risk_score || 0), 1)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <KpiCard label={t('rpt_risky_host')} value={d.total_risky_hosts ?? 0}
          color={(d.total_risky_hosts ?? 0) > 0 ? 'red' : 'green'} icon={<Server size={12} />} />
        <KpiCard label={t('rpt_risky_vm')} value={d.total_risky_vms ?? 0}
          color={(d.total_risky_vms ?? 0) > 0 ? 'amber' : 'green'} icon={<Zap size={12} />} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        {hosts.length > 0 && (
          <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4">
            <SectionHeader title={t('rpt_riskiest_hosts')} count={hosts.length} icon={<Server size={14} />} />
            <div className="space-y-3">
              {hosts.map((h: any, i: number) => (
                <div key={i}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-300">{h.host}</span>
                    <span className="text-red-400 font-bold">{h.risk_score}</span>
                  </div>
                  <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden mb-1">
                    <div className="bg-red-500 h-full rounded-full" style={{ width: `${(h.risk_score / maxHostRisk) * 100}%` }} />
                  </div>
                  <div className="text-slate-500 text-[10px]">{(h.reasons || []).join(' · ')}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {vms.length > 0 && (
          <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
            <SectionHeader title={t('rpt_riskiest_vms')} count={vms.length} icon={<Zap size={14} />} />
            <div className="space-y-3">
              {vms.slice(0, 10).map((v: any, i: number) => (
                <div key={i}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-300 truncate">{v.vm}</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {v.tier === 'production' && <span className="text-[9px] bg-red-900/40 text-red-400 px-1 rounded">PROD</span>}
                      <span className="text-amber-400 font-bold">{v.risk_score}</span>
                    </div>
                  </div>
                  <div className="h-2 bg-slate-700/50 rounded-full overflow-hidden mb-1">
                    <div className="bg-amber-500 h-full rounded-full" style={{ width: `${(v.risk_score / maxVmRisk) * 100}%` }} />
                  </div>
                  <div className="text-slate-500 text-[10px]">{(v.reasons || []).join(' · ')}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function OperationsView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const breakdown = d.event_breakdown || []
  const daily = d.daily_trend || []
  const virtPlatform = d.virt_platform || {}
  const virtLogs = virtPlatform.recent_logs || []
  const virtBreakdown = virtPlatform.breakdown || []
  const maxEvt = Math.max(...breakdown.map((e: any) => e.count || 0), 1)
  const maxDay = Math.max(...daily.map((e: any) => e.total || 0), 1)
  const sevColor: Record<string, string> = {
    critical: 'bg-red-500', error: 'bg-red-400',
    warning: 'bg-amber-500', info: 'bg-blue-500',
  }
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label={t('rpt_period_short')} value={t('rpt_n_days_cap', { n: d.period_days ?? 30 })} color="blue" icon={<Clock size={12} />} />
        <KpiCard label={t('rpt_total_events')} value={d.total_events ?? breakdown.reduce((a: number, b: any) => a + (b.count || 0), 0)} color="slate" />
        <KpiCard label={t('rpt_virt_platform')} value={virtPlatform.total_events ?? 0} color="purple" icon={<Layers size={12} />} />
        <KpiCard label={t('rpt_affected')} value={d.unique_servers ?? 0} color="slate" icon={<Server size={12} />} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        {/* Event type breakdown */}
        {breakdown.length > 0 && (
          <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <SectionHeader title={t('rpt_event_dist')} icon={<Activity size={14} />} />
            <div className="space-y-2">
              {breakdown.slice(0, 12).map((e: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${sevColor[e.severity] || 'bg-slate-500'}`} />
                  <span className="text-slate-300 flex-1 truncate">{e.type}</span>
                  <div className="w-20 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${sevColor[e.severity] || 'bg-slate-500'}`}
                      style={{ width: `${(e.count / maxEvt) * 100}%` }} />
                  </div>
                  <span className="text-slate-400 w-8 text-right">{e.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* Daily trend */}
        {daily.length > 0 && (
          <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
            <SectionHeader title={t('rpt_daily_trend')} icon={<TrendingUp size={14} />} />
            <div className="space-y-1.5">
              {daily.slice(0, 10).map((day: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="text-slate-500 w-20 flex-shrink-0">{day.day?.slice(5)}</span>
                  <div className="flex-1 h-2 bg-slate-700/50 rounded-full overflow-hidden flex">
                    <div className="bg-red-500 h-full" style={{ width: `${(day.critical / maxDay) * 100}%` }} />
                    <div className="bg-blue-500/60 h-full" style={{ width: `${((day.total - day.critical) / maxDay) * 100}%` }} />
                  </div>
                  <span className="text-slate-300 w-8 text-right">{day.total}</span>
                  {day.critical > 0 && <span className="text-red-400 w-12 text-right">{t('rpt_n_crit', { n: day.critical })}</span>}
                </div>
              ))}
            </div>
            <div className="flex gap-3 mt-2 text-[10px]">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />{t('rpt_sev_critical')}</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500/60" />{t('rpt_other')}</span>
            </div>
          </div>
        )}
      </div>
      {(virtBreakdown.length > 0 || virtLogs.length > 0) && (
        <div className="grid grid-cols-2 gap-4">
          {virtBreakdown.length > 0 && (
            <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
              <SectionHeader title={t('rpt_virt_events')} icon={<Layers size={14} />} />
              <div className="space-y-2">
                {virtBreakdown.slice(0, 10).map((e: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 truncate">{e.type}</span>
                    <span className="text-slate-400">{e.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {virtLogs.length > 0 && (
            <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
              <SectionHeader title={t('rpt_plat_logs')} icon={<Activity size={14} />} />
              <div className="space-y-2 max-h-56 overflow-y-auto">
                {virtLogs.slice(0, 12).map((log: any, i: number) => (
                  <div key={i} className="text-xs border-b border-slate-700/30 pb-2">
                    <div className="text-slate-200 truncate">{log.title}</div>
                    <div className="text-slate-500 mt-0.5">
                      {log.host || '-'} · {log.action || log.severity}
                      {log.created_at ? ` · ${new Date(log.created_at).toLocaleDateString('tr-TR')}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {d.note && (
        <div className="flex items-start gap-2 text-xs text-slate-500 bg-slate-800/30 rounded-lg p-3">
          <Info size={12} className="flex-shrink-0 mt-0.5" />
          <span>{d.note}</span>
        </div>
      )}
    </div>
  )
}

function BottleneckView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const bottlenecks = d.bottlenecks || []
  const critCount = d.critical_count ?? 0
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_total_host')} value={bottlenecks.length} color="blue" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_crit_bn')} value={critCount} color={critCount > 0 ? 'red' : 'green'} icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_warn_status')} value={bottlenecks.filter((b: any) => b.severity === 'Uyarı').length}
          color="amber" />
      </div>
      <div className="space-y-3">
        {bottlenecks.map((b: any) => (
          <div key={b.host} className={`rounded-xl border p-4 ${
            b.severity === 'Kritik' ? 'bg-red-500/5 border-red-500/20' :
            b.severity === 'Uyarı' ? 'bg-amber-500/5 border-amber-500/20' :
            'bg-slate-800/30 border-slate-700/30'
          }`}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-white font-semibold">{b.host}</span>
              <SeverityBadge level={b.severity ?? 'Normal'} />
            </div>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div className="space-y-2">
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">{t('rpt_cpu_now_peak')}</span>
                    <span className={b.current_cpu > 80 ? 'text-red-400 font-bold' : 'text-slate-300'}>
                      {b.current_cpu}% / {b.peak_cpu_24h ?? '-'}%
                    </span>
                  </div>
                  <ProgressBar pct={b.current_cpu} label="" showPct={false} />
                </div>
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">{t('rpt_mem_now_peak')}</span>
                    <span className={b.current_mem > 85 ? 'text-red-400 font-bold' : 'text-slate-300'}>
                      {b.current_mem}% / {b.peak_mem_24h ?? '-'}%
                    </span>
                  </div>
                  <ProgressBar pct={b.current_mem} label="" showPct={false} />
                </div>
              </div>
              <div className="space-y-2">
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">{t('rpt_disk_use')}</span>
                    <span className={b.current_ds > 80 ? 'text-amber-400 font-bold' : 'text-slate-300'}>{b.current_ds}%</span>
                  </div>
                  <ProgressBar pct={b.current_ds} label="" showPct={false} />
                </div>
                {b.peak_net_mbps != null && (
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">{t('rpt_net_peak')}</span>
                    <span className="text-slate-300">{b.peak_net_mbps} Mbps</span>
                  </div>
                )}
              </div>
            </div>
            {b.issues?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {b.issues.map((issue: string, i: number) => (
                  <span key={i} className="text-[10px] bg-red-900/30 text-red-400 px-2 py-0.5 rounded-full border border-red-500/20">{issue}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SlaView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const items = d.sla_items || []
  const met = d.servers_meeting_sla ?? 0
  const missing = d.servers_missing_sla ?? 0
  const compliance = d.overall_sla_compliance_pct ?? 100
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          <ScoreGauge score={Math.round(compliance)} max={100} label={t('rpt_sla_compliance')} size={96} />
        </div>
        <KpiCard label={t('rpt_sla_target')} value={`%${d.sla_target_pct ?? 99}`} color="blue" />
        <KpiCard label={t('rpt_sla_met')} value={met} color="green" icon={<CheckCircle2 size={12} />} />
        <KpiCard label={t('rpt_sla_missing')} value={missing} color={missing > 0 ? 'red' : 'green'} icon={<XCircle size={12} />} />
      </div>
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <SectionHeader title={t('rpt_sla_servers')} count={items.length} icon={<Server size={14} />} />
        <div className="space-y-1.5">
          {items.slice(0, 20).map((s: any) => (
            <div key={s.server} className="flex items-center gap-3 text-xs bg-slate-800/40 rounded-lg px-3 py-2">
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${s.sla_met ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-white flex-1">{s.server}</span>
              <div className="w-24">
                <ProgressBar pct={s.estimated_uptime_pct} label="" showPct={false} />
              </div>
              <span className={`w-16 text-right font-medium ${s.sla_met ? 'text-green-400' : 'text-red-400'}`}>
                %{s.estimated_uptime_pct}
              </span>
              {s.critical_events_30d > 0 && (
                <span className="text-red-400 w-16 text-right">{t('rpt_n_crit', { n: s.critical_events_30d })}</span>
              )}
            </div>
          ))}
        </div>
      </div>
      {d.note && (
        <div className="flex items-start gap-2 text-xs text-slate-500 bg-slate-800/30 rounded-lg p-3">
          <Info size={12} className="flex-shrink-0 mt-0.5" />
          <span>{d.note}</span>
        </div>
      )}
    </div>
  )
}

function BusinessImpactView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const services = d.services || []
  const highRisk = d.high_risk_candidates || []
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <KpiCard label={t('rpt_mapped_svc')} value={d.mapped_services ?? 0}
          color={(d.mapped_services ?? 0) > 0 ? 'blue' : 'amber'} icon={<Building2 size={12} />} />
        <KpiCard label={t('rpt_high_risk_n')} value={highRisk.length} color={highRisk.length > 0 ? 'red' : 'green'} />
      </div>
      {d.message && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4 flex items-start gap-3">
          <Info size={16} className="text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-amber-300 text-sm font-medium">{t('rpt_no_svc_map')}</p>
            <p className="text-slate-400 text-xs mt-1">{d.message}</p>
            {d.setup_instructions && <p className="text-blue-400 text-xs mt-2">{d.setup_instructions}</p>}
          </div>
        </div>
      )}
      {services.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_svc_map')} count={services.length} icon={<Network size={14} />} />
          <div className="space-y-3">
            {services.map((svc: any) => (
              <div key={svc.service} className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/20">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white font-medium text-sm">{svc.service}</span>
                  <span className="text-slate-400 text-xs">{svc.vm_count} VM</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(svc.vms || []).map((v: any, i: number) => (
                    <span key={i} className="text-xs bg-blue-900/30 text-blue-300 px-2 py-0.5 rounded border border-blue-700/30">
                      {v.vm}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {highRisk.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4">
          <SectionHeader title={t('rpt_high_risk_prod')} count={highRisk.length} icon={<AlertTriangle size={14} />} />
          <div className="flex flex-wrap gap-2">
            {highRisk.map((v: any, i: number) => (
              <div key={i} className="bg-red-900/20 text-red-300 border border-red-700/30 rounded-lg px-3 py-1.5 text-xs">
                {v.vm}
                <span className="text-red-500 ml-1">({v.reason})</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function PatchStatusView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const rows: any[] = d.servers || []
  const hasDetailedData = d.checked_servers !== undefined
  const hasDefenderData = rows.some(r => r.defender_enabled !== undefined && r.defender_enabled !== null)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label={t('rpt_total_servers')} value={d.total_servers ?? rows.length} color="slate" icon={<Server size={12} />} />
        {hasDetailedData ? (
          <>
            <KpiCard label={t('rpt_pending_pkg')} value={d.pending_updates_total ?? 0}
              color={(d.pending_updates_total ?? 0) > 0 ? 'amber' : 'green'} icon={<PackageOpen size={12} />} />
            <KpiCard label={t('reboot_needed')} value={d.reboot_required_count ?? 0}
              color={(d.reboot_required_count ?? 0) > 0 ? 'red' : 'green'} icon={<RefreshCw size={12} />} />
            <KpiCard label={t('rpt_never_checked')} value={d.never_checked_servers ?? 0}
              color={(d.never_checked_servers ?? 0) > 0 ? 'amber' : 'green'} icon={<Clock size={12} />} />
          </>
        ) : (
          <KpiCard label={t('rpt_note')} value="—" sub={d.note} color="slate" />
        )}
      </div>

      {d.note && (
        <div className="flex items-start gap-2 bg-slate-800/30 border border-slate-700/30 rounded-xl px-4 py-3 text-xs text-slate-400">
          <Info size={14} className="text-slate-500 flex-shrink-0 mt-0.5" />
          <span>{d.note}</span>
        </div>
      )}

      {rows.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <SectionHeader title={t('rpt_server_patch')} count={rows.length} icon={<PackageOpen size={14} />} />
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/40">
                  <th className="text-left font-medium py-2 pr-3">{t('col_server')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('rpt_os_kernel')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('col_status')}</th>
                  {hasDetailedData && <th className="text-right font-medium py-2 pr-3">{t('rpt_pending_pkg')}</th>}
                  {hasDetailedData && <th className="text-left font-medium py-2 pr-3">{t('rpt_last_check')}</th>}
                  {hasDetailedData && <th className="text-left font-medium py-2 pr-3">{t('rpt_reboot')}</th>}
                  {hasDefenderData && <th className="text-left font-medium py-2">Defender</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-2 pr-3 text-slate-200 font-medium whitespace-nowrap">{r.server}</td>
                    <td className="py-2 pr-3 text-slate-400 whitespace-nowrap">
                      {r.os_version || r.os_type || '—'}{r.kernel ? ` · ${r.kernel}` : ''}
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                        (r.status || '').toUpperCase() === 'ONLINE'
                          ? 'bg-green-500/10 text-green-400 border-green-500/20'
                          : 'bg-slate-700/30 text-slate-400 border-slate-600/30'
                      }`}>{r.status || '—'}</span>
                    </td>
                    {hasDetailedData && (
                      <td className="py-2 pr-3 text-right">
                        {r.pending_updates === null || r.pending_updates === undefined ? (
                          <span className="text-slate-600">{t('rpt_not_checked')}</span>
                        ) : (
                          <span className={r.pending_updates > 0 ? 'text-amber-400 font-medium' : 'text-green-400'}>
                            {r.pending_updates}
                          </span>
                        )}
                      </td>
                    )}
                    {hasDetailedData && (
                      <td className="py-2 pr-3 text-slate-400 whitespace-nowrap">
                        {r.last_checked ? new Date(r.last_checked).toLocaleString(dateLoc(locale)) : '—'}
                      </td>
                    )}
                    {hasDetailedData && (
                      <td className="py-2 pr-3">
                        {r.reboot_required
                          ? <span className="text-red-400 text-[11px]">{t('rpt_needed')}</span>
                          : <span className="text-slate-600 text-[11px]">—</span>}
                      </td>
                    )}
                    {hasDefenderData && (
                      <td className="py-2">
                        {r.defender_enabled === null || r.defender_enabled === undefined ? (
                          <span className="text-slate-600 text-[11px]">—</span>
                        ) : r.defender_enabled ? (
                          <span className="text-green-400 text-[11px]">{t('active_label')}</span>
                        ) : (
                          <span className="text-red-400 text-[11px]">{t('inactive_label')}</span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function PerformanceView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const anomalies: any[] = d.anomalies || []
  const sevColor: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400 border-red-500/20',
    warning: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  }
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_anomaly_24h')} value={d.anomaly_count ?? anomalies.length}
          color={(d.anomaly_count ?? 0) > 0 ? 'amber' : 'green'} icon={<Zap size={12} />} />
      </div>
      {anomalies.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center text-slate-500 text-sm">
          <CheckCircle2 size={28} className="mb-2 text-green-500/60" />
          {t('rpt_no_anomaly_24h')}
        </div>
      ) : (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4">
          <SectionHeader title={t('rpt_metric_anomalies')} count={anomalies.length} icon={<Zap size={14} />} />
          <div className="space-y-2">
            {anomalies.map((a: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-slate-800/60 last:border-0">
                <span className="text-slate-300 w-32 truncate">{a.server}</span>
                <span className="text-slate-400 flex-1">{a.metric}</span>
                <span className="text-slate-400 w-16 text-right">{a.value ?? '—'}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ml-2 ${sevColor[a.severity] || 'bg-slate-700/30 text-slate-400 border-slate-600/30'}`}>
                  {a.severity}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function NodeHealthView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const nodes: any[] = d.nodes || []
  const healthy = nodes.filter(n => (n.status || '').toLowerCase() === 'online' || (n.status || '').toLowerCase() === 'healthy').length
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_total_node')} value={nodes.length} color="slate" icon={<Layers size={12} />} />
        <KpiCard label={t('rpt_healthy')} value={healthy} color="green" icon={<CheckCircle2 size={12} />} />
        <KpiCard label={t('dash_problematic')} value={nodes.length - healthy} color={(nodes.length - healthy) > 0 ? 'red' : 'green'} icon={<AlertTriangle size={12} />} />
      </div>
      <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4">
        <SectionHeader title={t('rpt_node_status')} count={nodes.length} icon={<Layers size={14} />} />
        <div className="grid grid-cols-2 gap-2">
          {nodes.map((n: any, i: number) => (
            <div key={i} className="flex items-center justify-between text-xs bg-slate-900/40 rounded-lg px-3 py-2">
              <span className="text-slate-300 truncate">{n.name}</span>
              <span className="text-slate-500 text-[10px]">{n.role}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                (n.status || '').toLowerCase() === 'online' || (n.status || '').toLowerCase() === 'healthy'
                  ? 'bg-green-500/10 text-green-400 border-green-500/20'
                  : 'bg-red-500/10 text-red-400 border-red-500/20'
              }`}>{n.status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SecurityAuditView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const samples: any[] = d.samples || []
  const linuxRows: any[] = d.servers || []
  const defenderGaps: any[] = d.defender_gaps || []
  const isLinuxAudit = d.platform === 'linux' || linuxRows.length > 0 || d.checked_servers !== undefined
  const sevColor: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400 border-red-500/20',
    warning: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    info: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  }

  if (isLinuxAudit) {
    return (
      <div className="space-y-5">
        <div className="grid grid-cols-4 gap-3">
          <KpiCard label={t('rpt_total_servers')} value={d.total_servers ?? linuxRows.length} color="slate" icon={<Server size={12} />} />
          <KpiCard label={t('rpt_fw_off')} value={d.firewall_inactive_count ?? 0}
            color={(d.firewall_inactive_count ?? 0) > 0 ? 'red' : 'green'} icon={<Shield size={12} />} />
          <KpiCard label={t('rpt_selinux_off')} value={d.selinux_disabled_count ?? 0}
            color={(d.selinux_disabled_count ?? 0) > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
          <KpiCard label={t('rpt_high_fail_login')} value={d.high_failed_login_count ?? 0}
            color={(d.high_failed_login_count ?? 0) > 0 ? 'red' : 'green'} icon={<AlertTriangle size={12} />} />
        </div>
        {d.note && (
          <div className="flex items-start gap-2 bg-slate-800/30 border border-slate-700/30 rounded-xl px-4 py-3 text-xs text-slate-400">
            <Info size={14} className="text-slate-500 flex-shrink-0 mt-0.5" />
            <span>{d.note}</span>
          </div>
        )}
        {linuxRows.length > 0 && (
          <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
            <SectionHeader title={t('rpt_server_sec')} count={linuxRows.length} icon={<Shield size={14} />} />
            <div className="overflow-x-auto px-4 pb-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/40">
                    <th className="text-left font-medium py-2 pr-3">{t('col_server')}</th>
                    <th className="text-left font-medium py-2 pr-3">Firewall</th>
                    <th className="text-left font-medium py-2 pr-3">SELinux</th>
                    <th className="text-right font-medium py-2 pr-3">{t('rpt_fail_login_24h')}</th>
                    <th className="text-left font-medium py-2">{t('rpt_last_check')}</th>
                  </tr>
                </thead>
                <tbody>
                  {linuxRows.map((r: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/60 last:border-0">
                      <td className="py-2 pr-3 text-slate-200 font-medium whitespace-nowrap">{r.server}</td>
                      <td className="py-2 pr-3">
                        {r.firewall_active === null || r.firewall_active === undefined ? (
                          <span className="text-slate-600">—</span>
                        ) : r.firewall_active ? (
                          <span className="text-green-400">{t('active_label')}</span>
                        ) : (
                          <span className="text-red-400 font-medium">{t('inactive_label')}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-slate-400">{r.selinux_status}</td>
                      <td className="py-2 pr-3 text-right">
                        <span className={(r.failed_logins_24h ?? 0) >= 5 ? 'text-red-400 font-medium' : 'text-slate-400'}>
                          {r.failed_logins_24h ?? 0}
                        </span>
                      </td>
                      <td className="py-2 text-slate-500 whitespace-nowrap">
                        {r.last_checked ? new Date(r.last_checked).toLocaleString(dateLoc(locale)) : t('rpt_not_checked')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label={t('rpt_period_short')} value={t('rpt_n_days_cap', { n: d.period_days ?? 7 })} color="blue" icon={<Clock size={12} />} />
        <KpiCard label={t('rpt_sec_event')} value={d.security_event_count ?? 0}
          color={(d.security_event_count ?? 0) > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
        {d.defender_checked_servers !== undefined && (
          <>
            <KpiCard label={t('rpt_defender_off')} value={d.defender_disabled_count ?? 0}
              color={(d.defender_disabled_count ?? 0) > 0 ? 'red' : 'green'} icon={<Shield size={12} />} />
            <KpiCard label={t('rpt_sig_stale')} value={d.defender_outdated_count ?? 0}
              color={(d.defender_outdated_count ?? 0) > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
          </>
        )}
      </div>
      {defenderGaps.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4">
          <SectionHeader title={t('rpt_win_defender_gaps')} count={defenderGaps.length} icon={<Shield size={14} />} />
          <div className="space-y-1.5">
            {defenderGaps.map((g: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-slate-800/60 last:border-0">
                <span className="text-slate-300 flex-1 truncate">{g.server}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ml-2 ${g.defender_enabled ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                  {g.defender_enabled ? t('rpt_sig_not_current') : t('rpt_defender_disabled')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {samples.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center text-slate-500 text-sm">
          <CheckCircle2 size={28} className="mb-2 text-green-500/60" />
          {t('rpt_no_sec_events')}
        </div>
      ) : (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 p-4">
          <SectionHeader title={t('rpt_sec_events')} count={samples.length} icon={<AlertTriangle size={14} />} />
          <div className="space-y-1.5">
            {samples.map((s: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-slate-800/60 last:border-0">
                <span className="text-slate-300 flex-1 truncate">{s.title}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ml-2 ${sevColor[s.severity] || 'bg-slate-700/30 text-slate-400 border-slate-600/30'}`}>
                  {s.severity}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MonitoringCoverageView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const gaps: any[] = d.gaps || []
  const fullyCovered: any[] = d.fully_covered || []
  const [showCovered, setShowCovered] = useState(false)
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-5 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          <ScoreGauge score={Math.round(d.coverage_pct ?? 0)} max={100} label={t('rpt_mon_cov')} size={96} />
        </div>
        <KpiCard label={t('rpt_total_servers')} value={d.total_servers ?? 0} color="slate" icon={<Server size={12} />} />
        <KpiCard label={t('ai_ready')} value={d.ai_ready_count ?? 0} color="blue" icon={<Zap size={12} />} />
        <KpiCard label={t('rpt_full_cov')} value={d.fully_covered_count ?? fullyCovered.length} sub={t('rpt_full_cov_sub')}
          color="green" icon={<CheckCircle2 size={12} />} />
        <KpiCard label={t('rpt_uncovered')} value={gaps.length}
          color={gaps.length > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
      </div>
      {d.note && (
        <div className="flex items-start gap-2 bg-slate-800/30 border border-slate-700/30 rounded-xl px-4 py-3 text-xs text-slate-400">
          <Info size={14} className="text-slate-500 flex-shrink-0 mt-0.5" />
          <span>{d.note}</span>
        </div>
      )}
      {gaps.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center text-slate-500 text-sm">
          <CheckCircle2 size={28} className="mb-2 text-green-500/60" />
          {t('rpt_all_covered')}
        </div>
      ) : (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <SectionHeader title={t('rpt_uncovered_servers')} count={gaps.length} icon={<Radar size={14} />} />
          <div className="overflow-x-auto px-4 pb-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700/40">
                  <th className="text-left font-medium py-2 pr-3">{t('col_server')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('col_status')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('ai_ready')}</th>
                  <th className="text-left font-medium py-2 pr-3">{t('rpt_exp_installed')}</th>
                  <th className="text-left font-medium py-2">{t('rpt_exp_running')}</th>
                </tr>
              </thead>
              <tbody>
                {gaps.map((r: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-2 pr-3 text-slate-200 font-medium whitespace-nowrap">{r.server}</td>
                    <td className="py-2 pr-3">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                        (r.status || '').toUpperCase() === 'ONLINE'
                          ? 'bg-green-500/10 text-green-400 border-green-500/20'
                          : 'bg-slate-700/30 text-slate-400 border-slate-600/30'
                      }`}>{r.status || '—'}</span>
                    </td>
                    <td className="py-2 pr-3">{r.ai_ready ? <span className="text-green-400">{t('yes')}</span> : <span className="text-red-400">{t('no')}</span>}</td>
                    <td className="py-2 pr-3">{r.exporter_installed ? <span className="text-green-400">{t('yes')}</span> : <span className="text-slate-500">{t('no')}</span>}</td>
                    <td className="py-2">{r.exporter_running ? <span className="text-green-400">{t('yes')}</span> : <span className="text-red-400">{t('no')}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {fullyCovered.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl border border-slate-700/30 overflow-hidden">
          <button
            onClick={() => setShowCovered(v => !v)}
            className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-800/50 transition-colors"
          >
            <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <CheckCircle2 size={14} className="text-green-400" />
              {t('rpt_full_cov_n', { n: fullyCovered.length })}
            </span>
            <ChevronRight size={16} className={`text-slate-500 transition-transform ${showCovered ? 'rotate-90' : ''}`} />
          </button>
          {showCovered && (
            <div className="px-4 pb-4 flex flex-wrap gap-1.5">
              {fullyCovered.map((s: any, i: number) => (
                <span key={i} className="text-[11px] bg-green-500/10 text-green-300 border border-green-500/20 px-2 py-1 rounded-lg">
                  {s.server}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function PlatformExecSummaryView({ d }: { d: any }) {
  const t = useT()
  const { locale } = useLocale()
  const inv = d.inventory || {}
  const health = d.health || {}
  const rl = d.risk_level || 'Normal'
  const riskScore = health.score ?? (rl === 'Kritik' ? 25 : rl === 'Yüksek' ? 58 : 88)
  const invEntries = Object.entries(inv).filter(([k]) => k !== 'total_servers' && k !== 'rack_count' && k !== 'node_count')
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3 items-start">
        <div className="flex flex-col items-center bg-slate-800/40 rounded-xl p-4 border border-slate-700/30">
          <ScoreGauge score={Math.round(riskScore)} max={100} label={t('rpt_health_score')} size={96} />
          <SeverityBadge level={rl === 'Normal' ? 'Normal' : rl} />
        </div>
        <KpiCard label={t('rpt_total_servers')} value={inv.total_servers ?? inv.rack_count ?? 0} color="blue" icon={<Server size={12} />} />
        <KpiCard label={t('rpt_online')} value={inv.online ?? 0} color="green" icon={<CheckCircle2 size={12} />} />
        <KpiCard label={t('offline_label')} value={inv.offline ?? Math.max(0, (inv.total_servers ?? 0) - (inv.online ?? 0))}
          color={(inv.offline ?? 0) > 0 ? 'red' : 'green'} icon={<XCircle size={12} />} />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label={t('rpt_crit_events')} value={health.critical_events ?? 0}
          color={(health.critical_events ?? 0) > 0 ? 'red' : 'green'} icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('rpt_warn_events')} value={health.warning_events ?? 0}
          color={(health.warning_events ?? 0) > 0 ? 'amber' : 'green'} icon={<AlertTriangle size={12} />} />
        <KpiCard label={t('ai_ready')} value={inv.ai_ready ?? '—'} color="cyan" icon={<Zap size={12} />} />
      </div>
      {invEntries.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <SectionHeader title={t('rpt_inv_detail')} icon={<Layers size={14} />} />
          <div className="grid grid-cols-3 gap-2 mt-2">
            {invEntries.map(([k, v]) => (
              <div key={k} className="bg-slate-900/40 rounded-lg px-3 py-2 flex items-center justify-between text-xs">
                <span className="text-slate-400">{k.replace(/_/g, ' ')}</span>
                <span className="text-white font-medium">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {(d.recommendations?.length ?? 0) > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4">
          <SectionHeader title={t('rpt_actions')} icon={<Target size={14} />} />
          <ul className="space-y-2 mt-2">
            {d.recommendations.map((rec: string, i: number) => (
              <li key={i} className="text-sm text-blue-100 flex items-start gap-2">
                <ChevronRight size={14} className="flex-shrink-0 mt-0.5 text-blue-400" />
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Ana rapor görsel router ────────────────────────────────────────────────────

function ReportSummaryView({ type, data }: { type: string; data: Record<string, unknown> }) {
  const t = useT()
  const d = data as any
  if (type.startsWith('custom:')) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center gap-2">
        <FileBarChart2 size={36} className="text-lime-500/70" />
        <p className="text-slate-300 text-sm">{t('rpt_custom_badge')}</p>
        <p className="text-slate-500 text-xs max-w-md">{t('rpt_custom_desc')}</p>
        <p className="text-slate-600 text-[11px] mt-2">{t('rpt_md')} →</p>
      </div>
    )
  }
  if (type === 'executive_summary') {
    // Linux/Windows/Exadata `inventory`/`health` şeması kullanır; virt (hypervisor)
    // raporu `infrastructure`/`utilization` şeması kullanır — veriye göre yönlendir.
    return d.inventory ? <PlatformExecSummaryView d={d} /> : <ExecSummaryView d={d} />
  }
  // Virt (hypervisor) `capacity` host/VM/datastore şeması kullanır;
  // linux/windows bare-metal sunucu (`top_servers`) ve exadata node envanteri
  // (`nodes`) farklı bir görsele ihtiyaç duyar — bkz. ServerCapacityView.
  if (type === 'capacity') return d.capacity_items ? <CapacityView d={d} /> : <ServerCapacityView d={d} />
  // Aynı şekilde `risk`: virt VM/ESX/tools bazlı; linux/windows sunucu
  // (`risky_servers`) ve exadata rack (`unhealthy_racks`) bazlı.
  if (type === 'risk') return d.risks ? <RiskView d={d} /> : <ServerRiskView d={d} />
  if (type === 'vm_health') return <VmHealthView d={d} />
  if (type === 'resource_usage') return <ResourceUsageView d={d} />
  if (type === 'security_compliance') return <SecurityView d={d} />
  if (type === 'consolidation') return <ConsolidationView d={d} />
  if (type === 'lifecycle') return <LifecycleView d={d} />
  if (type === 'anomaly') return <AnomalyView d={d} />
  if (type === 'forecast') return <ForecastView d={d} />
  if (type === 'finance') return <FinanceView d={d} />
  if (type === 'riskiest_assets') return <RiskiestAssetsView d={d} />
  if (type === 'operations') return <OperationsView d={d} />
  if (type === 'performance_bottleneck') return <BottleneckView d={d} />
  if (type === 'sla') return <SlaView d={d} />
  if (type === 'business_impact') return <BusinessImpactView d={d} />
  if (type === 'patch_status') return <PatchStatusView d={d} />
  if (type === 'performance') return <PerformanceView d={d} />
  if (type === 'node_health') return <NodeHealthView d={d} />
  if (type === 'security') return <SecurityAuditView d={d} />
  if (type === 'monitoring_coverage') return <MonitoringCoverageView d={d} />
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <BarChart3 size={40} className="text-slate-600 mb-3" />
      <p className="text-slate-400 text-sm">{t('rpt_visual_loading')}</p>
    </div>
  )
}

// ── Ana sayfa ─────────────────────────────────────────────────────────────────

export default function InfraReports({
  platform = 'virt',
  initialTab,
}: {
  platform?: PlatformKey
  initialTab?: 'reports' | 'chat' | 'compare'
}) {
  const t = useT()
  const { locale } = useLocale()
  const catalog = PLATFORM_REPORT_CATALOGS[platform]
  const apiBase = `${API_BASE_URL}${reportsApiBase(platform)}`
  const showChat = platform === 'virt' || platform === 'linux' || platform === 'windows'
  const showCompare = platform === 'virt' || platform === 'linux' || platform === 'windows'
  const [mainTab, setMainTab] = useState<'reports' | 'chat' | 'compare'>(() => {
    if (initialTab) return initialTab
    try {
      const t = new URLSearchParams(window.location.search).get('tab')
      if (t === 'compare' || t === 'chat' || t === 'reports') return t
    } catch { /* ignore */ }
    return 'reports'
  })

  useEffect(() => {
    if (initialTab) setMainTab(initialTab)
  }, [initialTab, platform])
  const [generating, setGenerating] = useState<string | null>(null)
  const [viewReport, setViewReport] = useState<{
    type: string
    title: string
    data: Record<string, unknown>
    markdown?: string
    preferMarkdown?: boolean
  } | null>(null)
  const [lastGenTimes, setLastGenTimes] = useState<Record<string, string>>({})
  const [chatQuestion, setChatQuestion] = useState('')
  const [pendingChatQuestion, setPendingChatQuestion] = useState<string | null>(null)

  type CustomReportRow = {
    id: number
    title: string
    description: string | null
    last_run_at: string | null
    last_ok: boolean | null
    last_rendered: string | null
    last_error: string | null
    tool_name: string
  }

  const { data: customReportsData, refetch: refetchCustom } = useQuery({
    queryKey: ['custom-reports-catalog', platform],
    queryFn: async (): Promise<CustomReportRow[]> => {
      const r = await fetch(`${API_BASE_URL}/custom-reports/?platform=${encodeURIComponent(platform)}`)
      if (!r.ok) return []
      const j = await r.json()
      return (j.reports || []) as CustomReportRow[]
    },
    staleTime: 30_000,
  })
  const customReports = customReportsData || []

  const { data: history, refetch: refetchHistory } = useQuery({
    queryKey: ['report-history', platform],
    queryFn: async () => {
      const r = await fetch(`${apiBase}/history?limit=50`)
      if (!r.ok) return { reports: [] }
      return r.json()
    },
    staleTime: 30_000,
  })

  const { data: dataQuality } = useQuery({
    queryKey: ['report-data-quality', platform],
    queryFn: async () => {
      if (platform !== 'virt') return null
      const r = await fetch(`${API_BASE_URL}/hypervisors/reports/data-quality`)
      if (!r.ok) return null
      return r.json()
    },
    staleTime: 60_000,
    enabled: platform === 'virt',
  })

  const histMap: Record<string, string> = {}
  for (const rpt of (history?.reports || [])) {
    if (!histMap[rpt.type] || rpt.generated_at > histMap[rpt.type]) {
      histMap[rpt.type] = rpt.generated_at
    }
  }
  for (const cr of customReports) {
    const key = `custom:${cr.id}`
    if (cr.last_run_at) histMap[key] = cr.last_run_at
  }

  function isCustomType(type: string): boolean {
    return type.startsWith('custom:')
  }

  function customIdFromType(type: string): number | null {
    const n = Number(type.slice('custom:'.length))
    return Number.isFinite(n) && n > 0 ? n : null
  }

  async function handleGenerateCustom(type: string) {
    const id = customIdFromType(type)
    if (!id) return
    setGenerating(type)
    try {
      const r = await fetch(`${API_BASE_URL}/custom-reports/${id}/run`, { method: 'POST' })
      if (!r.ok) {
        const e = await r.json().catch(() => ({ detail: r.statusText }))
        throw new Error(e.detail || `HTTP ${r.status}`)
      }
      const j = await r.json()
      const report = j.report || {}
      const run = j.run || {}
      const md = (run.rendered || report.last_rendered || '') as string
      if (!run.ok && !md) {
        throw new Error(run.error || report.last_error || t('rpt_custom_empty_result'))
      }
      setViewReport({
        type,
        title: report.title || `custom:${id}`,
        data: {
          custom_report: true,
          report_id: id,
          tool_name: report.tool_name,
          tool_args: report.tool_args,
          generated_at: report.last_run_at || new Date().toISOString(),
          ok: run.ok,
          error: run.error,
        },
        markdown: md || (run.error ? `**Hata:** ${run.error}` : t('rpt_custom_empty_result')),
        preferMarkdown: true,
      })
      setLastGenTimes(prev => ({ ...prev, [type]: new Date().toISOString() }))
      refetchCustom()
    } catch (err) {
      alert(t('rpt_custom_run_err', { msg: String(err) }))
    } finally {
      setGenerating(null)
    }
  }

  async function handleViewCustom(type: string) {
    const id = customIdFromType(type)
    const cr = customReports.find(c => c.id === id)
    if (cr?.last_rendered && cr.last_ok !== false) {
      setViewReport({
        type,
        title: cr.title,
        data: {
          custom_report: true,
          report_id: cr.id,
          tool_name: cr.tool_name,
          generated_at: cr.last_run_at || undefined,
          ok: cr.last_ok,
          error: cr.last_error,
        },
        markdown: cr.last_rendered,
        preferMarkdown: true,
      })
      return
    }
    await handleGenerateCustom(type)
  }

  async function handleGenerate(type: string) {
    if (isCustomType(type)) {
      await handleGenerateCustom(type)
      return
    }
    setGenerating(type)
    try {
      const r = await fetch(`${apiBase}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_type: type, save: true }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const { data, markdown } = await r.json()
      const cat = catalog.find(c => c.type === type)
      setViewReport({ type, title: cat ? t(cat.titleKey) : type, data, markdown })
      setLastGenTimes(prev => ({ ...prev, [type]: new Date().toISOString() }))
      refetchHistory()
    } catch (err) {
      alert(t('rpt_gen_err', { msg: String(err) }))
    } finally {
      setGenerating(null)
    }
  }

  async function handleView(type: string) {
    if (isCustomType(type)) {
      await handleViewCustom(type)
      return
    }
    const r = await fetch(`${apiBase}/latest/${type}`)
    if (!r.ok) { handleGenerate(type); return }
    const { data, markdown } = await r.json()
    const cat = catalog.find(c => c.type === type)
    setViewReport({ type, title: cat ? t(cat.titleKey) : type, data, markdown })
  }

  function handleChatAsk() {
    if (!chatQuestion.trim()) return
    setPendingChatQuestion(chatQuestion.trim())
    setChatQuestion('')
    setMainTab('chat')
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header + Tab Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t(PLATFORM_REPORT_TITLE_KEYS[platform])}</h1>
          <p className="text-slate-400 text-sm mt-1">{t(PLATFORM_REPORT_SUBTITLE_KEYS[platform])}</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Clock size={13} />
          <span>{t('rpt_n_history', { n: history?.reports?.length || 0 })}</span>
        </div>
      </div>

      {/* Main Tab Switcher — Raporlar / AI Asistan / Karşılaştırma */}
      {(showChat || showCompare) && (
      <div className="flex gap-1 bg-slate-800/60 border border-slate-700 rounded-xl p-1 w-fit">
        <button
          onClick={() => setMainTab('reports')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            mainTab === 'reports'
              ? 'bg-blue-600 text-white shadow'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <BarChart3 size={15} /> {t('rpt_tab_reports')}
        </button>
        {showChat && (
        <button
          onClick={() => setMainTab('chat')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            mainTab === 'chat'
              ? 'bg-blue-600 text-white shadow'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Bot size={15} /> {t('rpt_tab_ai')}
        </button>
        )}
        {showCompare && (
        <button
          onClick={() => setMainTab('compare')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            mainTab === 'compare'
              ? 'bg-indigo-600 text-white shadow'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <GitCompare size={15} />{' '}
          {platform === 'virt' ? t('rpt_tab_cmp_virt') : t('rpt_tab_cmp_os')}
        </button>
        )}
      </div>
      )}

      {showCompare && mainTab === 'compare' && (
        <ServerComparePanel platform={platform} />
      )}

      {showChat && mainTab === 'chat' && (
        <div className="-mx-6 -mb-6 border-t border-slate-700/50">
          {platform === 'virt' && (
            <HypervisorChatPage
              embedded
              initialQuestion={pendingChatQuestion}
              onInitialQuestionUsed={() => setPendingChatQuestion(null)}
            />
          )}
          {platform === 'linux' && (
            <LinuxChatPage
              embedded
              initialQuestion={pendingChatQuestion}
              onInitialQuestionUsed={() => setPendingChatQuestion(null)}
            />
          )}
          {platform === 'windows' && (
            <WindowsChatPage
              embedded
              initialQuestion={pendingChatQuestion}
              onInitialQuestionUsed={() => setPendingChatQuestion(null)}
            />
          )}
        </div>
      )}

      {/* Reports tab content below */}
      {(mainTab === 'reports' || (!showChat && !showCompare)) && (<>

      {platform === 'virt' && <DataQualityBanner quality={dataQuality} />}

      {showChat && (
      <div className="bg-gradient-to-r from-blue-900/30 to-indigo-900/30 border border-blue-700/40 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Bot size={16} className="text-blue-400" />
          <span className="text-blue-300 text-sm font-medium">{t('rpt_ask_ai')}</span>
        </div>
        <div className="flex gap-2">
          <input
            value={chatQuestion}
            onChange={e => setChatQuestion(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleChatAsk()}
            placeholder={
              platform === 'linux' ? t('rpt_ph_linux') :
              platform === 'windows' ? t('rpt_ph_win') :
              t('rpt_ph_virt')
            }
            className="flex-1 bg-slate-800/60 border border-slate-700 rounded-lg px-4 py-2 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button onClick={handleChatAsk} disabled={!chatQuestion.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 flex items-center gap-2 transition-all">
            <ChevronRight size={14} />
            {t('rpt_ask_in_ai')}
          </button>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          {platform === 'virt' ? t('rpt_ask_hint_virt') : t('rpt_ask_hint_os')}
        </p>
      </div>
      )}

      {/* Rapor kataloğu — sabit + bu platformdaki özel raporlar */}
      <div>
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="text-slate-300 text-sm font-medium">{t('rpt_all')}</h2>
          <Link
            to="/custom-reports"
            className="text-[11px] text-lime-400/80 hover:text-lime-300 flex items-center gap-1"
          >
            <FileBarChart2 size={12} />
            {t('rpt_custom_manage')}
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {catalog.map(cat => (
            <div key={cat.type} className="cursor-pointer" onClick={() => histMap[cat.type] ? handleView(cat.type) : undefined}>
              <ReportCard
                type={cat.type}
                title={t(cat.titleKey)}
                icon={cat.icon}
                color={cat.color}
                desc={t(cat.descKey)}
                onGenerate={handleGenerate}
                isLoading={generating === cat.type}
                lastGenerated={lastGenTimes[cat.type] || histMap[cat.type]}
              />
            </div>
          ))}
          {customReports.map(cr => {
            const ctype = `custom:${cr.id}`
            return (
              <div
                key={ctype}
                className="cursor-pointer"
                onClick={() => histMap[ctype] || cr.last_rendered ? handleView(ctype) : undefined}
              >
                <ReportCard
                  type={ctype}
                  title={cr.title}
                  icon={<FileBarChart2 size={18} />}
                  color="lime"
                  desc={cr.description || t('rpt_custom_desc')}
                  badge={t('rpt_custom_badge')}
                  onGenerate={handleGenerate}
                  isLoading={generating === ctype}
                  lastGenerated={lastGenTimes[ctype] || histMap[ctype]}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Geçmiş */}
      {history?.reports?.length > 0 && (
        <div>
          <h2 className="text-slate-300 text-sm font-medium mb-3">{t('rpt_recent')}</h2>
          <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 text-xs text-slate-500">
                  <th className="text-left px-4 py-2">{t('rpt_col_report')}</th>
                  <th className="text-left px-4 py-2">{t('rpt_col_created')}</th>
                  <th className="text-left px-4 py-2">{t('col_status')}</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {history.reports.slice(0, 10).map((rpt: any) => {
                  const cat = catalog.find(c => c.type === rpt.type)
                  return (
                    <tr key={rpt.id} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500">{cat?.icon}</span>
                          <span className="text-white">{cat ? t(cat.titleKey) : rpt.title}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs">
                        {rpt.generated_at ? new Date(rpt.generated_at).toLocaleString(dateLoc(locale)) : '-'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded-full">{rpt.status}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleGenerate(rpt.type)}
                            disabled={generating === rpt.type}
                            title={t('rpt_gen_short')}
                            className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1 disabled:opacity-50"
                          >
                            {generating === rpt.type
                              ? <Loader2 size={12} className="animate-spin" />
                              : <Zap size={12} />}
                            {generating === rpt.type ? t('rpt_fetching') : t('rpt_new')}
                          </button>
                          <button
                            onClick={async () => {
                              const r = await fetch(`${apiBase}/latest/${rpt.type}`)
                              if (!r.ok) return
                              const { markdown } = await r.json()
                              if (!markdown) return
                              exportMarkdownToPrintWindow(markdown, {
                                title: rpt.title,
                                subtitle: t('rpt_generated', { dt: new Date(rpt.generated_at).toLocaleString(dateLoc(locale)) }),
                                filename: `${rpt.type}_${rpt.generated_at?.split('T')[0] || ''}`,
                              })
                            }}
                            className="text-xs text-red-400/70 hover:text-red-300 flex items-center gap-1"
                          >
                            <FileDown size={12} /> PDF
                          </button>
                          <button onClick={() => handleView(rpt.type)}
                            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
                            <Eye size={12} /> {t('rpt_view')}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Viewer modal */}
      {viewReport && (
        <ReportViewer
          type={viewReport.type}
          title={viewReport.title}
          data={viewReport.data}
          markdown={viewReport.markdown}
          preferMarkdown={viewReport.preferMarkdown}
          onClose={() => setViewReport(null)}
          onRegenerate={handleGenerate}
          regenerating={generating === viewReport.type}
        />
      )}
      </>)}
    </div>
  )
}
