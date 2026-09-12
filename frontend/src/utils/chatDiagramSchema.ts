/** /diagram yapı sözleşmesi — LLM JSON → React Flow. */

export type DiagramKind =
  | 'vcenter'
  | 'esxi'
  | 'vm'
  | 'datastore'
  | 'cluster'
  | 'ocp'
  | 'kubevirt'
  | 'linux'
  | 'windows'
  | 'db'
  | 'network'
  | 'user'
  | 'app'
  | 'storage'
  | 'unknown'

export interface DiagramNode {
  id: string
  label: string
  kind: DiagramKind
  layer?: string
}

export interface DiagramEdge {
  from: string
  to: string
  label?: string
}

export interface DiagramLayer {
  id: string
  label: string
}

export interface ArchitectureDiagram {
  title?: string
  nodes: DiagramNode[]
  edges: DiagramEdge[]
  layers: DiagramLayer[]
}

const KINDS = new Set<DiagramKind>([
  'vcenter', 'esxi', 'vm', 'datastore', 'cluster', 'ocp', 'kubevirt',
  'linux', 'windows', 'db', 'network', 'user', 'app', 'storage', 'unknown',
])

function slug(raw: string, i: number): string {
  const s = String(raw || '').replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 40)
  return s || `n${i}`
}

export function parseArchitectureDiagram(raw: string): ArchitectureDiagram | null {
  const text = (raw || '').trim()
  if (!text.startsWith('{')) return null
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const obj = data as Record<string, unknown>
  const nodesIn = Array.isArray(obj.nodes) ? obj.nodes : []
  const edgesIn = Array.isArray(obj.edges) ? obj.edges : []
  const layersIn = Array.isArray(obj.layers) ? obj.layers : []
  if (!nodesIn.length) return null

  const nodes: DiagramNode[] = []
  const seen = new Set<string>()
  nodesIn.slice(0, 24).forEach((n, i) => {
    if (!n || typeof n !== 'object') return
    const rec = n as Record<string, unknown>
    const id = slug(String(rec.id ?? `n${i}`), i)
    if (seen.has(id)) return
    seen.add(id)
    const kindRaw = String(rec.kind || 'unknown').toLowerCase() as DiagramKind
    nodes.push({
      id,
      label: String(rec.label || id).slice(0, 48),
      kind: KINDS.has(kindRaw) ? kindRaw : 'unknown',
      layer: rec.layer != null ? String(rec.layer).slice(0, 32) : undefined,
    })
  })
  if (!nodes.length) return null
  const ids = new Set(nodes.map((n) => n.id))

  const edges: DiagramEdge[] = []
  edgesIn.slice(0, 40).forEach((e) => {
    if (!e || typeof e !== 'object') return
    const rec = e as Record<string, unknown>
    const from = slug(String(rec.from ?? rec.source ?? ''), 0)
    const to = slug(String(rec.to ?? rec.target ?? ''), 1)
    if (!ids.has(from) || !ids.has(to) || from === to) return
    edges.push({
      from,
      to,
      label: rec.label != null ? String(rec.label).slice(0, 32) : undefined,
    })
  })

  const layers: DiagramLayer[] = []
  layersIn.slice(0, 8).forEach((l, i) => {
    if (!l || typeof l !== 'object') return
    const rec = l as Record<string, unknown>
    const id = slug(String(rec.id ?? `l${i}`), i)
    layers.push({ id, label: String(rec.label || id).slice(0, 40) })
  })

  const title = obj.title != null ? String(obj.title).slice(0, 80) : undefined
  return { title, nodes, edges, layers }
}
