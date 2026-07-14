import { describe, expect, it } from 'vitest'
import { formatCents } from './currency'

describe('formatCents', () => {
  it('formats whole and fractional amounts', () => {
    expect(formatCents(1234)).toBe('$12.34')
    expect(formatCents(100)).toBe('$1.00')
  })

  it('pads sub-dollar amounts', () => {
    expect(formatCents(5)).toBe('$0.05')
    expect(formatCents(0)).toBe('$0.00')
  })

  it('puts the sign before the symbol for negatives', () => {
    expect(formatCents(-250)).toBe('-$2.50')
  })

  it('accepts a custom symbol', () => {
    expect(formatCents(150, '£')).toBe('£1.50')
  })
})
