import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../theme/ThemeProvider', () => ({ useTheme: () => ({ theme: 'dark' }) }))
// jsdom'da ölçü yok; ResponsiveContainer'ı sabit boyutlu kapsayıcıya indirge.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactElement }) => (
      <div data-testid="plot" style={{ width: 600, height: 300 }}>{children}</div>
    ),
  }
})

import ChatMetricChart, { type ChatChartPayload } from '../components/ChatMetricChart'

const chart: ChatChartPayload = {
  type: 'timeseries',
  title: 'CPU Kullanımı — Son 6 saat (2 nesne)',
  unit: '%',
  series: [
    { metric_name: 'a:cpu', label: 'vm-a — CPU %', points: [{ t: '2026-10-27T10:00:00Z', v: 10 }, { t: '2026-10-27T11:00:00Z', v: 30 }] },
    { metric_name: 'b:cpu', label: 'vm-b — CPU %', points: [{ t: '2026-10-27T10:00:00Z', v: 5 }, { t: '2026-10-27T11:00:00Z', v: 8 }] },
  ],
}

describe('ChatMetricChart büyütme', () => {
  it('Büyüt düğmesi modal açar; kapat düğmesi, Esc ve dışa tıklama kapatır', () => {
    render(<ChatMetricChart chart={chart} chartId="t1" />)
    expect(screen.queryByTestId('chat-chart-modal')).toBeNull()

    fireEvent.click(screen.getByTestId('chat-chart-expand'))
    const modal = screen.getByTestId('chat-chart-modal')
    expect(modal).toBeInTheDocument()
    expect(modal).toHaveAttribute('aria-modal', 'true')
    // başlık hem kartta hem modalda
    expect(screen.getAllByText(chart.title).length).toBe(2)

    fireEvent.click(screen.getByTestId('chat-chart-close'))
    expect(screen.queryByTestId('chat-chart-modal')).toBeNull()

    fireEvent.click(screen.getByTestId('chat-chart-expand'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByTestId('chat-chart-modal')).toBeNull()

    fireEvent.click(screen.getByTestId('chat-chart-expand'))
    fireEvent.click(screen.getByTestId('chat-chart-modal'))
    expect(screen.queryByTestId('chat-chart-modal')).toBeNull()
  })

  it('modal içi tıklama modalı kapatmaz', () => {
    render(<ChatMetricChart chart={chart} chartId="t2" />)
    fireEvent.click(screen.getByTestId('chat-chart-expand'))
    fireEvent.click(screen.getAllByText(chart.title)[1])
    expect(screen.getByTestId('chat-chart-modal')).toBeInTheDocument()
  })

  it('veri yoksa büyüt düğmesi çıkmaz', () => {
    render(<ChatMetricChart chart={{ ...chart, series: [] }} chartId="t3" />)
    expect(screen.queryByTestId('chat-chart-expand')).toBeNull()
  })
})
