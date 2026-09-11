import { describe, it, expect } from 'vitest'
import mermaid from 'mermaid'
import { sanitizeMermaidSource, hardenMermaidSvg } from '../components/ChatMermaid'

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'base',
  flowchart: { htmlLabels: true, useMaxWidth: false },
  themeVariables: { fontSize: '18px', primaryTextColor: '#0f172a', primaryColor: '#f8fafc' },
})

describe('sanitizeMermaidSource', () => {
  it('strips markdown bold and backticks from labels', () => {
    const src = 'flowchart TD\n  A[**vCenter Bağlantısı**] --> B[`ESXi Host`]'
    const out = sanitizeMermaidSource(src)
    expect(out).not.toContain('**')
    expect(out).not.toContain('`')
    expect(out).toContain('vCenter Bağlantısı')
    expect(out).toContain('ESXi Host')
  })

  it('quotes path-like node labels that break Mermaid shape syntax', () => {
    const src = [
      'flowchart TD',
      '    A[Root /]',
      '    A --> B[/boot]',
      '    A --> C[/var]',
      '    C --> K[/var/log]',
    ].join('\n')
    const out = sanitizeMermaidSource(src)
    expect(out).toContain('A["Root /"]')
    expect(out).toContain('B["/boot"]')
    expect(out).toContain('C["/var"]')
    expect(out).toContain('K["/var/log"]')
    expect(out).not.toMatch(/B\[\/boot\]/)
  })

  it('quotes Windows backslash paths in node labels', () => {
    const out = sanitizeMermaidSource('flowchart TD\n  A[C:\\Windows\\System32] --> B[OK]')
    expect(out).toContain('A["C:\\Windows\\System32"]')
  })

  it('parses sanitized linux filesystem diagram', async () => {
    const raw = [
      'flowchart TD',
      '    A[Root /]',
      '    A --> B[/boot]',
      '    A --> C[/var]',
      '    A --> D[/home]',
      '    C --> K[/var/log]',
    ].join('\n')
    const out = sanitizeMermaidSource(raw)
    await expect(mermaid.parse(out)).resolves.toBeTruthy()
  })
})

describe('hardenMermaidSvg', () => {
  it('forces dark text fill on svg text nodes', () => {
    const raw =
      '<svg xmlns="http://www.w3.org/2000/svg"><text fill="#111827">X</text><g class="node"><rect fill="#0f172a"/></g></svg>'
    const out = hardenMermaidSvg(raw)
    expect(out).toContain('#0f172a')
    expect(out).toContain('#f8fafc')
    expect(out).toContain('#2563eb')
  })
})

describe('mermaid fences used by chat diagrams', () => {
  it('parses a sequence diagram', async () => {
    const r = await mermaid.parse(
      'sequenceDiagram\n  participant C as Client\n  participant A as API\n  C->>A: POST /unified-chat/stream\n  A-->>C: SSE token',
    )
    expect(r).toBeTruthy()
  })

  it('parses a flowchart topology', async () => {
    const r = await mermaid.parse(
      'flowchart TB\n  VC[vCenter] --> H1[esx-01]\n  VC --> H2[esx-02]\n  H1 --> VM1[web01]\n  H2 --> VM2[db01]',
    )
    expect(r).toBeTruthy()
  })

  it('rejects broken syntax', async () => {
    await expect(mermaid.parse('flowchart TB\n  A-->')).rejects.toBeTruthy()
  })
})
