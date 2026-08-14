import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitCompare, Loader2, Sparkles, Check, X, Search } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import type { PlatformKey } from '../config/platformAiops'
import { useT } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

type Candidate = {
  id: number
  name: string
  hostname?: string
  ip_address?: string
  status?: string
  os?: string
  type?: string
  hypervisor?: string
  cpu_cores?: number
  memory_gb?: number
}

type DiffRow = {
  key: string
  label: string
  values: string[]
  identical: boolean
}

type CompareResult = {
  platform: string
  entity_type: string
  labels: string[]
  profiles: any[]
  diffs: {
    config: DiffRow[]
    architecture: DiffRow[]
    summary: {
      config: { same: number; different: number; total: number }
      architecture: { same: number; different: number; total: number }
      total_same: number
      total_different: number
    }
  }
  ai_analysis?: string | null
}

type TFn = (key: TranslationKey, vars?: Record<string, string | number>) => string

const ENTITY_OPTIONS: Record<string, { value: string; labelKey: TranslationKey }[]> = {
  linux: [{ value: 'server', labelKey: 'cmp_linux_os' }],
  windows: [{ value: 'server', labelKey: 'cmp_win_os' }],
  virt: [
    { value: 'vm', labelKey: 'cmp_vm' },
    { value: 'esx', labelKey: 'cmp_esx' },
  ],
  exadata: [{ value: 'server', labelKey: 'cmp_server' }],
}

function scopeCopy(platform: PlatformKey, entityType: string, t: TFn) {
  if (platform === 'virt' && entityType === 'esx') {
    return {
      title: t('cmp_esx_title'),
      subtitle: t('cmp_esx_sub'),
      configTitle: t('cmp_esx_cfg'),
      archTitle: t('cmp_esx_arch'),
      hint: t('cmp_esx_hint'),
      searchPh: t('cmp_esx_search'),
    }
  }
  if (platform === 'virt' && entityType === 'vm') {
    return {
      title: t('cmp_vm_title'),
      subtitle: t('cmp_vm_sub'),
      configTitle: t('cmp_vm_cfg'),
      archTitle: t('cmp_vm_arch'),
      hint: t('cmp_vm_hint'),
      searchPh: t('cmp_vm_search'),
    }
  }
  if (platform === 'windows') {
    return {
      title: t('cmp_win_title'),
      subtitle: t('cmp_win_sub'),
      configTitle: t('cmp_os_cfg'),
      archTitle: t('cmp_vm_arch'),
      hint: t('cmp_win_hint'),
      searchPh: t('cmp_os_search'),
    }
  }
  return {
    title: t('cmp_linux_title'),
    subtitle: t('cmp_linux_sub'),
    configTitle: t('cmp_os_cfg'),
    archTitle: t('cmp_vm_arch'),
    hint: t('cmp_linux_hint'),
    searchPh: t('cmp_linux_search'),
  }
}

