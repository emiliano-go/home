export const THEME_KEY = 'hestia-theme'

export const DEFAULT_THEME = {
  '--content-bg': '#262624',
  '--sidebar-bg': '#1f1e1d',
  '--surface': '#30302e',
  '--border': '#3d3d3a',
  '--fg': '#f5f4ef',
  '--muted': '#8f8d86',
  '--accent': '#d97757',
  '--ok': '#6a9955',
  '--warn': '#d9a13b',
  '--err': '#e06c5a',
}

export const LIGHT_THEME = {
  '--content-bg': '#faf9f5',
  '--sidebar-bg': '#f0eee8',
  '--surface': '#ffffff',
  '--border': '#d9d4c9',
  '--fg': '#2b2a27',
  '--muted': '#6f6d66',
  '--accent': '#c96442',
  '--ok': '#4f7a3f',
  '--warn': '#b45309',
  '--err': '#c0392b',
}

export const THEME_LABELS = {
  '--content-bg': 'Content background',
  '--sidebar-bg': 'Sidebar background',
  '--surface': 'Surface',
  '--border': 'Border',
  '--fg': 'Text',
  '--muted': 'Muted text',
  '--accent': 'Accent',
  '--ok': 'Success',
  '--warn': 'Warning',
  '--err': 'Danger',
}

export const THEME_MODES = [
  ['system', 'Follow system'],
  ['light', 'Light'],
  ['dark', 'Dark'],
]

export const ATOM_ONE_THEME = {
  '--content-bg': '#282c34',
  '--sidebar-bg': '#21252b',
  '--surface': '#2c313a',
  '--border': '#3e4451',
  '--fg': '#abb2bf',
  '--muted': '#7a8292',
  '--accent': '#61afef',
  '--ok': '#98c379',
  '--warn': '#d19a66',
  '--err': '#e06c75',
}

export const GITHUB_LIGHT_THEME = {
  '--content-bg': '#f6f8fa',
  '--sidebar-bg': '#eaeef2',
  '--surface': '#ffffff',
  '--border': '#d0d7de',
  '--fg': '#1f2328',
  '--muted': '#59636e',
  '--accent': '#0969da',
  '--ok': '#1a7f37',
  '--warn': '#9a6700',
  '--err': '#d1242f',
}

export const NORD_LIGHT_THEME = {
  '--content-bg': '#eceff4',
  '--sidebar-bg': '#dfe6ee',
  '--surface': '#f7f8fa',
  '--border': '#c8d0dc',
  '--fg': '#2e3440',
  '--muted': '#616c80',
  '--accent': '#4c7199',
  '--ok': '#4c8a5f',
  '--warn': '#9a6a2f',
  '--err': '#b04a55',
}

export const DRACULA_THEME = {
  '--content-bg': '#282a36',
  '--sidebar-bg': '#1e1f2b',
  '--surface': '#343746',
  '--border': '#44475a',
  '--fg': '#f8f8f2',
  '--muted': '#6272a4',
  '--accent': '#bd93f9',
  '--ok': '#50fa7b',
  '--warn': '#ffb86c',
  '--err': '#ff5555',
}

export const TOKYO_NIGHT_THEME = {
  '--content-bg': '#1a1b26',
  '--sidebar-bg': '#16161e',
  '--surface': '#24283b',
  '--border': '#343a4f',
  '--fg': '#c0caf5',
  '--muted': '#565f89',
  '--accent': '#7aa2f7',
  '--ok': '#9ece6a',
  '--warn': '#e0af68',
  '--err': '#f7768e',
}

export const GRUVBOX_DARK_THEME = {
  '--content-bg': '#282828',
  '--sidebar-bg': '#1d2021',
  '--surface': '#3c3836',
  '--border': '#504945',
  '--fg': '#ebdbb2',
  '--muted': '#928374',
  '--accent': '#fe8019',
  '--ok': '#b8bb26',
  '--warn': '#fabd2f',
  '--err': '#fb4934',
}

export const MATERIAL_LIGHT_THEME = {
  '--content-bg': '#fef7ff',
  '--sidebar-bg': '#f3edf7',
  '--surface': '#ffffff',
  '--border': '#cac4d0',
  '--fg': '#1d1b20',
  '--muted': '#49454f',
  '--accent': '#6750a4',
  '--ok': '#2e7d32',
  '--warn': '#b26a00',
  '--err': '#b3261e',
}

export const MATERIAL_DARK_THEME = {
  '--content-bg': '#121212',
  '--sidebar-bg': '#1e1e1e',
  '--surface': '#242424',
  '--border': '#3a3a3e',
  '--fg': '#e6e0e9',
  '--muted': '#938f99',
  '--accent': '#bb86fc',
  '--ok': '#66d18c',
  '--warn': '#ffb74d',
  '--err': '#cf6679',
}

