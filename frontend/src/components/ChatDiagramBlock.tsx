/**
 * Tek giriş: JSON → React Flow; Mermaid → çiz, olmazsa React Flow kurtar.
 * Ham kod kullanıcıya asıl sonuç olarak gösterilmez.
 */
import { ChatArchitectureDiagram } from './ChatArchitectureDiagram'
import { ChatMermaid } from './ChatMermaid'
import { parseArchitectureDiagram } from '../utils/chatDiagramSchema'
import { looksLikeMermaid, mermaidToArchitectureDiagram } from '../utils/mermaidToDiagram'

export function ChatDiagramBlock({ source, preferMermaid = false }: { source: string; preferMermaid?: boolean }) {
  const json = parseArchitectureDiagram(source.trim())
  if (json) return <ChatArchitectureDiagram diagram={json} />

  const recovered = mermaidToArchitectureDiagram(source)
  if (recovered && recovered.nodes.length >= 2) {
    if (preferMermaid) {
      return <ChatMermaid source={source} fallback={recovered} />
    }
    return <ChatArchitectureDiagram diagram={recovered} />
  }
  if (looksLikeMermaid(source) || preferMermaid) {
    return <ChatMermaid source={source} fallback={recovered} />
  }
  return null
}
