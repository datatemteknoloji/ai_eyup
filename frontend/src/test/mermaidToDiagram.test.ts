import { describe, it, expect } from 'vitest'
import { looksLikeMermaid, mermaidToArchitectureDiagram } from '../utils/mermaidToDiagram'

const SAMPLE = `flowchart LR
  subgraph Platform
    A[OpenShift]
    B[vCenter]
    C[Linux]
  end
  A --> B
  B --> C
`

describe('mermaidToArchitectureDiagram', () => {
  it('recovers nodes and edges from typical LLM mermaid', () => {
    expect(looksLikeMermaid(SAMPLE)).toBe(true)
    const d = mermaidToArchitectureDiagram(SAMPLE)
    expect(d).toBeTruthy()
    expect(d!.nodes.length).toBeGreaterThanOrEqual(3)
    expect(d!.edges.length).toBeGreaterThanOrEqual(2)
    expect(d!.nodes.some((n) => n.kind === 'vcenter')).toBe(true)
    expect(d!.nodes.some((n) => n.kind === 'ocp' || n.kind === 'linux')).toBe(true)
  })

  it('rejects prose', () => {
    expect(looksLikeMermaid('Genel altyapı durumunuz nedir')).toBe(false)
    expect(mermaidToArchitectureDiagram('sadece metin')).toBeNull()
  })
})
