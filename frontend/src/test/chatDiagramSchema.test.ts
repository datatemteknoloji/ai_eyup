import { describe, it, expect } from 'vitest'
import { parseArchitectureDiagram } from '../utils/chatDiagramSchema'

describe('parseArchitectureDiagram', () => {
  it('accepts layered topology JSON', () => {
    const d = parseArchitectureDiagram(JSON.stringify({
      title: 'vSphere',
      layers: [{ id: 'mgmt', label: 'Yönetim' }],
      nodes: [
        { id: 'vc', label: 'Office VC', kind: 'vcenter', layer: 'mgmt' },
        { id: 'h1', label: 'esxi01', kind: 'esxi' },
      ],
      edges: [{ from: 'vc', to: 'h1', label: 'SOAP' }],
    }))
    expect(d?.title).toBe('vSphere')
    expect(d?.nodes).toHaveLength(2)
    expect(d?.nodes[0].kind).toBe('vcenter')
    expect(d?.edges[0].from).toBe('vc')
  })

  it('rejects empty or invalid', () => {
    expect(parseArchitectureDiagram('not json')).toBeNull()
    expect(parseArchitectureDiagram('{"nodes":[]}')).toBeNull()
    expect(parseArchitectureDiagram('{"nodes":[{"id":"a","label":"A","kind":"nope"}]}')?.nodes[0].kind).toBe('unknown')
  })
})
