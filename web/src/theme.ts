// Light/dark choice. 'system' follows the device; the choice is kept on this
// device only. public/theme.js applies a saved choice before first paint, so
// keep THEME_KEY and the attribute in step with it.

export type Theme = 'system' | 'light' | 'dark'
export const THEMES: readonly Theme[] = ['system', 'light', 'dark']
export const THEME_KEY = 'kh-theme'

function isTheme(value: unknown): value is Theme {
  return typeof value === 'string' && (THEMES as readonly string[]).includes(value)
}

/** The saved choice, or 'system' when there is none or storage is blocked. */
export function readTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(THEME_KEY)
    return isTheme(saved) ? saved : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') delete root.dataset.theme
  else root.dataset.theme = theme
}

/** Apply now and remember it; still applies for this visit if storage is blocked. */
export function setTheme(theme: Theme): void {
  applyTheme(theme)
  try {
    if (theme === 'system') window.localStorage.removeItem(THEME_KEY)
    else window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Private mode or blocked storage: the choice lasts until the page closes.
  }
}
