import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

describe('useDebouncedValue', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('değeri 300 ms sonra yansıtır; ardışık yazımlarda yalnızca son değer geçer', () => {
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), { initialProps: { v: '' } })
    expect(result.current).toBe('')

    rerender({ v: 'b' })
    act(() => { vi.advanceTimersByTime(200) })
    rerender({ v: 'bo' })
    act(() => { vi.advanceTimersByTime(200) })
    expect(result.current).toBe('') // ilk yazımdan 400 ms geçti ama sayaç sıfırlandı

    act(() => { vi.advanceTimersByTime(100) })
    expect(result.current).toBe('bo')
  })
})
