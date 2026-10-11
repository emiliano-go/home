import { DEFAULT_THEME, LIGHT_THEME, THEME_MODES, THEME_PRESETS, defaultThemeState, effectiveMode } from '../theme.js'

export function ThemePanel({ theme, setTheme }) {
  const activeMode = effectiveMode(theme)
  const base = activeMode === 'light' ? LIGHT_THEME : DEFAULT_THEME
  const merged = { ...base, ...(theme.themes[activeMode] || {}) }

  const isActive = (key) => {
    const preset = THEME_PRESETS[key]
    if (!preset || preset.mode !== activeMode) return false
    return Object.keys(base).every((k) => merged[k] === preset.palette[k])
  }

  const applyPreset = (key) => {
    const preset = THEME_PRESETS[key]
    if (!preset) return
    setTheme({
      mode: preset.mode,
      themes: { ...theme.themes, [preset.mode]: { ...preset.palette } },
    })
  }

  return (
    <div className="theme-panel">
      <div className="field">
        <span className="field-label">Appearance</span>
        <div className="segmented">
          {THEME_MODES.map(([mode, label]) => (
            <button
              key={mode}
              className={theme.mode === mode ? 'on' : ''}
              onClick={() => setTheme({ ...theme, mode })}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="field-hint">
          Follow system switches automatically when your OS theme changes.
        </span>
      </div>

      <div className="field">
        <span className="field-label">Presets</span>
        <div className="row" style={{ marginBottom: 0 }}>
          {Object.entries(THEME_PRESETS).map(([key, preset]) => (
            <button
              key={key}
              className={`btn${isActive(key) ? ' primary' : ''}`}
              onClick={() => applyPreset(key)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <span className="field-hint">
          A preset also switches the appearance to its light or dark mode.
        </span>
      </div>

      <div className="row" style={{ marginBottom: 0 }}>
        <button className="btn" onClick={() => setTheme(defaultThemeState())}>
          Reset all
        </button>
      </div>
    </div>
  )
}