export const THEME_PRESETS = {
  'hestia-light': { label: 'Hestia Light', mode: 'light', palette: LIGHT_THEME },
  'github-light': { label: 'GitHub Light', mode: 'light', palette: GITHUB_LIGHT_THEME },
  'nord-light': { label: 'Nord Light', mode: 'light', palette: NORD_LIGHT_THEME },
  'material-light': { label: 'Material Light', mode: 'light', palette: MATERIAL_LIGHT_THEME },
  'hestia-dark': { label: 'Hestia Dark', mode: 'dark', palette: DEFAULT_THEME },
  'atom-one': { label: 'Atom One', mode: 'dark', palette: ATOM_ONE_THEME },
  'dracula': { label: 'Dracula', mode: 'dark', palette: DRACULA_THEME },
  'tokyo-night': { label: 'Tokyo Night', mode: 'dark', palette: TOKYO_NIGHT_THEME },
  'gruvbox-dark': { label: 'Gruvbox Dark', mode: 'dark', palette: GRUVBOX_DARK_THEME },
  'material-dark': { label: 'Material Dark', mode: 'dark', palette: MATERIAL_DARK_THEME },
}

export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function rgbToHex(rgb) {
  return '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
}

export function mixColors(a, b, t) {
  const ca = hexToRgb(a)
  const cb = hexToRgb(b)
  if (!ca || !cb) return a
  return rgbToHex(ca.map((v, i) => v + (cb[i] - v) * t))
}

export function rgba(hex, alpha) {
  const rgb = hexToRgb(hex)
  return rgb ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})` : hex
}

export function luminance(hex) {
  const rgb = hexToRgb(hex)
  if (!rgb) return 0
  const [r, g, b] = rgb.map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function readableOn(hex) {
  return luminance(hex) > 0.2 ? '#20130c' : '#ffffff'
}

export function systemMode() {
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function effectiveMode(state) {
  return state.mode === 'system' ? systemMode() : state.mode
}

export function defaultThemeState() {
  return { mode: 'system', themes: { dark: {}, light: {} } }
}

export function loadThemeState() {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (!raw) return defaultThemeState()
    const parsed = JSON.parse(raw)
    if (parsed && parsed.themes) {
      return {
        mode: THEME_MODES.some(([m]) => m === parsed.mode) ? parsed.mode : 'system',
        themes: { dark: parsed.themes.dark || {}, light: parsed.themes.light || {} },
      }
    }
    if (parsed && Object.keys(parsed).some((k) => k.startsWith('--'))) {
      // legacy single palette: keep it as dark-mode overrides
      return { mode: 'dark', themes: { dark: parsed, light: {} } }
    }
    return defaultThemeState()
  } catch (e) {
    return defaultThemeState()
  }
}

export function saveThemeState(state) {
  const themes = {}
  for (const mode of ['dark', 'light']) {
    const base = mode === 'light' ? LIGHT_THEME : DEFAULT_THEME
    const clean = Object.fromEntries(
      Object.entries(state.themes[mode] || {}).filter(
        ([k, v]) => base[k] && hexToRgb(v) && v !== base[k]
      )
    )
    if (Object.keys(clean).length) themes[mode] = clean
  }
  if (state.mode === 'system' && Object.keys(themes).length === 0) {
    localStorage.removeItem(THEME_KEY)
  } else {
    localStorage.setItem(THEME_KEY, JSON.stringify({ mode: state.mode, themes }))
  }
}

export function applyThemeState(state) {
  const mode = effectiveMode(state)
  const base = mode === 'light' ? LIGHT_THEME : DEFAULT_THEME
  const vars = { ...base, ...(state.themes[mode] || {}) }
  const root = document.documentElement.style
  root.setProperty('color-scheme', mode)
  for (const [k, v] of Object.entries(vars)) root.setProperty(k, v)

  const fg = vars['--fg']
  const contentBg = vars['--content-bg']
  const sidebarBg = vars['--sidebar-bg']
  const surface = vars['--surface']
  const border = vars['--border']
  const accent = vars['--accent']

  root.setProperty('--sidebar-bg-hover', mixColors(sidebarBg, fg, 0.06))
  root.setProperty('--sidebar-active', mixColors(sidebarBg, fg, 0.12))
  root.setProperty('--surface-2', mixColors(surface, fg, 0.05))
  root.setProperty('--surface-hover', mixColors(surface, fg, 0.09))
  root.setProperty('--border-soft', mixColors(border, contentBg, 0.45))
  root.setProperty('--fg-secondary', mixColors(fg, contentBg, 0.25))
  root.setProperty('--faint', mixColors(fg, contentBg, 0.5))
  root.setProperty('--accent-dim', mixColors(accent, '#000000', 0.18))
  root.setProperty(
    '--accent-hover',
    mode === 'light' ? mixColors(accent, '#000000', 0.08) : mixColors(accent, '#ffffff', 0.12)
  )
  root.setProperty('--accent-soft', rgba(accent, 0.14))
  root.setProperty('--accent-glow', rgba(accent, 0.3))
  root.setProperty('--ok-soft', rgba(vars['--ok'], 0.14))
  root.setProperty('--on-ok', readableOn(vars['--ok']))
  root.setProperty('--warn-soft', rgba(vars['--warn'], 0.14))
  root.setProperty('--err-soft', rgba(vars['--err'], 0.14))
  root.setProperty('--on-accent', readableOn(accent))
  root.setProperty('--overlay', rgba(mixColors(contentBg, '#000000', 0.6), 0.6))

  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', contentBg)
}
