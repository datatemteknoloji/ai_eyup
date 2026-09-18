import mermaid from 'mermaid'
import type { ChatChartPayload } from '../components/ChatMetricChart'
import { niceTimeTicks, niceYDomain } from './chatChartScale'
import { parseArchitectureDiagram } from './chatDiagramSchema'

export { niceYDomain } from './chatChartScale'

const CHART_COLORS = ['#2563eb', '#059669', '#d97706', '#db2777', '#7c3aed', '#0891b2']

function esc(s: string): string {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function formatTick(ts: string, spanMs: number): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  if (spanMs <= 36 * 3600 * 1000) {
    return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  }
  if (spanMs <= 14 * 24 * 3600 * 1000) {
    return d.toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit' })
  }
  if (spanMs <= 400 * 24 * 3600 * 1000) {
    return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })
  }
  return d.toLocaleDateString('tr-TR', { month: 'short', year: 'numeric' })
}

function formatVal(v: number, unit: string): string {
  if (unit === '%') return `${v.toFixed(1)}%`
  if (unit === 'B/s') {
    const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
    let val = v
    let i = 0
    while (Math.abs(val) >= 1024 && i < units.length - 1) {
      val /= 1024
      i += 1
    }
    return `${val.toFixed(1)} ${units[i]}`
  }
  return String(Math.round(v * 100) / 100)
}

function seriesStats(points: { t: string; v: number }[]): { min: number; max: number; last: number } | null {
  const vals = points.map((p) => p.v).filter((v) => Number.isFinite(v))
  if (!vals.length) return null
  return {
    min: Math.min(...vals),
    max: Math.max(...vals),
    last: vals[vals.length - 1],
  }
}

/** Chat chart payload → yazdırılabilir SVG (Recharts ekranda kalır). */
export function chartToSvg(chart: ChatChartPayload): string {
  const series = (chart.series || []).filter((s) => (s.points || []).length >= 2)
  if (!series.length) return ''
  const w = 900
  const legendRows = Math.ceil(series.length / 2)
  const legendH = 22 + legendRows * 18
  const pad = { l: 56, r: 16, t: 32, b: 28 + legendH }
  const h = 300 + legendH
  const iw = w - pad.l - pad.r
  const ih = h - pad.t - pad.b
  const stamps = new Set<string>()
  series.forEach((s) => s.points.forEach((p) => stamps.add(p.t)))
  const times = Array.from(stamps).sort()
  const first = new Date(times[0]).getTime()
  const last = new Date(times[times.length - 1]).getTime()
  const span = Math.max(1, last - first)
  let rawMin = Infinity
  let rawMax = -Infinity
  series.forEach((s) => s.points.forEach((p) => {
    if (Number.isFinite(p.v)) {
      rawMin = Math.min(rawMin, p.v)
      rawMax = Math.max(rawMax, p.v)
    }
  }))
  if (!Number.isFinite(rawMin)) return ''
  const { min: minV, max: maxV } = niceYDomain(rawMin, rawMax, chart.unit || '')
  const ySpan = Math.max(1e-9, maxV - minV)
  const xOf = (t: string) => pad.l + ((new Date(t).getTime() - first) / span) * iw
  const yOf = (v: number) => pad.t + (1 - (v - minV) / ySpan) * ih
  const paths = series.map((s, i) => {
    const pts = [...s.points].sort((a, b) => a.t.localeCompare(b.t))
    const d = pts.map((p, idx) => `${idx ? 'L' : 'M'}${xOf(p.t).toFixed(1)},${yOf(p.v).toFixed(1)}`).join(' ')
    const color = CHART_COLORS[i % CHART_COLORS.length]
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`
  }).join('')
  const xTimes = niceTimeTicks(first, last)
  const ticks = xTimes.map((ms, i) => {
    const x = xOf(new Date(ms).toISOString())
    const anchor = i === 0 ? 'start' : i === xTimes.length - 1 ? 'end' : 'middle'
    return `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + ih}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${x.toFixed(1)}" y="${pad.t + ih + 18}" text-anchor="${anchor}" font-size="11" fill="#334155">${esc(formatTick(new Date(ms).toISOString(), span))}</text>`
  }).join('')
  const yTickCount = 5
  const yTicks = Array.from({ length: yTickCount }, (_, i) => {
    const f = i / (yTickCount - 1)
    const v = maxV - f * ySpan
    const y = pad.t + f * ih
    return `<text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#334155">${esc(formatVal(v, chart.unit))}</text>
      <line x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}" stroke="#e2e8f0" stroke-width="1"/>`
  }).join('')
  const legend = series.map((s, i) => {
    const color = CHART_COLORS[i % CHART_COLORS.length]
    const col = i % 2
    const row = Math.floor(i / 2)
    const x = pad.l + col * (iw / 2)
    const y = pad.t + ih + 38 + row * 18
    const name = (s.label || s.metric_name || `seri-${i + 1}`).slice(0, 40)
    const st = seriesStats([...s.points].sort((a, b) => a.t.localeCompare(b.t)))
    const line = st
      ? `${name}  ${formatVal(st.min, chart.unit)}–${formatVal(st.max, chart.unit)} · son ${formatVal(st.last, chart.unit)}`
      : name
    return `<rect x="${x}" y="${y - 8}" width="12" height="3" rx="1" fill="${color}"/>
      <text x="${x + 18}" y="${y}" font-size="11" fill="#0f172a">${esc(line)}</text>`
  }).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:100%;height:auto;background:#fff">
    <text x="${pad.l}" y="20" font-size="13" font-weight="600" fill="#0f172a">${esc(chart.title)}</text>
    ${yTicks}${paths}${ticks}${legend}
  </svg>`
}

function diagramToSvg(raw: string): string {
  const d = parseArchitectureDiagram(raw)
  if (!d) return ''
  const w = 640
  const boxW = 150
  const boxH = 36
  const gapX = 24
  const gapY = 28
  const layers = d.layers.length ? d.layers : [{ id: 'all', label: '' }]
  const byLayer = new Map<string, typeof d.nodes>()
  for (const n of d.nodes) {
    const key = n.layer || layers[0]?.id || 'all'
    const arr = byLayer.get(key) || []
    arr.push(n)
    byLayer.set(key, arr)
  }
  const pos = new Map<string, { x: number; y: number }>()
  let y = 36
  for (const layer of layers) {
    const nodes = byLayer.get(layer.id) || []
    if (!nodes.length) continue
    const cols = Math.min(3, nodes.length)
    nodes.forEach((n, i) => {
      const col = i % cols
      const row = Math.floor(i / cols)
      const x = 20 + col * (boxW + gapX)
      const ny = y + row * (boxH + 10)
      pos.set(n.id, { x, y: ny })
    })
    const rowsN = Math.ceil(nodes.length / cols)
    y += rowsN * (boxH + 10) + gapY
  }
  const h = Math.max(120, y + 12)
  const boxes = d.nodes.map((n) => {
    const p = pos.get(n.id)
    if (!p) return ''
    return `<rect x="${p.x}" y="${p.y}" width="${boxW}" height="${boxH}" rx="6" fill="#dbeafe" stroke="#1d4ed8"/>
      <text x="${p.x + boxW / 2}" y="${p.y + 22}" text-anchor="middle" font-size="11" fill="#0f172a">${esc(n.label)}</text>`
  }).join('')
  const lines = d.edges.map((e) => {
    const a = pos.get(e.from)
    const b = pos.get(e.to)
    if (!a || !b) return ''
    return `<line x1="${a.x + boxW / 2}" y1="${a.y + boxH}" x2="${b.x + boxW / 2}" y2="${b.y}" stroke="#64748b" stroke-width="1.4"/>`
  }).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:100%;height:auto;background:#fff">${lines}${boxes}</svg>`
}

