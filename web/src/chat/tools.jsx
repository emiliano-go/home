import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { truncate } from '../lib/format.js'
import { mdToHtml } from '../lib/markdown.js'

export const TOOL_ICONS = {
  git_pull: 'refresh',
  git_log: 'git',
  git_diff: 'git',
  git_show: 'git',
  git_status: 'git',
  git_branches: 'git',
  repo_path: 'folder',
  list_files: 'files',
  read_file: 'files',
  grep: 'search',
  read_agents_md: 'info',
  list_docs: 'files',
  gh_commits: 'git',
  gh_prs: 'git',
  gh_issues: 'chat',
  gh_ci_runs: 'settings',
  memory_search: 'search',
  memory_get: 'memory',
  memory_list: 'memory',
  memory_create: 'plus',
  memory_update: 'refresh',
  memory_delete: 'x',
  workspace_write: 'files',
  workspace_read: 'files',
  workspace_list: 'folder',
  run_subagent: 'agents',
  run_swarm: 'agents',
  agent_list: 'agents',
  generate_image: 'gallery',
  browser_task: 'globe',
  browser_open: 'globe',
  browser_screenshot: 'gallery',
  browser_get_content: 'files',
  browser_click: 'play',
  browser_type: 'edit',
  browser_eval: 'settings',
  browser_close: 'x',
}

export const TOOL_TITLES = {
  git_pull: 'Pull latest changes',
  git_log: 'Read commit history',
  git_diff: 'Diff changes',
  git_show: 'Show a commit',
  git_status: 'Check git status',
  git_branches: 'List branches',
  repo_path: 'Resolve repository path',
  list_files: 'List files',
  read_file: 'Read a file',
  grep: 'Search file contents',
  read_agents_md: 'Read AGENTS.md',
  list_docs: 'List docs',
  gh_commits: 'Fetch GitHub commits',
  gh_prs: 'Fetch pull requests',
  gh_issues: 'Fetch issues',
  gh_ci_runs: 'Fetch CI runs',
  memory_search: 'Search memory',
  memory_get: 'Get a memory',
  memory_list: 'List memories',
  memory_create: 'Write a memory',
  memory_update: 'Update a memory',
  memory_delete: 'Delete a memory',
  workspace_write: 'Write a workspace file',
  workspace_read: 'Read a workspace file',
  workspace_list: 'List workspace files',
  run_subagent: 'Delegate to a subagent',
  run_swarm: 'Run a subagent swarm',
  agent_list: 'List agent profiles',
  generate_image: 'Generate an image',
  browser_task: 'Run a browser task',
  browser_open: 'Open a page',
  browser_screenshot: 'Screenshot the page',
  browser_get_content: 'Read page content',
  browser_click: 'Click an element',
  browser_type: 'Type into a field',
  browser_eval: 'Run page JavaScript',
  browser_close: 'Close the browser',
}

function resultImage(result) {
  if (!result?.ok) return null
  try {
    const data = JSON.parse(result.preview)
    const first =
      typeof data?.markdown === 'string'
        ? data.markdown
        : Array.isArray(data?.screenshots)
          ? data.screenshots[0]
          : null
    const url = typeof first === 'string' && first.match(/\]\(([^)]+)\)/)
    return url ? url[1] : null
  } catch (e) {
    return null
  }
}

function groupTimeline(items) {
  const out = []
  for (const item of items) {
    if (item.kind === 'tool') {
      const last = out[out.length - 1]
      if (last && last.kind === 'tools') last.events.push(item.evt)
      else out.push({ kind: 'tools', events: [item.evt] })
    } else {
      out.push(item)
    }
  }
  return out
}

