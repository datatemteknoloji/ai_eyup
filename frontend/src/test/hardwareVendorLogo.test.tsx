import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { VendorLogo } from '../components/hardware/hwUi'

describe('Donanım — üretici logosu', () => {
  it('dell → Dell logosu, hpe → HP logosu', () => {
    const { unmount } = render(<VendorLogo vendor="dell" />)
    expect(screen.getByTestId('hw-vendor-logo')).toHaveAttribute('data-vendor', 'dell')
    expect(screen.getByAltText('Dell')).toHaveAttribute('src', '/assets/logos/dell-logo.svg')
    unmount()
    render(<VendorLogo vendor="HPE" />)
    expect(screen.getByTestId('hw-vendor-logo')).toHaveAttribute('data-vendor', 'hpe')
    expect(screen.getByAltText('HPE')).toHaveAttribute('src', '/assets/logos/hp-logo.svg')
  })

  it('bilinmeyen / boş üretici → genel sunucu ikonu (img yok)', () => {
    const { unmount } = render(<VendorLogo vendor="supermicro" />)
    expect(screen.getByTestId('hw-vendor-logo')).toHaveAttribute('data-vendor', 'unknown')
    expect(screen.queryByRole('img')).toBeNull()
    unmount()
    render(<VendorLogo vendor={null} />)
    expect(screen.getByTestId('hw-vendor-logo')).toHaveAttribute('data-vendor', 'unknown')
  })
})
