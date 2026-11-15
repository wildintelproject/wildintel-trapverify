import { describe, expect, it } from 'vitest'
import { anyCutoff, cleanSpeciesCutoffs, effectiveMinScore } from './minScore'

describe('effectiveMinScore', () => {
  it('uses the species value when it has one', () => {
    expect(effectiveMinScore(0.5, { 'Vulpes vulpes': 0.8 }, 'Vulpes vulpes')).toBe(0.8)
  })
  it('uses the general value for the others and for sessions without overrides', () => {
    expect(effectiveMinScore(0.5, { 'Vulpes vulpes': 0.8 }, 'Sus scrofa')).toBe(0.5)
    expect(effectiveMinScore(0.5, undefined, 'Sus scrofa')).toBe(0.5)
    expect(effectiveMinScore(0.5, {}, undefined)).toBe(0.5)
  })
  it('a species value of 0 means no cut-off, not the general one', () => {
    expect(effectiveMinScore(0.5, { 'Sus scrofa': 0 }, 'Sus scrofa')).toBe(0)
  })
})

describe('cleanSpeciesCutoffs', () => {
  it('keeps only selected species with a value within 0 to 1', () => {
    expect(cleanSpeciesCutoffs({ a: 0.7, b: 0.9, c: 1.5, d: -1, e: NaN }, ['a', 'c', 'd', 'e'])).toEqual({ a: 0.7 })
  })
  it('keeps zero and one', () => {
    expect(cleanSpeciesCutoffs({ a: 0, b: 1 }, ['a', 'b'])).toEqual({ a: 0, b: 1 })
  })
  it('handles no overrides', () => {
    expect(cleanSpeciesCutoffs(undefined, ['a'])).toEqual({})
  })
})

describe('anyCutoff', () => {
  it('is true for a general cut-off or any species one above 0', () => {
    expect(anyCutoff(0.5, {})).toBe(true)
    expect(anyCutoff(0, { a: 0.3 })).toBe(true)
  })
  it('is false when everything is 0 or absent', () => {
    expect(anyCutoff(0, {})).toBe(false)
    expect(anyCutoff(0, { a: 0 })).toBe(false)
    expect(anyCutoff(0, undefined)).toBe(false)
  })
})