export function RunTimeline({ runId }) {
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  useEffect(() => {
    if (!runId) return
    let alive = true
    const controller = new AbortController()
    api
      .resumeRun(runId, 0, {
        signal: controller.signal,
        onEvent: (evt) => {
          if (!alive) return
          const e = evt.event
          if (e === 'thinking') {
            setItems((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.kind === 'thinking') {
                return [...prev.slice(0, -1), { ...last, text: last.text + (evt.text || '') }]
              }
              return [...prev, { kind: 'thinking', text: evt.text || '' }]
            })
          } else if (e === 'tool_call' || e === 'tool_result' || e === 'tool_progress') {
            setItems((prev) => [...prev, { kind: 'tool', evt }])
          } else if (e === 'message') {
            if (evt.content && evt.content.trim()) {
              setItems((prev) => [...prev, { kind: 'assistant', text: evt.content }])
            }
          } else if (e === 'error') {
            setError(evt.message || 'subagent error')
          }
        },
      })
      .catch((err) => {
        if (alive && !controller.signal.aborted) setError(err.message || String(err))
      })
    return () => {
      alive = false
      controller.abort()
    }
  }, [runId])
  if (error) return <div className="subagent-error">{error}</div>
  if (!items.length) return <div className="subagent-empty">Reading run…</div>
  return (
    <div className="subagent-timeline">
      {groupTimeline(items).map((g, i) =>
        g.kind === 'thinking' ? (
          <div key={`think-${i}`} className="subagent-thinking">
            {g.text}
          </div>
        ) : g.kind === 'assistant' ? (
          <div
            key={`msg-${i}`}
            className="msg-md prose subagent-msg"
            dangerouslySetInnerHTML={{ __html: mdToHtml(g.text) }}
          />
        ) : (
          pairToolRuns(g.events).map((r, j) => (
            <ToolRun key={`t-${i}-${j}`} name={r.name} args={r.args} result={r.result} progress={r.progress} />
          ))
        )
      )}
    </div>
  )
}

export function ThinkingBlock({ text, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!text) return null
  return (
    <div className="thinking-block">
      <button type="button" className="thinking-head" onClick={() => setOpen((o) => !o)}>
        <Icon name="sparkles" size={13} />
        <span>Thinking</span>
        <span className={`thinking-chevron ${open ? 'open' : ''}`}>
          <Icon name="chevronDown" size={13} />
        </span>
      </button>
      {open && <div className="thinking-body">{text}</div>}
    </div>
  )
}

export function SubagentPanel({ members }) {
  const [openRun, setOpenRun] = useState(null)
  if (!members || !members.length) return null
  return (
    <div className="subagent-panel">
      {members.map((m, i) => (
        <div key={m.run_id || i} className="subagent-row">
          <button
            type="button"
            className="subagent-row-head"
            onClick={() => m.run_id && setOpenRun(openRun === m.run_id ? null : m.run_id)}
          >
            <span className={`subagent-dot ${m.status || 'running'}`} />
            <span className="subagent-name">{m.name || `agent ${i + 1}`}</span>
            <span className="subagent-title">{truncate(m.title || m.task || '', 64)}</span>
            <span className={`tool-run-badge ${m.status === 'error' ? 'error' : ''}`}>
              {m.status || 'running'}
            </span>
          </button>
          {m.summary && openRun !== m.run_id && (
            <div className="subagent-summary">{truncate(m.summary, 220)}</div>
          )}
          {openRun === m.run_id && <RunTimeline runId={m.run_id} />}
        </div>
      ))}
    </div>
  )
}

function parsedMembers(name, result) {
  if (!result?.preview) return null
  try {
    const data = JSON.parse(result.preview)
    if (name === 'run_swarm' && Array.isArray(data?.results)) {
      return data.results.map((r, i) => ({
        run_id: r.run_id,
        name: r.agent,
        index: r.index ?? i,
        status: r.status,
        summary: r.summary || r.error,
        title: r.task,
      }))
    }
    if (name === 'run_subagent' && data?.run_id) {
      return [{ run_id: data.run_id, name: data.agent, status: data.status, summary: data.summary }]
    }
  } catch (e) {
    return null
  }
  return null
}

