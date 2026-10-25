/**
 * Yönetici Raporları — beş hazır rapor, veri hazırlığı ve yöntem rozeti.
 * Sayılar backend gerçeklerinden gelir. AI metni bu sayfada üretilmez;
 * kapıdan geçmemiş metin yoktur, kartta kural cümlesi durur.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Download, Printer, RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { AiBlock, MethodBadge } from '../components/insights/MethodBadge'

type Num = { value: number | string; unit?: string; display?: string[] }
type Section = {
  id: string
  title: string
  method_id: string
  status: 'ok' | 'unmeasured' | 'not_applicable'
  numbers: Record<string, Num>
  labels: Record<string, string>
  notes: string[]
  rows: Array<Record<string, unknown>>
}
type Readiness = { section_id: string; status: string; reason: string; days_available?: number | null; days_required?: number | null }
type Facts = {
  report_type: string
  period: { start: string; end: string }
  sections: Section[]
  data_readiness: Readiness[]
}

const TITLES: Record<string, string> = {
  a1: 'Aylık yönetici özeti',
  b1: 'Kapasite tükenme',
  b2: 'Yatırım ihtiyacı',
  a2: 'Atıl kaynak',
  a6: 'Olay ve operasyon',
}

const STATUS: Record<string, string> = {
  ok: 'Ölçüldü',
  unmeasured: 'Ölçülemedi',
  not_applicable: 'Uygulanmaz',
}

function monthRange(month: string): { start: string; end: string } {
  const [y, m] = month.split('-').map(Number)
  const start = new Date(Date.UTC(y, m - 1, 1))
  const end = new Date(Date.UTC(y, m, 1))
  return { start: start.toISOString(), end: end.toISOString() }
}

function ruleLine(section: Section): string {
  if (section.status !== 'ok') return section.notes[0] || 'Veri yok.'
  const bits = Object.values(section.numbers).map((n) => n.display?.[0]).filter(Boolean)
  return bits.length ? `${section.title}: ${bits.join(', ')}.` : section.notes[0] || section.title
}

export default function ExecutiveReports() {
  const now = new Date()
  const [month, setMonth] = useState(`${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`)
  const range = useMemo(() => monthRange(month), [month])
  const q = useQuery<{ reports: Facts[] }>({
    queryKey: ['executive-facts', range.start, range.end],
    queryFn: async () => {
      const url = `${API_BASE_URL}/ops/executive-facts?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`
      const res = await fetch(url)
      if (!res.ok) throw new Error('Raporlar alınamadı')
      return res.json()
    },
  })

  const reports = q.data?.reports || []
  const gaps = reports.flatMap((r) => (r.data_readiness || []).filter((d) => d.status !== 'ok').map((d) => ({ ...d, report: r.report_type })))

  function downloadCsv() {
    const lines = ['rapor,bolum,anahtar,deger,birim']
    for (const report of reports) {
      for (const section of report.sections) {
        for (const [key, num] of Object.entries(section.numbers || {})) {
          lines.push([report.report_type, section.id, key, String(num.value), num.unit || ''].join(','))
        }
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `yonetici-raporlari-${month}.csv`
    a.click()
  }

  return (
    <div className="p-4 md:p-6 space-y-4 text-slate-200">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Yönetici Raporları</h1>
          <p className="text-sm text-slate-400">Platform notları ayrıdır. Genel not, en kötü platformu aşmaz.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
            aria-label="Dönem"
          />
          <button type="button" onClick={() => q.refetch()} className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm inline-flex items-center gap-1">
            <RefreshCw size={14} className={q.isFetching ? 'animate-spin' : ''} /> Yenile
          </button>
          <button type="button" onClick={downloadCsv} className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm inline-flex items-center gap-1">
            <Download size={14} /> CSV
          </button>
          <button type="button" onClick={() => window.print()} className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm inline-flex items-center gap-1">
            <Printer size={14} /> PDF
          </button>
        </div>
      </div>

      <section className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
        <h2 className="text-sm font-semibold text-white mb-2">Veri hazırlığı</h2>
        {q.isLoading && <p className="text-sm text-slate-400">Yükleniyor…</p>}
        {q.isError && <p className="text-sm text-red-300">Raporlar alınamadı.</p>}
        {!q.isLoading && gaps.length === 0 && <p className="text-sm text-slate-400">Eksik bölüm yok.</p>}
        <ul className="space-y-1 text-sm">
          {gaps.map((g) => (
            <li key={`${g.report}-${g.section_id}`} className="text-slate-300">
              <span className="text-slate-500">{TITLES[g.report] || g.report} — </span>
              {g.reason}
              {g.days_available != null && g.days_required != null ? ` (${g.days_available}/${g.days_required} gün)` : ''}
            </li>
          ))}
        </ul>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {reports.map((report) => (
          <article key={report.report_type} className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-semibold text-white">{TITLES[report.report_type] || report.report_type}</h2>
              <Link to="/infra-reports" className="text-xs text-sky-300 hover:underline">Altyapı raporları</Link>
            </div>
            {report.sections.map((section) => (
              <div key={section.id} className="space-y-2 border-t border-slate-800 pt-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-slate-200">{section.title}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full border border-slate-600 text-slate-300">{STATUS[section.status] || section.status}</span>
                  <MethodBadge id={section.method_id} />
                </div>
                <div className="flex flex-wrap gap-3 text-sm">
                  {Object.entries(section.numbers || {}).map(([key, num]) => (
                    <span key={key} className="tabular-nums text-white">{num.display?.[0] ?? num.value}<span className="text-slate-500 text-xs ml-1">{key}</span></span>
                  ))}
                </div>
                {Object.keys(section.labels || {}).length > 0 && (
                  <p className="text-xs text-slate-400">{Object.values(section.labels).join(' · ')}</p>
                )}
                <AiBlock method={section.method_id}>{ruleLine(section)}</AiBlock>
              </div>
            ))}
          </article>
        ))}
      </div>
    </div>
  )
}