function DiffTable({
  title,
  rows,
  labels,
  onlyDiffs,
}: {
  title: string
  rows: DiffRow[]
  labels: string[]
  onlyDiffs: boolean
}) {
  const t = useT()
  const visible = onlyDiffs ? rows.filter((r) => !r.identical) : rows
  if (!visible.length) {
    return (
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
        <h3 className="text-sm font-medium text-slate-200 mb-2">{title}</h3>
        <p className="text-xs text-slate-500">{t('cmp_no_fields')}</p>
      </div>
    )
  }
  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-200">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700/40">
              <th className="text-left px-4 py-2 font-medium w-48">{t('cmp_field')}</th>
              {labels.map((l) => (
                <th key={l} className="text-left px-4 py-2 font-medium">{l}</th>
              ))}
              <th className="text-center px-3 py-2 w-16">{t('col_status')}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.key}
                className={`border-b border-slate-800/60 ${
                  r.identical ? 'bg-transparent' : 'bg-amber-500/5'
                }`}
              >
                <td className="px-4 py-2 text-slate-300 font-medium">{r.label}</td>
                {r.values.map((v, i) => (
                  <td
                    key={i}
                    className={`px-4 py-2 font-mono text-xs ${
                      r.identical ? 'text-slate-400' : 'text-amber-200'
                    }`}
                  >
                    {v}
                  </td>
                ))}
                <td className="px-3 py-2 text-center">
                  {r.identical ? (
                    <Check size={14} className="inline text-emerald-400" />
                  ) : (
                    <X size={14} className="inline text-amber-400" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ServerComparePanel({ platform }: { platform: PlatformKey }) {
  const t = useT()
  const entityOpts = ENTITY_OPTIONS[platform] || ENTITY_OPTIONS.linux
  const [entityType, setEntityType] = useState(entityOpts[0].value)
  const [selected, setSelected] = useState<number[]>([])
  const [search, setSearch] = useState('')
  const [onlyDiffs, setOnlyDiffs] = useState(true)
  const [withAi, setWithAi] = useState(true)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<CompareResult | null>(null)

  React.useEffect(() => {
    setEntityType(entityOpts[0].value)
    setSelected([])
    setResult(null)
  }, [platform])

  const copy = scopeCopy(platform, entityType, t)

  const { data: candidatesData, isLoading: candLoading } = useQuery({
    queryKey: ['compare-candidates', platform, entityType],
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/compare/candidates?platform=${platform}&entity_type=${entityType}`
      )
      if (!r.ok) throw new Error(t('cmp_candidates_fail'))
      return r.json() as Promise<{ items: Candidate[]; count: number }>
    },
  })

  const candidates = candidatesData?.items || []
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter((c) =>
      [c.name, c.hostname, c.ip_address, c.os, c.hypervisor, c.type]
        .filter(Boolean)
        .some((x) => String(x).toLowerCase().includes(q))
    )
  }, [candidates, search])

  function toggle(id: number) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 3) return prev
      return [...prev, id]
    })
  }

  async function runCompare() {
    if (selected.length < 2) {
      setError(t('cmp_need_two'))
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          entity_type: entityType,
          ids: selected,
          with_ai: withAi,
          question: question.trim() || null,
        }),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      setResult(data)
    } catch (e: any) {
      setError(e?.message || t('cmp_fail'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="bg-gradient-to-r from-indigo-900/25 to-slate-900/40 border border-indigo-700/30 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
            <GitCompare size={18} className="text-indigo-300" />
          </div>
          <div>
            <h2 className="text-white text-sm font-semibold">{copy.title}</h2>
            <p className="text-slate-400 text-xs mt-1 leading-relaxed">{copy.subtitle}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-3">
          {entityOpts.length > 1 && (
            <div>
              <label className="text-xs text-slate-400 mb-1.5 block">{t('cmp_type')}</label>
              <div className="flex gap-1 bg-slate-800/60 border border-slate-700 rounded-lg p-1">
                {entityOpts.map((o) => (
                  <button
                    key={o.value}
                    onClick={() => {
                      setEntityType(o.value)
                      setSelected([])
                      setResult(null)
                    }}
                    className={`flex-1 text-xs px-2 py-1.5 rounded-md transition-all ${
                      entityType === o.value
                        ? 'bg-indigo-600 text-white'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {t(o.labelKey)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs text-slate-400 mb-1.5 block">
              {t('cmp_selection', { n: selected.length, hint: copy.hint })}
            </label>
            <div className="relative mb-2">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={copy.searchPh}
                className="w-full bg-slate-800/60 border border-slate-700 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div className="max-h-80 overflow-y-auto border border-slate-700/60 rounded-lg divide-y divide-slate-800/80 bg-slate-900/40">
              {candLoading && (
                <div className="p-4 text-xs text-slate-500 flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> {t('loading')}
                </div>
              )}
              {!candLoading && filtered.length === 0 && (
                <div className="p-4 text-xs text-slate-500">{t('cmp_none')}</div>
              )}
              {filtered.map((c) => {
                const on = selected.includes(c.id)
                return (
                  <button
                    key={c.id}
                    onClick={() => toggle(c.id)}
                    className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${
                      on ? 'bg-indigo-600/20' : 'hover:bg-slate-800/60'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-white font-medium truncate">{c.name}</span>
                      {on && <Check size={14} className="text-indigo-300 flex-shrink-0" />}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5 truncate">
                      {[c.ip_address, c.hostname, c.os || c.type, c.hypervisor]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={withAi}
                onChange={(e) => setWithAi(e.target.checked)}
                className="rounded border-slate-600"
              />
              {t('cmp_ai')}
            </label>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t('cmp_q_ph')}
              className="w-full bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={runCompare}
              disabled={loading || selected.length < 2}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
            >
              {loading ? (
                <>
                  <Loader2 size={15} className="animate-spin" /> {t('cmp_comparing')}
                </>
              ) : (
                <>
                  <GitCompare size={15} /> {t('cmp_compare')}
                </>
              )}
            </button>
            {error && <p className="text-xs text-red-400">{error}</p>}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {!result && !loading && (
            <div className="h-64 flex flex-col items-center justify-center text-center border border-dashed border-slate-700 rounded-xl">
              <GitCompare size={32} className="text-slate-600 mb-3" />
              <p className="text-slate-400 text-sm">{t('cmp_pick_two')}</p>
            </div>
          )}
          {loading && (
            <div className="h-64 flex flex-col items-center justify-center text-center">
              <Loader2 size={28} className="animate-spin text-indigo-400 mb-3" />
              <p className="text-slate-400 text-sm">
                {withAi ? t('cmp_ai_wait') : t('cmp_wait')}
              </p>
            </div>
          )}
          {result && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  {result.labels.map((l) => (
                    <span
                      key={l}
                      className="px-2.5 py-1 rounded-md bg-slate-800 border border-slate-600 text-xs text-slate-200"
                    >
                      {l}
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-emerald-400">
                    {t('cmp_same', { n: result.diffs.summary.total_same })}
                  </span>
                  <span className="text-amber-400">
                    {t('cmp_diff', { n: result.diffs.summary.total_different })}
                  </span>
                  <label className="flex items-center gap-1.5 text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={onlyDiffs}
                      onChange={(e) => setOnlyDiffs(e.target.checked)}
                    />
                    {t('cmp_diffs_only')}
                  </label>
                </div>
              </div>

              <DiffTable
                title={copy.configTitle}
                rows={result.diffs.config}
                labels={result.labels}
                onlyDiffs={onlyDiffs}
              />
              <DiffTable
                title={copy.archTitle}
                rows={result.diffs.architecture}
                labels={result.labels}
                onlyDiffs={onlyDiffs}
              />

              {result.ai_analysis && (
                <div className="bg-indigo-950/30 border border-indigo-700/40 rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles size={15} className="text-indigo-300" />
                    <h3 className="text-sm font-medium text-indigo-200">{t('cmp_ai_comment')}</h3>
                  </div>
                  <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
                    {result.ai_analysis}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
