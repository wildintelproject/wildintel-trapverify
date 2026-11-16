import { describe, expect, it } from 'vitest'
import { wholeNumber } from './integer'

describe('wholeNumber', () => {
  it('cuts decimals off', () => {
    expect(wholeNumber('1.5', 1)).toBe(1)
    expect(wholeNumber('90.9', 10)).toBe(90)
    expect(wholeNumber(2.7, 1)).toBe(2)
  })
  it('never goes below the minimum', () => {
    expect(wholeNumber('0', 1)).toBe(1)
    expect(wholeNumber('-5', 10)).toBe(10)
    expect(wholeNumber('3', 10)).toBe(10)
  })
  it('uses the fallback for an empty or unreadable box', () => {
    expect(wholeNumber('', 10, 120)).toBe(120)
    expect(wholeNumber('abc', 1, 60)).toBe(60)
    expect(wholeNumber('', 1)).toBe(1)
  })
  it('keeps whole numbers as they are', () => {
    expect(wholeNumber('60', 1)).toBe(60)
    expect(wholeNumber('120', 10, 120)).toBe(120)
  })
})
