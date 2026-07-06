import { describe, expect, it } from 'vitest'
import { formatP, formatPsi } from './occupancy'

describe('formatPsi', () => {
  it('formats psi with its 95% confidence interval', () => {
    expect(formatPsi(0.6234, 0.512, 0.7183, false)).toBe('0.623 [0.512, 0.718]')
  })

  it('falls back to "?" for a missing CI bound', () => {
    expect(formatPsi(0.5, null, 0.9, false)).toBe('0.500 [?, 0.900]')
  })

  it('renders a dash for degenerate estimates', () => {
    expect(formatPsi(0.999, 0.9, 1.0, true)).toBe('—')
  })

  it('renders a dash when psi itself is null', () => {
    expect(formatPsi(null, null, null, false)).toBe('—')
  })
})

describe('formatP', () => {
  it('formats the detection probability to 3 decimals', () => {
    expect(formatP(0.4567)).toBe('0.457')
  })

  it('renders a dash when p is null', () => {
    expect(formatP(null)).toBe('—')
  })
})
