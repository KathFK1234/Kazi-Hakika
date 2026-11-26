import { useState } from 'react'
import { readTheme, setTheme, THEMES, type Theme } from '../theme'

const LABELS: Record<Theme, string> = {
  system: 'Device theme',
  light: 'Light',
  dark: 'Dark',
}

/** System / Light / Dark, for everyone, signed in or not. */
export function ThemeSwitch() {
  const [theme, setChoice] = useState<Theme>(readTheme)
  return (
    <label className="theme-switch">
      <span className="visually-hidden">Colour theme</span>
      <select
        value={theme}
        onChange={(event) => {
          const next = event.target.value as Theme
          setTheme(next)
          setChoice(next)
        }}
      >
        {THEMES.map((value) => (
          <option key={value} value={value}>
            {LABELS[value]}
          </option>
        ))}
      </select>
    </label>
  )
}
