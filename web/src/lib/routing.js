export const GLOBAL_VIEWS = ['home', 'help', 'search', 'agents', 'gallery', 'reminders', 'watches', 'settings', 'new-project', 'runs']

export const PROJECT_VIEWS = [
  'welcome',
  'chat',
  'goals',
  'tasks',
  'roadmap',
  'github',
  'activity',
  'automations',
  'files',
  'memory',
  'background',
  'capture',
  'about',
  'repos',
]

export function parseHash(hash) {
  const raw = (hash || '').replace(/^#\/?/, '')
  if (!raw) return null
  const [path, query] = raw.split('?')
  const params = new URLSearchParams(query || '')
  const parts = path.split('/').filter(Boolean)
  if (parts[0] === 'p' && parts[1]) {
    const action = params.get('action')
    return {
      projectId: Number(parts[1]),
      view: {
        type: PROJECT_VIEWS.includes(parts[2]) ? parts[2] : 'welcome',
        ...(action ? { action } : {}),
      },
      session: params.get('session') || null,
    }
  }
  if (parts[0] === 'g' && GLOBAL_VIEWS.includes(parts[1])) {
    return { view: { type: parts[1] } }
  }
  if (parts[0] && GLOBAL_VIEWS.includes(parts[0])) {
    return { view: { type: parts[0] } }
  }
  return null
}

export function viewHash(projectId, view, chatSessionId) {
  if (view.type === 'reminders' || view.type === 'watches') return `#/g/${view.type}`
  if (['home', 'help', 'search', 'agents', 'gallery', 'settings', 'new-project', 'runs'].includes(view.type)) {
    return `#/${view.type}`
  }
  if (projectId && PROJECT_VIEWS.includes(view.type)) {
    const params = new URLSearchParams()
    if (view.type === 'chat' && chatSessionId) params.set('session', chatSessionId)
    if (view.action && view.action !== 'chat') params.set('action', view.action)
    const q = params.toString() ? `?${params.toString()}` : ''
    return `#/p/${projectId}/${view.type}${q}`
  }
  return '#/home'
}
