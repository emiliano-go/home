const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = data.detail || JSON.stringify(data)
    } catch (e) {
      // keep statusText
    }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  listProjects: () => request('/projects'),
  createProject: (body) => request('/projects', { method: 'POST', body: JSON.stringify(body) }),
  // SSE: POST stream of `data: {json}` events while cloning + initializing.
  async createProjectStream(body, handlers) {
    const res = await fetch(`${BASE}/projects/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const data = await res.json()
        detail = data.detail || JSON.stringify(data)
      } catch (e) {
        // keep statusText
      }
      throw new Error(detail)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 1)
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        let evt
        try {
          evt = JSON.parse(trimmed.slice(5).trim())
        } catch (e) {
          continue
        }
        handlers.onEvent(evt)
      }
    }
  },
  getProject: (id) => request(`/projects/${id}`),
  openProject: (id) => request(`/projects/${id}/open`, { method: 'POST' }),
  pullProject: (id, repo) =>
    request(`/projects/${id}/pull${repo ? `?repo=${encodeURIComponent(repo)}` : ''}`, {
      method: 'POST',
    }),
  listProjectRepos: (id, github = false) =>
    request(`/projects/${id}/repos${github ? '?github=true' : ''}`),
  addProjectRepo: (id, body) =>
    request(`/projects/${id}/repos`, { method: 'POST', body: JSON.stringify(body) }),
  removeProjectRepo: (id, alias) =>
    request(`/projects/${id}/repos/${encodeURIComponent(alias)}`, { method: 'DELETE' }),
  setGitWrites: (id, enabled) =>
    request(`/projects/${id}/git-writes`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
  updateProject: (id, body) =>
    request(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  listSnapshots: (id) => request(`/projects/${id}/snapshots`),
  revertProject: (id, sha) =>
    request(`/projects/${id}/revert`, { method: 'POST', body: JSON.stringify(sha ? { sha } : {}) }),
  getSandbox: (id) => request(`/projects/${id}/sandbox`),
  promoteSandbox: (id) => request(`/projects/${id}/sandbox/promote`, { method: 'POST', body: '{}' }),
  discardSandbox: (id) => request(`/projects/${id}/sandbox/discard`, { method: 'POST', body: '{}' }),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),
  activity: () => request('/activity'),

  projectStatus: (id, since) =>
    request(
      `/projects/${id}/status${since ? `?since=${encodeURIComponent(since)}` : ''}`
    ),
  projectActivity: (id, github = true) =>
    request(`/projects/${id}/activity?github=${github ? 'true' : 'false'}`),
  projectGithub: (id, kind, state = 'open', repo) =>
    request(
      `/projects/${id}/github?kind=${kind}&state=${state}${repo ? `&repo=${encodeURIComponent(repo)}` : ''}`
    ),
  projectUsage: (id) => request(`/projects/${id}/usage`),

  listTasks: (projectId) => request(`/projects/${projectId}/tasks`),  createTask: (projectId, body) =>
    request(`/projects/${projectId}/tasks`, { method: 'POST', body: JSON.stringify(body) }),
  updateTask: (taskId, body) =>
    request(`/tasks/${taskId}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteTask: (taskId) => request(`/tasks/${taskId}`, { method: 'DELETE' }),
  listComments: (taskId) => request(`/tasks/${taskId}/comments`),
  addComment: (taskId, body) =>
    request(`/tasks/${taskId}/comments`, { method: 'POST', body: JSON.stringify(body) }),
  syncIssues: (projectId, body = {}) =>
    request(`/projects/${projectId}/issues/sync`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  suggestTasks: (projectId) =>
    request(`/projects/${projectId}/tasks/suggest`, { method: 'POST', body: '{}' }),

  listMilestones: (projectId) => request(`/projects/${projectId}/milestones`),
  createMilestone: (projectId, body) =>
    request(`/projects/${projectId}/milestones`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateMilestone: (milestoneId, body) =>
    request(`/milestones/${milestoneId}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteMilestone: (milestoneId) =>
    request(`/milestones/${milestoneId}`, { method: 'DELETE' }),

  triage: (projectId, body) =>
    request(`/projects/${projectId}/triage`, { method: 'POST', body: JSON.stringify(body) }),
  reviewItem: (projectId, body) =>
    request(`/projects/${projectId}/github/review`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  mergePr: (projectId, body) =>
    request(`/projects/${projectId}/github/merge`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  generateDoc: (projectId, body) =>
    request(`/projects/${projectId}/docs`, { method: 'POST', body: JSON.stringify(body) }),

  listGoals: (projectId) => request(`/projects/${projectId}/goals`),
  createGoal: (projectId, body) =>
    request(`/projects/${projectId}/goals`, { method: 'POST', body: JSON.stringify(body) }),
  updateGoal: (id, body) =>
    request(`/goals/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteGoal: (id) => request(`/goals/${id}`, { method: 'DELETE' }),
  discussGoal: (id) => request(`/goals/${id}/discuss`, { method: 'POST', body: '{}' }),
  planGoal: (id, body = {}) =>
    request(`/goals/${id}/plan`, { method: 'POST', body: JSON.stringify(body) }),
  convergeGoal: (id, body = {}) =>
    request(`/goals/${id}/converge`, { method: 'POST', body: JSON.stringify(body) }),

  globalSearch: (q) => request(`/search?q=${encodeURIComponent(q)}`),
  listInbox: () => request('/inbox'),
  pollInbox: () => request('/inbox/poll', { method: 'POST' }),
  markInboxRead: (id) => request(`/inbox/${id}/read`, { method: 'POST' }),
  markAllInboxRead: () => request('/inbox/read-all', { method: 'POST' }),

  listSchedules: (projectId) => request(`/projects/${projectId}/schedules`),
  createSchedule: (projectId, body) =>
    request(`/projects/${projectId}/schedules`, { method: 'POST', body: JSON.stringify(body) }),
  updateSchedule: (id, body) =>
    request(`/schedules/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSchedule: (id) => request(`/schedules/${id}`, { method: 'DELETE' }),
  runSchedule: (id) => request(`/schedules/${id}/run`, { method: 'POST' }),

  listPresets: () => request('/providers/presets'),
  listProviders: () => request('/providers'),
  listProviderModels: (body) =>
    request('/providers/models', { method: 'POST', body: JSON.stringify(body) }),
  addProviderModels: (id, models) =>
    request(`/providers/${id}/models`, { method: 'POST', body: JSON.stringify({ models }) }),
  removeProviderModel: (id, name) =>
    request(`/providers/${id}/models/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  createProvider: (body) => request('/providers', { method: 'POST', body: JSON.stringify(body) }),
  updateProvider: (id, body) =>
    request(`/providers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProvider: (id) => request(`/providers/${id}`, { method: 'DELETE' }),
  testProvider: (id) => request(`/providers/${id}/test`, { method: 'POST' }),

  listAgentPresets: () => request('/agents/presets'),
  listAgents: () => request('/agents'),
  createAgent: (body) => request('/agents', { method: 'POST', body: JSON.stringify(body) }),
  updateAgent: (id, body) =>
    request(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteAgent: (id) => request(`/agents/${id}`, { method: 'DELETE' }),

  listActions: () => request('/actions'),
  setActionDefault: (key, agentId) =>
    request(`/actions/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ agent_id: agentId }),
    }),

  notifyStatus: () => request('/notify/status'),
  notifyTest: () => request('/notify/test', { method: 'POST', body: '{}' }),

  getSettings: () => request('/settings'),
  updateSettings: (body) =>
    request('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  getDecision: () => request('/decision'),
  patchDecision: (body) =>
    request('/decision', { method: 'PATCH', body: JSON.stringify(body) }),
  implementTask: (taskId) =>
    request(`/tasks/${taskId}/implement`, { method: 'POST', body: '{}' }),
  runNextTask: (projectId) =>
    request(`/projects/${projectId}/tasks/run-next`, { method: 'POST', body: '{}' }),
  capture: (projectId, body) =>
    request(`/projects/${projectId}/capture`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listJobs: (projectId, activeOnly = false) =>
    request(`/projects/${projectId}/jobs${activeOnly ? '?active_only=true' : ''}`),
  stopJob: (id) => request(`/jobs/${id}/stop`, { method: 'POST', body: '{}' }),
  listPreferences: () => request('/settings/preferences'),
  addPreference: (text) =>
    request('/settings/preferences', { method: 'POST', body: JSON.stringify({ text }) }),
  setPreference: (index, text) =>
    request(`/settings/preferences/${index}`, {
      method: 'PUT',
      body: JSON.stringify({ text }),
    }),
  removePreference: (index) =>
    request(`/settings/preferences/${index}`, { method: 'DELETE' }),

  githubStatus: () => request('/github/status'),
  githubConnect: (token) =>
    request('/github/token', { method: 'POST', body: JSON.stringify({ token }) }),
  githubDisconnect: () => request('/github/token', { method: 'DELETE' }),
  githubImportGh: () => request('/github/import-gh', { method: 'POST', body: '{}' }),

  listReminders: (includeDone = false) =>
    request(`/reminders?include_done=${includeDone ? 'true' : 'false'}`),
  createReminder: (body) =>
    request('/reminders', { method: 'POST', body: JSON.stringify(body) }),
  updateReminder: (id, body) =>
    request(`/reminders/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteReminder: (id) => request(`/reminders/${id}`, { method: 'DELETE' }),

  listWatches: () => request('/watches'),
  createWatch: (body) =>
    request('/watches', { method: 'POST', body: JSON.stringify(body) }),
  updateWatch: (id, body) =>
    request(`/watches/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteWatch: (id) => request(`/watches/${id}`, { method: 'DELETE' }),
  checkWatch: (id) => request(`/watches/${id}/check`, { method: 'POST', body: '{}' }),

  listSkills: () => request('/skills'),
  installSkill: (body) =>
    request('/skills/install', { method: 'POST', body: JSON.stringify(body) }),
  getSkill: (slug) => request(`/skills/${slug}`),
  deleteSkill: (slug) => request(`/skills/${slug}`, { method: 'DELETE' }),

  authStatus: () => request('/auth/status'),
  authRegisterBegin: (setupToken) =>
    request('/auth/register/begin', {
      method: 'POST',
      body: JSON.stringify({ setup_token: setupToken }),
    }),
  authRegisterComplete: (body) =>
    request('/auth/register/complete', { method: 'POST', body: JSON.stringify(body) }),
  authLoginBegin: () => request('/auth/login/begin', { method: 'POST', body: '{}' }),
  authLoginComplete: (body) =>
    request('/auth/login/complete', { method: 'POST', body: JSON.stringify(body) }),
  authLogout: () => request('/auth/logout', { method: 'POST' }),

  listSessions: (projectId) => request(`/projects/${projectId}/sessions`),
  listMessages: (sessionId) => request(`/sessions/${sessionId}/messages`),
  listQuestions: (sessionId) => request(`/sessions/${sessionId}/questions`),
  dismissQuestion: (id) =>
    request(`/questions/${id}/dismiss`, { method: 'POST', body: '{}' }),
  searchMemory: (projectId, q) =>
    request(`/projects/${projectId}/memory?q=${encodeURIComponent(q)}`),
  listCandidates: (projectId, status = 'pending') =>
    request(`/projects/${projectId}/memory/candidates?status=${status}`),
  acceptCandidate: (id) =>
    request(`/candidates/${id}/accept`, { method: 'POST', body: '{}' }),
  rejectCandidate: (id) =>
    request(`/candidates/${id}/reject`, { method: 'POST', body: '{}' }),
  acceptAllCandidates: (projectId) =>
    request(`/projects/${projectId}/memory/candidates/accept-all`, {
      method: 'POST',
      body: '{}',
    }),

  listWorkspace: (projectId, pattern = '*') =>
    request(`/projects/${projectId}/workspace?pattern=${encodeURIComponent(pattern)}`),
  getWorkspaceFile: async (projectId, path) => {
    const res = await fetch(
      `${BASE}/projects/${projectId}/workspace/file?path=${encodeURIComponent(path)}`
    )
    if (!res.ok) throw new Error(res.status === 404 ? 'File not found' : res.statusText)
    return res.text()
  },
  listGallery: () => request('/gallery'),
  fixMemory: (projectId, body) =>
    request(`/projects/${projectId}/memory/fix`, { method: 'POST', body: JSON.stringify(body) }),

  // Chat as a run: streams events, auto-reconnects and resumes on drops.
  chatStream(projectId, body, handlers = {}) {
    return streamRun(`/projects/${projectId}/chat`, {
      method: 'POST',
      body,
      ...handlers,
    })
  },

  // Re-attach to a run already in flight (Wi-Fi drop, tab reload).
  resumeRun(runId, after, handlers = {}) {
    return streamRun(`/runs/${runId}/events`, { method: 'GET', after, ...handlers })
  },

  stopRun: (runId) => request(`/runs/${runId}/stop`, { method: 'POST', body: '{}' }),
  listRuns: (activeOnly = false) =>
    request(`/runs${activeOnly ? '?active_only=true' : ''}`),
  getRun: (runId) => request(`/runs/${runId}`),

  // Side question while a task runs: same agent, compacted context, read-only.
  async btw(projectId, body, handlers) {
    return streamPost(`/projects/${projectId}/btw`, body, handlers.onEvent)
  },
}

const TERMINAL_EVENTS = new Set(['done', 'error', 'stopped', 'timed_out'])

// Stream a run (POST to start, GET to resume) with replay + auto-reconnect.
async function streamRun(path, { method = 'POST', body, after = 0, onEvent, onStatus, signal }) {
  let runId = null
  let last = after
  let attempt = 0
  for (;;) {
    const url = runId ? `/runs/${runId}/events` : path
    const headers = {}
    if (runId && last) headers['Last-Event-ID'] = String(last)
    if (body && !runId) headers['Content-Type'] = 'application/json'
    let finished = false
    try {
      const res = await fetch(BASE + url, {
        method: runId ? 'GET' : method,
        headers,
        body: runId ? undefined : body ? JSON.stringify(body) : undefined,
        signal,
      })
      if (!res.ok) {
        let detail = res.statusText
        try {
          const data = await res.json()
          detail = data.detail || JSON.stringify(data)
        } catch (e) {
          // keep statusText
        }
        throw new Error(detail)
      }
      onStatus?.('streaming')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 1)
          const trimmed = line.trim()
          if (trimmed.startsWith('id:')) {
            const n = parseInt(trimmed.slice(3).trim(), 10)
            if (!Number.isNaN(n)) last = n
            continue
          }
          if (!trimmed.startsWith('data:')) continue
          let evt
          try {
            evt = JSON.parse(trimmed.slice(5).trim())
          } catch (e) {
            continue
          }
          if (evt.run_id) runId = evt.run_id
          if (typeof evt.seq === 'number') last = evt.seq
          onEvent?.(evt)
          if (TERMINAL_EVENTS.has(evt.event)) finished = true
        }
      }
      if (finished) return
    } catch (err) {
      if (signal?.aborted) throw err
      if (!runId) throw err
    }
    if (!runId) return
    attempt += 1
    onStatus?.('reconnecting')
    await new Promise((r) => setTimeout(r, Math.min(1000 * attempt, 8000)))
  }
}

// POST an SSE endpoint and invoke onEvent for every `data: {json}` line.
async function streamPost(path, body, onEvent) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = data.detail || JSON.stringify(data)
    } catch (e) {
      // keep statusText
    }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 1)
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      let evt
      try {
        evt = JSON.parse(trimmed.slice(5).trim())
      } catch (e) {
        continue
      }
      onEvent(evt)
    }
  }
}
