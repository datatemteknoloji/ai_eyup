import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const state = { demoActive: false }
vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: state.demoActive, hasRealBackup: false, demoActive: state.demoActive, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string) => k }))

import DemoBanner from '../components/DemoBanner'

const layoutSrc = Object.values(
  import.meta.glob('../components/Layout.tsx', { query: '?raw', import: 'default', eager: true }),
)[0] as string

describe('F.0 DEMO banner', () => {
  beforeEach(() => { state.demoActive = false })

  it('is not rendered when demo is inactive (production default)', () => {
    render(<DemoBanner />)
    expect(screen.queryByTestId('demo-global-banner')).toBeNull()
  })

  it('is rendered with the global demo message when demo is active', () => {
    state.demoActive = true
    render(<DemoBanner />)
    const el = screen.getByTestId('demo-global-banner')
    expect(el.textContent).toContain('demo_global_banner')
    expect(el.getAttribute('role')).toBe('alert')
  })

  it('is mounted in Layout so it shows on every screen', () => {
    expect(layoutSrc).toContain("import DemoBanner from './DemoBanner'")
    expect(layoutSrc).toContain('<DemoBanner />')
  })
})
