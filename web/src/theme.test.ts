import { afterEach, describe, expect, it, vi } from 'vitest'
import source from '../public/theme.js?raw'
import { applyTheme, readTheme, setTheme, THEME_KEY } from './theme'

afterEach(() => {
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

describe('theme', () => {
  it('defaults to the device setting', () => {
    expect(readTheme()).toBe('system')
    applyTheme('system')
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('remembers light or dark and applies it', () => {
    setTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(readTheme()).toBe('dark')

    setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(readTheme()).toBe('light')
  })

  it('going back to the device setting forgets the choice', () => {
    setTheme('dark')
    setTheme('system')
    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
  })

  it('ignores a stored value it does not know', () => {
    localStorage.setItem(THEME_KEY, 'neon')
    expect(readTheme()).toBe('system')
  })

  it('still works when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readTheme()).toBe('system')
    setTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})

describe('public/theme.js (runs before the app)', () => {
  const run = () => new Function(source)()

  it.each(['light', 'dark'] as const)('applies a saved %s choice under the same key as theme.ts', (theme) => {
    localStorage.setItem(THEME_KEY, theme)
    run()
    expect(document.documentElement.dataset.theme).toBe(theme)
  })

  it('leaves the device setting alone for no or unknown values', () => {
    run()
    expect(document.documentElement.dataset.theme).toBeUndefined()
    localStorage.setItem(THEME_KEY, 'system')
    run()
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('survives blocked storage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(run).not.toThrow()
  })
})
