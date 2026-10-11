import { useState } from 'react'
import { api } from '../api.js'
import { Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

export const TOOL_GROUPS = [
  {
    key: 'repo',
    label: 'Repository',
    desc: 'Git history, diffs, branches, and showing commits in the clone.',
    delegable: true,
  },
  {
    key: 'files',
    label: 'Files',
    desc: 'List, read, and search files in the repository.',
    delegable: true,
  },
  {
    key: 'github',
    label: 'GitHub',
    desc: 'Commits, pull requests, issues, and CI runs (read-only).',
    delegable: true,
  },
  {
    key: 'memory',
    label: 'Memory',
    desc: 'Read Totem project memory, and write it in write mode.',
    delegable: true,
  },
  {
    key: 'workspace',
    label: 'Workspace',
    desc: 'Read workspace files, and write plans/specs/docs in write mode.',
    delegable: true,
  },
  {
    key: 'writes',
    label: 'Code writes',
    desc: 'Edit files in the clone (needs git writes). Subagents edit only; branch/commit/push stay with the principal.',
    delegable: true,
  },
  {
    key: 'images',
    label: 'Images',
    desc: 'Generate images from prompts. Principal agent only.',
    delegable: false,
  },
  {
    key: 'browser',
    label: 'Browser',
    desc: 'Autonomous web tasks and UI debugging. Principal agent only.',
    delegable: false,
  },
  {
    key: 'tasks',
    label: 'Task board',
    desc: 'Create and move tasks on the project kanban. Principal agent only.',
    delegable: false,
  },
  {
    key: 'agents',
    label: 'Delegation',
    desc: 'Hand subtasks to other agents. Principal agent only.',
    delegable: false,
  },
]

export const ALL_TOOLS = TOOL_GROUPS.map((g) => g.key)
export const DELEGABLE_GROUPS = TOOL_GROUPS.filter((g) => g.delegable)

export function ToolGroupPicker({ value, onChange, groups = TOOL_GROUPS }) {
  const selected = new Set(value)
  const toggle = (k) => {
    const next = new Set(selected)
    if (next.has(k)) next.delete(k)
    else next.add(k)
    onChange(groups.filter((g) => next.has(g.key)).map((g) => g.key))
  }
  return (
    <div className="tool-groups">
      {groups.map((g) => (
        <button
          type="button"
          key={g.key}
          className={`tool-group ${selected.has(g.key) ? 'on' : ''}`}
          onClick={() => toggle(g.key)}
        >
          <span className="tool-group-check">
            {selected.has(g.key) && <Icon name="check" size={12} />}
          </span>
          <span className="tool-group-text">
            <span className="tool-group-label">{g.label}</span>
            <span className="tool-group-desc">{g.desc}</span>
          </span>
        </button>
      ))}
    </div>
  )
}

export function toTools(value) {
  if (Array.isArray(value)) return value
  return String(value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

export function AgentForm({ providers, presets, initial, onSubmit, onCancel, saving, error, submitLabel }) {
  const [form, setForm] = useState(() => ({
    name: initial?.name || '',
    provider_id: initial?.provider_id ? String(initial.provider_id) : '',
    model: initial?.model || '',
    reasoning_effort: initial?.reasoning_effort || '',
    system_prompt: initial?.system_prompt || '',
    tools: toTools(initial?.tools),
    mode: initial?.mode || 'read',
    max_turns: initial?.max_turns != null ? String(initial.max_turns) : '6',
  }))
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const selectedProvider = providers.find((p) => String(p.id) === form.provider_id)
  const modelOptions = selectedProvider?.models || []
  const applyPreset = (key) => {
    const p = presets[key]
    if (!p) return
    setForm((f) => ({
      ...f,
      name: f.name || p.name || key,
      reasoning_effort: p.reasoning_effort || f.reasoning_effort,
      system_prompt: p.system_prompt || '',
      tools: toTools(p.tools),
      mode: p.mode || 'read',
      max_turns: p.max_turns != null ? String(p.max_turns) : f.max_turns,
    }))
  }
  const submit = (e) => {
    e.preventDefault()
    onSubmit({
      name: form.name,
      provider_id: form.provider_id ? parseInt(form.provider_id, 10) : undefined,
      model: form.model,
      reasoning_effort: form.reasoning_effort || null,
      system_prompt: form.system_prompt,
      tools: form.tools,
      mode: form.mode,
      max_turns: form.max_turns ? parseInt(form.max_turns, 10) : undefined,
    })
  }
  return (
    <form className="agent-form" onSubmit={submit}>
      {!initial && Object.keys(presets).length > 0 && (
        <label className="field">
          <span className="field-label">Start from a preset</span>
          <select defaultValue="" onChange={(e) => applyPreset(e.target.value)}>
            <option value="">Blank agent</option>
            {Object.entries(presets).map(([k, p]) => (
              <option key={k} value={k}>
                {p.name || k}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="field-row">
        <label className="field">
          <span className="field-label">Name</span>
          <input value={form.name} onChange={set('name')} placeholder="default" required />
        </label>
        <label className="field">
          <span className="field-label">Provider</span>
          <select
            value={form.provider_id}
            onChange={(e) => setForm((f) => ({ ...f, provider_id: e.target.value, model: '' }))}
            required
          >
            <option value="">Choose a provider...</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Model</span>
          <select value={form.model} onChange={set('model')} disabled={!selectedProvider}>
            <option value="">
              Provider default{selectedProvider?.model ? ` (${selectedProvider.model})` : ''}
            </option>
            {modelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Reasoning effort</span>
          <select value={form.reasoning_effort} onChange={set('reasoning_effort')}>
            <option value="">Model default</option>
            <option value="none">None (thinking off)</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="max">Max</option>
          </select>
          <span className="field-hint">Sent as reasoning_effort. Some models reject medium.</span>
        </label>
      </div>
      <div className="field">
        <span className="field-label">Delegation mode</span>
        <div className="segmented">
          <button
            type="button"
            className={form.mode === 'read' ? 'on' : ''}
            onClick={() => setForm((f) => ({ ...f, mode: 'read' }))}
          >
            Read
          </button>
          <button
            type="button"
            className={form.mode === 'write' ? 'on' : ''}
            onClick={() => setForm((f) => ({ ...f, mode: 'write' }))}
          >
            Write
          </button>
        </div>
        <span className="field-hint">
          Read: explore and report only. Write: may also write workspace files and project
          memory. Project code stays read-only either way.
        </span>
      </div>
      <div className="field">
        <span className="field-label">What this agent can do</span>
        <ToolGroupPicker
          value={form.tools}
          groups={DELEGABLE_GROUPS}
          onChange={(tools) => setForm((f) => ({ ...f, tools }))}
        />
        <span className="field-hint">
          Images, the task board, and delegation belong to the principal agent only.
        </span>
      </div>
      <label className="field">
        <span className="field-label">System prompt (optional)</span>
        <textarea
          rows={4}
          value={form.system_prompt}
          onChange={set('system_prompt')}
          placeholder="Extra instructions prepended to every run for this agent."
        />
      </label>
      <div className="row" style={{ marginBottom: 0 }}>
        <button className="btn primary" disabled={saving}>
          {saving ? (
            <>
              <Spinner size={14} /> Saving
            </>
          ) : (
            submitLabel
          )}
        </button>
        {onCancel && (
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {error && <div className="error-text">{error}</div>}
    </form>
  )
}

export function SimpleAgentForm({ defaultAgent, providers, saving, error, onSave, onOpenSettings }) {
  const [providerId, setProviderId] = useState(
    defaultAgent?.provider_id ? String(defaultAgent.provider_id) : ''
  )
  const [model, setModel] = useState(defaultAgent?.model || '')
  const [prompt, setPrompt] = useState(defaultAgent?.system_prompt || '')

  const selectedProvider = providers.find((p) => String(p.id) === providerId)

  const submit = (e) => {
    e.preventDefault()
    if (!providerId) return
    onSave({
      name: defaultAgent?.name || 'default',
      provider_id: parseInt(providerId, 10),
      model,
      system_prompt: prompt,
      tools: ALL_TOOLS,
      mode: 'write',
      max_turns: defaultAgent?.max_turns || 10,
    })
  }

  if (providers.length === 0) {
    return (
      <div className="panel">
        <div className="placeholder">
          <div className="placeholder-icon">
            <Icon name="alert" size={18} />
          </div>
          <div className="error-banner">No providers configured</div>
          <div className="placeholder-hint">
            Add a provider and API key first, then come back to pick your agent.
          </div>
          <button className="btn primary" onClick={onOpenSettings}>
            <Icon name="settings" size={14} /> Open settings
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>One agent for everything</h3>
        <p>
          A single model and prompt handles chat, exploration, review, writing, and memory. This
          is all most setups need.
        </p>
      </div>
      <form className="agent-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Provider</span>
          <select
            value={providerId}
            onChange={(e) => {
              setProviderId(e.target.value)
              setModel('')
            }}
            required
          >
            <option value="">Choose a provider...</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Model</span>
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={!selectedProvider}>
            <option value="">
              Provider default{selectedProvider?.model ? ` (${selectedProvider.model})` : ''}
            </option>
            {(selectedProvider?.models || []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">System prompt (optional)</span>
          <textarea
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Extra instructions prepended to every run."
          />
        </label>
        <div className="field-hint">
          This agent can do everything: repo, files, GitHub, memory, workspace, and delegation.
        </div>
        <button className="btn primary" disabled={saving}>
          {saving ? (
            <>
              <Spinner size={14} /> Saving
            </>
          ) : (
            'Save agent'
          )}
        </button>
        {error && <div className="error-text">{error}</div>}
      </form>
    </div>
  )
}

export function AgentsPage({ onOpenSettings }) {
  const agentsReq = useAsync(api.listAgents, [])
  const providersReq = useAsync(api.listProviders, [])
  const presetsReq = useAsync(api.listAgentPresets, [])
  const actionsReq = useAsync(api.listActions, [])

  const [mode, setMode] = useState('simple')
  const [editing, setEditing] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState(null)
  const [actionSaving, setActionSaving] = useState(null)

  const agents = agentsReq.data || []
  const providers = providersReq.data || []
  const presets = presetsReq.data || {}
  const actions = actionsReq.data || []
  const chatDefaultId = actions.find((a) => a.key === 'chat')?.agent_id
  const defaultAgent =
    agents.find((a) => a.id === chatDefaultId) || agents.find((a) => a.name === 'default') || null

  const providerName = (id) => providers.find((p) => p.id === id)?.name || id || 'default'
  const providerModel = (id) => providers.find((p) => p.id === id)?.model || ''

  const refresh = () => {
    agentsReq.reload()
    actionsReq.reload()
  }

  const saveSimple = (body) => {
    setSaving(true)
    setFormError(null)
    const req = defaultAgent ? api.updateAgent(defaultAgent.id, body) : api.createAgent(body)
    req
      .then((agent) => api.setActionDefault('chat', agent.id))
      .then(refresh)
      .catch((e) => setFormError(e.message || String(e)))
      .finally(() => setSaving(false))
  }

  const saveAgent = (body) => {
    setSaving(true)
    setFormError(null)
    const req = editing ? api.updateAgent(editing.id, body) : api.createAgent(body)
    req
      .then(() => {
        setShowForm(false)
        setEditing(null)
        refresh()
      })
      .catch((e) => setFormError(e.message || String(e)))
      .finally(() => setSaving(false))
  }

  const saveAction = (key, agentId) => {
    setActionSaving(key)
    api
      .setActionDefault(key, agentId)
      .then(() => actionsReq.reload())
      .catch((e) => alert(e.message))
      .finally(() => setActionSaving(null))
  }

  if (agentsReq.loading || providersReq.loading) {
    return (
      <div className="center-col">
        <div className="page-head">
          <h2>Agents</h2>
        </div>
        <Skeleton className="block-skeleton" />
        <Skeleton className="block-skeleton" style={{ marginTop: 12 }} />
      </div>
    )
  }

  return (
    <div className="center-col">
      <div className="page-head">
        <h2>Agents</h2>
        <div className="segmented">
          <button
            className={mode === 'simple' ? 'on' : ''}
            onClick={() => setMode('simple')}
          >
            Simple
          </button>
          <button
            className={mode === 'advanced' ? 'on' : ''}
            onClick={() => setMode('advanced')}
          >
            Advanced
          </button>
        </div>
      </div>

      {mode === 'simple' ? (
        <SimpleAgentForm
          key={defaultAgent?.id || 'new'}
          defaultAgent={defaultAgent}
          providers={providers}
          saving={saving}
          error={formError}
          onSave={saveSimple}
          onOpenSettings={onOpenSettings}
        />
      ) : (
        <div className="agents-advanced">
          <section className="panel">
            <div className="panel-head row-between">
              <div>
                <h3>Agent profiles</h3>
                <p>
                  Each profile binds a provider, a system prompt, and the tools it may use. Create
                  focused agents (explore, review, write) or extra models.
                </p>
              </div>
              {!showForm && (
                <button
                  className="btn primary"
                  onClick={() => {
                    setEditing(null)
                    setFormError(null)
                    setShowForm(true)
                  }}
                >
                  <Icon name="plus" size={14} /> New agent
                </button>
              )}
            </div>

            {showForm && (
              <AgentForm
                key={editing?.id || 'new'}
                providers={providers}
                presets={presets}
                initial={editing}
                saving={saving}
                error={formError}
                submitLabel={editing ? 'Save changes' : 'Create agent'}
                onSubmit={saveAgent}
                onCancel={() => {
                  setShowForm(false)
                  setEditing(null)
                }}
              />
            )}

            {agents.length === 0 && !showForm ? (
              <div className="placeholder">
                <div className="placeholder-icon">
                  <Icon name="agents" size={18} />
                </div>
                <div className="placeholder-title">No agent profiles yet</div>
                <div className="placeholder-hint">Create one to specialise a role or model.</div>
              </div>
            ) : (
              <div className="agent-list">
                {agents.map((a) => (
                  <div key={a.id} className="agent-card">
                    <div className="agent-card-main">
                      <div className="agent-card-name">
                        {a.name}
                        {a.id === chatDefaultId && <span className="badge accent">default</span>}
                      </div>
                      <div className="agent-card-meta">
                        {providerName(a.provider_id)} ·{' '}
                        {a.model || providerModel(a.provider_id) || 'model'}
                        {a.reasoning_effort ? ` (${a.reasoning_effort})` : ''} ·{' '}
                        {a.mode || 'read'} mode · {toTools(a.tools).length} tool groups
                      </div>
                    </div>
                    <div className="agent-card-actions">
                      <button
                        className="btn"
                        onClick={() => {
                          setEditing(a)
                          setFormError(null)
                          setShowForm(true)
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="btn danger"
                        onClick={() =>
                          api
                            .deleteAgent(a.id)
                            .then(refresh)
                            .catch((e) => alert(e.message))
                        }
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-head">
              <h3>Defaults per action</h3>
              <p>
                Leave an action on <em>Default agent</em> to use the main agent. Assign another
                profile to give that action its own model or prompt.
              </p>
            </div>
            <div className="action-list">
              {actions.map((a) => (
                <div key={a.key} className="action-row">
                  <div className="action-info">
                    <div className="action-label">{a.label}</div>
                    <div className="action-desc">{a.description}</div>
                  </div>
                  <select
                    value={a.agent_id ?? ''}
                    disabled={actionSaving === a.key}
                    onChange={(e) =>
                      saveAction(a.key, e.target.value ? parseInt(e.target.value, 10) : null)
                    }
                  >
                    <option value="">Default agent</option>
                    {agents.map((ag) => (
                      <option key={ag.id} value={ag.id}>
                        {ag.name}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
