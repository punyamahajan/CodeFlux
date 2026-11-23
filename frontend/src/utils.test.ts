import { describe, it, expect } from 'vitest'
import { formatMicroUSD } from './utils'

describe('Frontend Utils', () => {
  it('formats micro-USD to dollar strings accurately', () => {
    expect(formatMicroUSD(1_000_000)).toBe('$1.00')
    expect(formatMicroUSD(500_000)).toBe('$0.50')
    expect(formatMicroUSD(10_000_000)).toBe('$10.00')
    expect(formatMicroUSD(0)).toBe('$0.00')
  })
})
