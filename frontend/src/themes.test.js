import { describe, expect, it } from 'vitest'
import { THEMES } from './themes'

describe('THEMES', () => {
  it('has unique ids and includes the light default', () => {
    const ids = THEMES.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain('light')
  })

  it('every theme has a label and swatch', () => {
    for (const theme of THEMES) {
      expect(theme.label).toBeTruthy()
      expect(theme.swatch).toMatch(/^#/)
    }
  })
})
