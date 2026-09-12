/** Bozuk / çitsiz Mermaid → React Flow şeması. Çizim asla ham koda düşmesin. */
import type { ArchitectureDiagram, DiagramKind, DiagramNode } from './chatDiagramSchema'

const KIND_HINTS: [RegExp, DiagramKind][] = [
  [/vcenter|vsphere|vcsa/i, 'vcenter'],
  [/esxi|esx\b|hypervisor/i, 'esxi'],
  [/kubevirt|openshift.?virt/i, 'kubevirt'],
  [/openshift|ocp\b|k8s|kubernetes/i, 'ocp'],
  [/datastore|vmdk|storage|ceph|nfs/i, 'datastore'],
  [/cluster|drs|ha\b/i, 'cluster'],
  [/\bvm\b|sanal|virtual.?machine/i, 'vm'],
  [/windows|winrm/i, 'windows'],
  [/linux|rhel|ssh|node.?exporter/i, 'linux'],
  [/postgres|timescale|database|\bdb\b/i, 'db'],
  [/network|vlan|nic|switch/i, 'network'],
  [/user|kullanıcı|operator/i, 'user'],
  [/app|uygulama|backend|frontend/i, 'app'],
]

export function looksLikeMermaid(src: string): boolean {
  const t = (src || '').trim()
  if (t.length < 12) return false
  if (/^(flowchart|graph|sequenceDiagram|erDiagram|stateDiagram)/m.test(t)) return true
  return /-->|---|-\.-/.test(t) && /\bsubgraph\b|\[.+\]/.test(t)
}

function inferKind(label: string): DiagramKind {
  for (const [re, kind] of KIND_HINTS) {
    if (re.test(label)) return kind
  }
  return 'unknown'
}

function cleanId(raw: string): string {
  return raw.replace(/[^a-zA-Z0-9_]/g, '_').slice(0, 40) || 'n'
}

function stripQuotes(s: string): string {
  return s.replace(/^["'`]+|["'`]+$/g, '').replace(/\*\*/g, '').trim()
}

/** id[label] / id(label) / id{label} / id((label)) */
const NODE_RE = /([A-Za-z][\w-]*)\s*(?:\[([^\]]+)\]|\(\(([^)]+)\)\)|\(([^)]+)\)|\{([^}]+)\}|>\s*([^<\n]+)<)/g
const EDGE_RE = /([A-Za-z][\w-]*)\s*(?:-->|---|-\.->|==>|-.->)\s*(?:\|([^|]+)\|)?\s*([A-Za-z][\w-]*)/g
const SUBGRAPH_RE = /subgraph\s+([^\n[]+)(?:\[([^\]]+)\])?/gi

export function mermaidToArchitectureDiagram(src: string): ArchitectureDiagram | null {
  const text = (src || '').replace(/\r\n/g, '\n')
  if (!looksLikeMermaid(text)) return null

  const nodes = new Map<string, DiagramNode>()
  const layers: { id: string; label: string }[] = []
  let currentLayer: string | undefined
  const edges: { from: string; to: string; label?: string }[] = []

  const lines = text.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (/^subgraph\s+/i.test(trimmed)) {
      const m = /^subgraph\s+(.+)$/i.exec(trimmed)
      const raw = stripQuotes((m?.[1] || 'katman').replace(/\[.*$/, '').trim())
      const id = cleanId(raw)
      currentLayer = id
      if (!layers.some((l) => l.id === id)) layers.push({ id, label: raw.slice(0, 40) })
      continue
    }
    if (/^end\b/i.test(trimmed)) {
      currentLayer = undefined
      continue
    }
    if (/^(flowchart|graph|%%)/i.test(trimmed)) continue

    NODE_RE.lastIndex = 0
    let nm: RegExpExecArray | null
    const lineCopy = trimmed
    while ((nm = NODE_RE.exec(lineCopy))) {
      const id = cleanId(nm[1])
      const label = stripQuotes(nm[2] || nm[3] || nm[4] || nm[5] || nm[6] || nm[1]).slice(0, 48)
      if (!nodes.has(id)) {
        nodes.set(id, { id, label, kind: inferKind(label), layer: currentLayer })
      } else if (label !== id) {
        const prev = nodes.get(id)!
        nodes.set(id, { ...prev, label, kind: inferKind(label) || prev.kind })
      }
    }

    EDGE_RE.lastIndex = 0
    let em: RegExpExecArray | null
    while ((em = EDGE_RE.exec(lineCopy))) {
      const from = cleanId(em[1])
      const to = cleanId(em[3])
      if (from === to) continue
      if (!nodes.has(from)) nodes.set(from, { id: from, label: em[1], kind: inferKind(em[1]), layer: currentLayer })
      if (!nodes.has(to)) nodes.set(to, { id: to, label: em[3], kind: inferKind(em[3]), layer: currentLayer })
      edges.push({ from, to, label: em[2] ? stripQuotes(em[2]).slice(0, 32) : undefined })
    }
  }

  // subgraph başlıkları (çok satırlı)
  SUBGRAPH_RE.lastIndex = 0
  let sm: RegExpExecArray | null
  while ((sm = SUBGRAPH_RE.exec(text))) {
    const label = stripQuotes(sm[2] || sm[1] || '')
    const id = cleanId(label)
    if (id && !layers.some((l) => l.id === id)) layers.push({ id, label: label.slice(0, 40) })
  }

  if (nodes.size < 2 && edges.length === 0) return null
  if (nodes.size < 1) return null
  return {
    title: undefined,
    nodes: Array.from(nodes.values()).slice(0, 24),
    edges: edges.slice(0, 40),
    layers: layers.slice(0, 8),
  }
}
