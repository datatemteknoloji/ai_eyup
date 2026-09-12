import { useEffect, useId, useState } from 'react'
import { useT } from '../i18n/LocaleProvider'
import { ChatArchitectureDiagram } from './ChatArchitectureDiagram'
import type { ArchitectureDiagram } from '../utils/chatDiagramSchema'

type Phase = 'pending' | 'ok' | 'error'
type MermaidMod = typeof import('mermaid')

let mermaidLoader: Promise<MermaidMod> | null = null

const BOX_FILL = '#f8fafc'
const BOX_STROKE = '#2563eb'
const TEXT_FILL = '#0f172a'
const LINE_STROKE = '#475569'

/** LLM bazen **bold** / `code` bırakır; Mermaid bunları literal basar.
 * `[/boot]` gibi path etiketleri paralelkenar sözdizimine çarpar → tırnakla.
 */
export function sanitizeMermaidSource(src: string): string {
  let out = (src || '')
    .replace(/\*\*/g, '')
    .replace(/__/g, '')
    .replace(/`+/g, '')
    .replace(/\r\n/g, '\n')
    .replace(/\n$/, '')

  // [/boot] veya [C:\Windows] — şekil sözdizimine çarpan path etiketleri → ["..."]
  out = out.replace(/\[(?!")([^\]\n]*[\\/][^\]\n]*)\]/g, (_m, inner: string) => {
    const text = String(inner).trim()
    if (!text) return '["/"]'
    return `["${text.replace(/"/g, "'")}"]`
  })
  return out
}

/**
 * Mermaid tema/CSS bazen foreignObject veya inline fill ile koyu-üzerine-koyu bırakır.
 * Render sonrası SVG'yi açık kart + koyu yazıya zorla.
 */
export function hardenMermaidSvg(svg: string): string {
  if (typeof DOMParser === 'undefined' || !svg) return svg
  try {
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
    const root = doc.documentElement
    if (!root || root.querySelector('parsererror')) return svg

    root.querySelectorAll('text, tspan').forEach((el) => {
      el.setAttribute('fill', TEXT_FILL)
      const st = el.getAttribute('style') || ''
      el.setAttribute(
        'style',
        `${st.replace(/fill\s*:[^;]+;?/gi, '').replace(/color\s*:[^;]+;?/gi, '')};fill:${TEXT_FILL};color:${TEXT_FILL}`,
      )
    })

    root.querySelectorAll('foreignObject, foreignObject *').forEach((el) => {
      const st = (el as Element).getAttribute('style') || ''
      ;(el as Element).setAttribute(
        'style',
        `${st.replace(/color\s*:[^;]+;?/gi, '')};color:${TEXT_FILL} !important;fill:${TEXT_FILL}`,
      )
    })

    root.querySelectorAll('.node rect, .node polygon, .node circle, .basic.label-container').forEach((el) => {
      el.setAttribute('fill', BOX_FILL)
      el.setAttribute('stroke', BOX_STROKE)
      el.setAttribute('stroke-width', '1.5')
    })

    root.querySelectorAll('.actor > rect, .actor-man > circle, rect.actor').forEach((el) => {
      el.setAttribute('fill', BOX_FILL)
      el.setAttribute('stroke', BOX_STROKE)
    })

    root.querySelectorAll('.flowchart-link, .edgePath path, path.transition, line').forEach((el) => {
      const cls = el.getAttribute('class') || ''
      if (cls.includes('actor-line')) return
      el.setAttribute('stroke', LINE_STROKE)
      if (!el.getAttribute('fill') || el.getAttribute('fill') === 'none') {
        /* keep */
      }
    })

    root.querySelectorAll('marker path').forEach((el) => {
      el.setAttribute('fill', LINE_STROKE)
      el.setAttribute('stroke', LINE_STROKE)
    })

    // Okunabilir boyut: shrink etme; yatay kaydır.
    root.removeAttribute('style')
    root.setAttribute('width', root.getAttribute('viewBox')?.split(/\s+/)[2] || root.getAttribute('width') || '100%')
    if (!root.getAttribute('height') && root.getAttribute('viewBox')) {
      const parts = root.getAttribute('viewBox')!.split(/\s+/)
      if (parts[3]) root.setAttribute('height', parts[3])
    }

    return new XMLSerializer().serializeToString(root)
  } catch {
    return svg
  }
}