export function ToolRun({ name, args, result, progress, members }) {
  const [open, setOpen] = useState(false)
  const delegation = members || parsedMembers(name, result)
  const status = !result ? 'running' : result.ok ? 'ok' : 'error'
  const label = status === 'running' ? 'Running' : status === 'ok' ? 'Done' : 'Failed'
  const summary = status === 'running' && progress ? progress : result ? result.preview : JSON.stringify(args)
  const image = resultImage(result)
  return (
    <div className={`tool-run ${status}`}>
      <button className="tool-run-head" onClick={() => setOpen((o) => !o)}>
        <span className="tool-run-icon">
          {status === 'running' ? (
            <Spinner size={14} />
          ) : (
            <Icon name={status === 'ok' ? 'check' : 'x'} size={14} />
          )}
        </span>
        <Icon name={TOOL_ICONS[name] || 'play'} size={14} className="tool-run-toolicon" />
        <span className="tool-run-name" title={TOOL_TITLES[name] || name}>
          {TOOL_TITLES[name] || name}
        </span>
        <span className="tool-run-arg">{truncate(summary, 72)}</span>
        <span className={`tool-run-badge ${status}`}>{label}</span>
        <span className={`tool-run-chevron ${open ? 'open' : ''}`}>
          <Icon name="chevronDown" size={14} />
        </span>
      </button>
      {delegation && delegation.length > 0 && <SubagentPanel members={delegation} />}
      {image && <img className="tool-run-image" src={image} alt={name} loading="lazy" />}
      {open && (
        <div className="tool-run-body">
          <div className="tool-run-section">
            <div className="tool-run-label">Arguments</div>
            <pre>{JSON.stringify(args, null, 2)}</pre>
          </div>
          {result && (
            <div className="tool-run-section">
              <div className="tool-run-label">{result.ok ? 'Result' : 'Error'}</div>
              <pre className={result.ok ? '' : 'err'}>{String(result.preview ?? '')}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function pairToolRuns(events) {
  const runs = []
  for (const evt of events) {
    if (evt.event === 'tool_call') {
      runs.push({ id: evt.id, name: evt.name, args: evt.arguments, result: null, progress: '' })
    } else if (evt.event === 'tool_result') {
      for (let i = runs.length - 1; i >= 0; i--) {
        if (runs[i].name === evt.name && !runs[i].result) {
          runs[i].result = evt
          break
        }
      }
    } else if (evt.event === 'tool_progress') {
      for (let i = runs.length - 1; i >= 0; i--) {
        if (!runs[i].result && (!evt.tool_call_id || runs[i].id === evt.tool_call_id)) {
          runs[i].progress = evt.text
          break
        }
      }
    }
  }
  return runs
}

export function parseToolArgs(value) {
  try {
    return typeof value === 'string' ? JSON.parse(value || '{}') : value || {}
  } catch (e) {
    return {}
  }
}

export function messageItems(rows) {
  const items = []
  let last = null
  for (const m of rows) {
    if (m.role === 'user') {
      items.push({ kind: 'user', id: m.id, content: m.content })
      last = null
      continue
    }
    if (m.role === 'tool') {
      if (last) {
        const run = last.runs.find((r) => !r.result && r.name === m.name)
        if (run) run.result = { ok: m.ok !== false, preview: m.content }
      }
      continue
    }
    if (m.role === 'notification') {
      items.push({ kind: 'notification', id: m.id, content: m.content })
      last = null
      continue
    }
    let calls = []
    try {
      calls = m.tool_calls ? JSON.parse(m.tool_calls) : []
    } catch (e) {
      calls = []
    }
    const item = {
      kind: 'assistant',
      id: m.id,
      content: m.content,
      thinking: m.thinking,
      runs: calls.map((c) => ({
        name: c.function?.name || c.name || 'tool',
        args: parseToolArgs(c.function?.arguments ?? c.arguments),
        result: null,
      })),
    }
    items.push(item)
    last = item
  }
  return items
}
