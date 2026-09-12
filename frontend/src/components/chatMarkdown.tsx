/**
 * Ortak markdown tablo/kod stilleri — geniş rapor tablolarını balon içinde
 * yatay kaydırma ile tutar (taşmayı engeller). Tema değişkenleriyle light/dark okunur.
 * ```ainew-diagram``` → React Flow; ```mermaid``` → ChatMermaid (yedek).
 */
import { Children, isValidElement, type ReactNode } from 'react'
import type { Components } from 'react-markdown'
import { ChatDiagramBlock } from './ChatDiagramBlock'
import { looksLikeMermaid } from '../utils/mermaidToDiagram'
import { parseArchitectureDiagram } from '../utils/chatDiagramSchema'

function childText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(childText).join('')
  if (isValidElement(node)) {
    return childText((node.props as { children?: ReactNode }).children)
  }
  return ''
}

function fenceLangAndSource(children: ReactNode): { lang: string; source: string } | null {
  const text = childText(children).replace(/\n$/, '')
  if (!text.trim()) return null
  for (const child of Children.toArray(children)) {
    if (!isValidElement(child)) continue
    const cls = String((child.props as { className?: string }).className || '')
    const m = cls.match(/language-([a-z0-9-]+)/i)
    if (m) return { lang: m[1].toLowerCase(), source: text }
  }
  return { lang: '', source: text }
}

export const chatMarkdownComponents: Components = {
  table: ({ children }) => (
    <div className="chat-md-table-wrap my-3 max-w-full overflow-x-auto rounded-lg border border-slate-500/80 shadow-sm">
      <table className="w-full table-auto text-left text-sm border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/[0.05]">{children}</thead>,
  th: ({ children }) => (
    <th className="chat-md-th px-3 py-2 font-semibold text-slate-100 border-b border-slate-500 whitespace-nowrap">{children}</th>
  ),
  td: ({ children }) => (
    <td className="chat-md-td px-3 py-2 text-slate-200 border-b border-white/[0.06] align-top break-words">{children}</td>
  ),
  tr: ({ children, ...props }) => (
    <tr className="even:bg-white/[0.02] hover:bg-white/[0.04] transition-colors" {...props}>{children}</tr>
  ),
  code: ({ className, children }) =>
    className
      ? <code className={className}>{children}</code>
      : (
        <code className="chat-md-inline-code bg-white/[0.08] px-1.5 py-0.5 rounded text-xs text-amber-200">
          {children}
        </code>
      ),
  pre: ({ children }) => {
    const fence = fenceLangAndSource(children)
    if (fence) {
      const lang = fence.lang
      const isJsonFence = lang === 'ainew-diagram' || lang === 'diagram-json' || lang === 'json'
      if (isJsonFence && parseArchitectureDiagram(fence.source)) {
        return <ChatDiagramBlock source={fence.source} />
      }
      if (lang === 'mermaid' || looksLikeMermaid(fence.source)) {
        return <ChatDiagramBlock source={fence.source} preferMermaid={lang === 'mermaid'} />
      }
    }
    return (
      <pre className="chat-md-pre bg-cyber-deep border border-white/[0.08] rounded-lg p-3 overflow-x-auto text-xs my-2 max-h-[min(50vh,28rem)] text-slate-200">
        {children}
      </pre>
    )
  },
}

/** Mesaj balonu: flex içinde daralabilsin, taşan içerik balonu şişirmesin */
export const chatBubbleShell =
  'min-w-0 w-full max-w-full overflow-hidden rounded-3xl px-5 py-4 shadow-lg'

export const chatResponseBody =
  'chat-response-content min-w-0 max-w-none overflow-x-hidden text-sm leading-relaxed prose prose-invert prose-sm prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5'