function loadMermaid(): Promise<MermaidMod> {
  if (!mermaidLoader) {
    mermaidLoader = import('mermaid').then((mod) => {
      // Açık kart + koyu yazı — sohbet balonunda her zaman okunur.
      mod.default.initialize({
        startOnLoad: false,
        theme: 'base',
        securityLevel: 'strict',
        fontFamily: 'DM Sans, ui-sans-serif, system-ui, sans-serif',
        flowchart: {
          htmlLabels: true,
          curve: 'basis',
          padding: 16,
          nodeSpacing: 40,
          rankSpacing: 50,
          useMaxWidth: false,
        },
        sequence: {
          actorMargin: 48,
          messageMargin: 36,
          useMaxWidth: false,
          mirrorActors: false,
        },
        themeVariables: {
          darkMode: false,
          background: '#ffffff',
          fontFamily: 'DM Sans, ui-sans-serif, system-ui, sans-serif',
          fontSize: '18px',
          primaryColor: BOX_FILL,
          primaryTextColor: TEXT_FILL,
          primaryBorderColor: BOX_STROKE,
          secondaryColor: '#e2e8f0',
          secondaryTextColor: TEXT_FILL,
          tertiaryColor: '#f1f5f9',
          tertiaryTextColor: TEXT_FILL,
          lineColor: LINE_STROKE,
          textColor: TEXT_FILL,
          mainBkg: BOX_FILL,
          nodeBkg: BOX_FILL,
          nodeBorder: BOX_STROKE,
          nodeTextColor: TEXT_FILL,
          clusterBkg: '#e2e8f0',
          clusterBorder: '#64748b',
          titleColor: TEXT_FILL,
          edgeLabelBackground: '#ffffff',
          actorBkg: BOX_FILL,
          actorBorder: BOX_STROKE,
          actorTextColor: TEXT_FILL,
          actorLineColor: LINE_STROKE,
          signalColor: LINE_STROKE,
          signalTextColor: TEXT_FILL,
          labelBoxBkgColor: BOX_FILL,
          labelBoxBorderColor: BOX_STROKE,
          labelTextColor: TEXT_FILL,
          loopTextColor: TEXT_FILL,
          noteBkgColor: '#fef9c3',
          noteTextColor: TEXT_FILL,
          noteBorderColor: '#ca8a04',
          activationBkgColor: '#dbeafe',
          activationBorderColor: BOX_STROKE,
          sequenceNumberColor: '#ffffff',
        },
      })
      return mod
    })
  }
  return mermaidLoader
}

function looksComplete(src: string): boolean {
  const t = src.trim()
  if (t.length < 24) return false
  const typed = /^(flowchart|graph|sequenceDiagram|erDiagram|stateDiagram(?:-v2)?|gantt|classDiagram|journey)\b/m.test(t)
  return typed && t.split('\n').length >= 3
}

function safeDomId(raw: string): string {
  return raw.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 40)
}

export function ChatMermaid({
  source,
  fallback = null,
}: {
  source: string
  fallback?: ArchitectureDiagram | null
}) {
  const t = useT()
  const rid = safeDomId(useId())
  const [phase, setPhase] = useState<Phase>('pending')
  const [svg, setSvg] = useState('')
  const trimmed = sanitizeMermaidSource(source)

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const { default: mermaid } = await loadMermaid()
        const id = `mmd_${rid}_${Math.random().toString(36).slice(2, 8)}`
        const { svg: out } = await mermaid.render(id, trimmed)
        if (!cancelled) {
          setSvg(hardenMermaidSvg(out))
          setPhase('ok')
        }
      } catch {
        if (!cancelled) {
          setSvg('')
          setPhase(looksComplete(trimmed) ? 'error' : 'pending')
        }
      }
    }, 350)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [trimmed, rid])

  if (phase === 'ok' && svg) {
    return (
      <div
        className="chat-mermaid my-3 max-w-full overflow-x-auto rounded-lg border border-slate-300 bg-white p-4 shadow-sm"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    )
  }

  if ((phase === 'error' || phase === 'pending') && fallback && fallback.nodes.length >= 2) {
    return <ChatArchitectureDiagram diagram={fallback} />
  }

  return (
    <div className="my-2">
      {phase === 'error' && (
        <p className="text-[11px] text-amber-200/90 mb-1">{t('chat_diagram_failed')}</p>
      )}
      <pre className="chat-md-pre bg-cyber-deep border border-white/[0.08] rounded-lg p-3 overflow-x-auto text-xs max-h-[min(50vh,28rem)] text-slate-200">
        <code className="language-mermaid">{trimmed}</code>
      </pre>
    </div>
  )
}