async function mermaidToSvg(src: string): Promise<string> {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base' })
  const id = `pdf-mmd-${Math.random().toString(36).slice(2, 9)}`
  const { svg } = await mermaid.render(id, src.trim())
  return svg
}

const FENCE_RE = /```(mermaid|ainew-diagram)\s*\n([\s\S]*?)```/gi

/** Diyagram çitlerini markdown parser'ın bozmayacağı yer tutucularla değiştirir. */
export async function extractDiagramSlots(markdown: string): Promise<{ text: string; html: string[] }> {
  const html: string[] = []
  const src = String(markdown || '')
  let out = ''
  let last = 0
  for (const m of src.matchAll(FENCE_RE)) {
    out += src.slice(last, m.index)
    const lang = (m[1] || '').toLowerCase()
    const body = m[2] || ''
    let slot = ''
    try {
      if (lang === 'mermaid') {
        slot = `<div class="chat-pdf-diagram">${await mermaidToSvg(body)}</div>`
      } else {
        const svg = diagramToSvg(body)
        if (svg) slot = `<div class="chat-pdf-diagram">${svg}</div>`
      }
    } catch {
      slot = ''
    }
    if (slot) {
      out += `\n\nPDFVIZPLACEHOLDER${html.length}END\n\n`
      html.push(slot)
    } else {
      out += m[0]
    }
    last = (m.index || 0) + m[0].length
  }
  out += src.slice(last)
  return { text: out, html }
}

export function injectDiagramSlots(html: string, slots: string[]): string {
  return html.replace(/PDFVIZPLACEHOLDER(\d+)END/g, (_, i) => slots[Number(i)] || '')
}

export function chartsToHtml(charts: ChatChartPayload[] | undefined | null): string {
  if (!charts?.length) return ''
  return charts.map((c) => {
    const svg = chartToSvg(c)
    return svg ? `<div class="chat-pdf-chart">${svg}</div>` : ''
  }).join('')
}
