import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from '../components/ErrorBoundary'

const ThrowError = ({ message }: { message: string }) => {
  throw new Error(message)
}

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <div>Safe content</div>
      </ErrorBoundary>
    )
    expect(screen.getByText('Safe content')).toBeDefined()
  })

  it('renders fallback UI when a child component throws', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <ThrowError message="Test crash" />
      </ErrorBoundary>
    )
    expect(screen.getByText('Beklenmeyen Bir Hata Oluştu')).toBeDefined()
    expect(screen.getByRole('button', { name: /Sayfayı Yenile/i })).toBeDefined()
    consoleError.mockRestore()
  })

  it('renders custom fallback when provided', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary fallback={<div>Custom fallback</div>}>
        <ThrowError message="crash" />
      </ErrorBoundary>
    )
    expect(screen.getByText('Custom fallback')).toBeDefined()
    consoleError.mockRestore()
  })
})
