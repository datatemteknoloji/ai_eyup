import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { AnswerFooter, AutomicMarkdown, ConfidenceBadge, normalizeAnswer } from '../pages/automation/AnswerView'

describe('normalizeAnswer', () => {
  it('removes the ainew-meta block', () => {
    expect(normalizeAnswer('**Sonuç.**\n\nMetin\n\n```ainew-meta\n{"a":1}\n```')).toBe('**Sonuç.**\n\nMetin')
  })
  it('unwraps a whole-answer ```markdown fence so it is not rendered as one code block', () => {
    const t = '```markdown\n**Sonuç.**\n\nMetin\n```\n```ainew-meta\n{}\n```'
    expect(normalizeAnswer(t)).toBe('**Sonuç.**\n\nMetin')
  })
  it('hides half-typed fences while streaming', () => {
    expect(normalizeAnswer('**Sonuç.**\n\nMetin\n``', true)).toBe('**Sonuç.**\n\nMetin')
    expect(normalizeAnswer('**Sonuç.**\n\nMetin\n```ain', true)).toBe('**Sonuç.**\n\nMetin')
    expect(normalizeAnswer('```markdown\n**Sonuç.**', true)).toBe('**Sonuç.**')
  })
  it('keeps real code blocks', () => {
    expect(normalizeAnswer('Komut:\n\n```sql\nSELECT 1\n```')).toContain('```sql')
  })
})

describe('AutomicMarkdown', () => {
  it('renders headings as quiet labels, lists as blocks, no raw code area', () => {
    const { container } = render(
      <AutomicMarkdown severity="warning" text={'**44 hatalı job.**\n\n### Detay\n\n- `JOBS.A` hata\n- `JOBS.B` hata\n'} />,
    )
    expect(container.querySelector('.automic-md')?.getAttribute('data-severity')).toBe('warning')
    expect(container.querySelector('h3')).toBeNull()
    expect(container.querySelector('h4.am-h')?.textContent).toBe('Detay')
    expect(container.querySelectorAll('li.am-li')).toHaveLength(2)
    expect(container.querySelector('pre')).toBeNull()
    expect(container.querySelector('p.am-p strong.am-strong')?.textContent).toBe('44 hatalı job.')
  })
})

describe('AnswerFooter', () => {
  const scope = {
    system: 'DEV-FAKE', clients: [100, 200], time_from: '2026-10-09T10:00:00+00:00', time_to: '2026-10-09T16:00:00+00:00',
    data_source: 'db', record_count: 1234, source_lag_sec: 600, partial: true, tools: ['automic_search_executions'],
  }
  it('shows a one-line summary and expands details on click', () => {
    render(<AnswerFooter scope={scope} confidence="high" />)
    expect(screen.getByText(/DEV-FAKE/)).toBeTruthy()
    expect(screen.getByText(/Modül DB/)).toBeTruthy()
    expect(screen.queryByText('Kaynak gecikmesi')).toBeNull()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Kaynak gecikmesi')).toBeTruthy()
    expect(screen.getByText('10 dk')).toBeTruthy()
    expect(screen.getByText('Çalışma arama')).toBeTruthy()
    expect(screen.getByText(/Sonuç kısmi/)).toBeTruthy()
  })
  it('renders nothing without data', () => {
    const { container } = render(<AnswerFooter scope={{}} />)
    expect(container.firstChild).toBeNull()
  })
  it('confidence badge', () => {
    render(<ConfidenceBadge value="low" />)
    expect(screen.getByText(/Güven: Düşük/)).toBeTruthy()
  })
})
