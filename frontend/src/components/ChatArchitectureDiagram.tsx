import { useMemo } from 'react'
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  Handle,
  Position,
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Server,
  Cpu,
  Box,
  HardDrive,
  Network,
  Database,
  Cloud,
  Layers,
  Monitor,
  User,
  AppWindow,
  Warehouse,
  HelpCircle,
} from 'lucide-react'
import type { ArchitectureDiagram, DiagramKind } from '../utils/chatDiagramSchema'

const KIND_META: Record<DiagramKind, { icon: typeof Server; accent: string; chip: string }> = {
  vcenter: { icon: Cloud, accent: '#0369a1', chip: 'vCenter' },
  esxi: { icon: Server, accent: '#4f46e5', chip: 'ESXi' },
  vm: { icon: Box, accent: '#047857', chip: 'VM' },
  datastore: { icon: HardDrive, accent: '#b45309', chip: 'Datastore' },
  cluster: { icon: Layers, accent: '#6d28d9', chip: 'Cluster' },
  ocp: { icon: Cloud, accent: '#be185d', chip: 'OpenShift' },
  kubevirt: { icon: Box, accent: '#9f1239', chip: 'KubeVirt' },
  linux: { icon: Cpu, accent: '#15803d', chip: 'Linux' },
  windows: { icon: Monitor, accent: '#1d4ed8', chip: 'Windows' },
  db: { icon: Database, accent: '#0e7490', chip: 'DB' },
  network: { icon: Network, accent: '#475569', chip: 'Ağ' },
  user: { icon: User, accent: '#334155', chip: 'Kullanıcı' },
  app: { icon: AppWindow, accent: '#7c3aed', chip: 'Uygulama' },
  storage: { icon: Warehouse, accent: '#c2410c', chip: 'Depolama' },
  unknown: { icon: HelpCircle, accent: '#475569', chip: '' },
}

function ArchNode({ data }: NodeProps) {
  const kind = (data as { kind?: DiagramKind }).kind || 'unknown'
  const label = String((data as { label?: string }).label || '')
  const meta = KIND_META[kind] || KIND_META.unknown
  const Icon = meta.icon
  return (
    <div
      className="min-w-[156px] max-w-[220px] rounded-xl border bg-white px-3 py-2.5 shadow-sm"
      style={{
        borderColor: `${meta.accent}55`,
        boxShadow: '0 1px 3px rgba(15,23,42,0.08), 0 0 0 1px rgba(15,23,42,0.04)',
      }}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-slate-400 !border-0" />
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `${meta.accent}18`, color: meta.accent }}
        >
          <Icon size={15} strokeWidth={2.2} />
        </span>
        <div className="min-w-0">
          {meta.chip ? (
            <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: meta.accent }}>
              {meta.chip}
            </p>
          ) : null}
          <p className="text-[13px] font-semibold leading-snug text-slate-800 break-words">{label}</p>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-slate-400 !border-0" />
    </div>
  )
}

const nodeTypes = { arch: ArchNode }

function layout(diagram: ArchitectureDiagram): { nodes: Node[]; edges: Edge[] } {
  const layerIds = diagram.layers.map((l) => l.id)
  const byLayer = new Map<string, typeof diagram.nodes>()
  const unlayered: typeof diagram.nodes = []
  for (const n of diagram.nodes) {
    const lid = n.layer && layerIds.includes(n.layer) ? n.layer : ''
    if (!lid) {
      unlayered.push(n)
      continue
    }
    const arr = byLayer.get(lid) || []
    arr.push(n)
    byLayer.set(lid, arr)
  }
  const rows: (typeof diagram.nodes)[] = []
  if (layerIds.length) {
    for (const id of layerIds) rows.push(byLayer.get(id) || [])
    if (unlayered.length) rows.push(unlayered)
  } else {
    const cols = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(diagram.nodes.length))))
    for (let i = 0; i < diagram.nodes.length; i += cols) {
      rows.push(diagram.nodes.slice(i, i + cols))
    }
  }

  const nodes: Node[] = []
  const xGap = 220
  const yGap = 130
  rows.forEach((row, ri) => {
    const offset = Math.max(0, (4 - row.length) * (xGap / 2) / 2)
    row.forEach((n, ci) => {
      nodes.push({
        id: n.id,
        type: 'arch',
        position: { x: offset + ci * xGap, y: 16 + ri * yGap },
        data: { label: n.label, kind: n.kind },
        draggable: true,
      })
    })
  })

  const edges: Edge[] = diagram.edges.map((e, i) => ({
    id: `e${i}_${e.from}_${e.to}`,
    source: e.from,
    target: e.to,
    label: e.label,
    type: 'smoothstep',
    animated: false,
    style: { stroke: '#64748b', strokeWidth: 1.5 },
    labelStyle: { fill: '#334155', fontSize: 10, fontWeight: 600 },
    labelBgStyle: { fill: '#f8fafc', fillOpacity: 0.95 },
  }))
  return { nodes, edges }
}

function DiagramCanvas({ diagram }: { diagram: ArchitectureDiagram }) {
  const { nodes, edges } = useMemo(() => layout(diagram), [diagram])
  return (
    <div className="chat-arch-flow h-[420px] w-full bg-slate-50" style={{ colorScheme: 'light', background: '#f8fafc' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.4}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        colorMode="light"
        style={{ background: '#f8fafc', colorScheme: 'light' }}
      >
        <Background color="#cbd5e1" gap={20} size={1} />
        <Controls showInteractive={false} className="!border-slate-200 !bg-white !shadow-sm" />
      </ReactFlow>
    </div>
  )
}

export function ChatArchitectureDiagram({ diagram }: { diagram: ArchitectureDiagram }) {
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
      {diagram.title ? (
        <div className="border-b border-slate-200 bg-white px-4 py-2.5">
          <p className="text-xs font-semibold tracking-wide text-slate-700">{diagram.title}</p>
        </div>
      ) : null}
      <ReactFlowProvider>
        <DiagramCanvas diagram={diagram} />
      </ReactFlowProvider>
    </div>
  )
}
