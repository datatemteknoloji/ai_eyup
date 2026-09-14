import mermaid from 'mermaid'
import type { ChatChartPayload } from '../components/ChatMetricChart'
import { parseArchitectureDiagram } from './chatDiagramSchema'

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

/** Chat chart payload → yazdırılabilir SVG (Recharts ekranda kalır). */
export function chartToSvg(chart: ChatChartPayload): string {
  const series = (chart.series || []).filter((s) => (s.points || []).length >= 2)
  if (!series.length) return ''
  const w = 680
  const h = 240
  const pad = { l: 48, r: 12, t: 28, b: 36 }
  const iw = w - pad.l - pad.r
  const ih = h - pad.t - pad.b
  const stamps = new Set<string>()
  series.forEach((s) => s.points.forEach((p) => stamps.add(p.t)))
  const times = Array.from(stamps).sort()
  const first = new Date(times[0]).getTime()
  const last = new Date(times[times.length - 1]).getTime()
  const span = Math.max(1, last - first)
  let minV = Infinity
  let maxV = -Infinity
  series.forEach((s) => s.points.forEach((p) => {
    if (Number.isFinite(p.v)) {
      minV = Math.min(minV, p.v)
      maxV = Math.max(maxV, p.v)
    }
  }))
  if (!Number.isFinite(minV)) return ''
  if (chart.unit === '%' && minV >= 0 && maxV <= 100) {
    minV = 0
    maxV = 100
  } else if (maxV === minV) {
    maxV = minV + 1
    minV = Math.max(0, minV - 1)
  }
  const xOf = (t: string) => pad.l + ((new Date(t).getTime() - first) / span) * iw
  const yOf = (v: number) => pad.t + (1 - (v - minV) / (maxV - minV)) * ih
  const paths = series.map((s, i) => {
    const pts = [...s.points].sort((a, b) => a.t.localeCompare(b.t))
    const d = pts.map((p, idx) => `${idx ? 'L' : 'M'}${xOf(p.t).toFixed(1)},${yOf(p.v).toFixed(1)}`).join(' ')
    const color = CHART_COLORS[i % CHART_COLORS.length]
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/>`
  }).join('')
  const ticks = [0, 0.5, 1].map((f) => {
    const t = new Date(first + span * f).toISOString()
    const x = pad.l + f * iw
    return `<text x="${x}" y="${h - 10}" text-anchor="middle" font-size="10" fill="#475569">${esc(formatTick(t, span))}</text>`
  }).join('')
  const yTicks = [maxV, (maxV + minV) / 2, minV].map((v, i) => {
    const y = pad.t + (i / 2) * ih
    return `<text x="${pad.l - 6}" y="${y + 3}" text-anchor="end" font-size="10" fill="#475569">${esc(formatVal(v, chart.unit))}</text>
      <line x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}" stroke="#e2e8f0"/>`
  }).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:100%;height:auto;background:#fff">
    <text x="${pad.l}" y="16" font-size="12" font-weight="600" fill="#0f172a">${esc(chart.title)}</text>
    ${yTicks}${paths}${ticks}
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
