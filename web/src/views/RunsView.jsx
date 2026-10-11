import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Icon } from '../icons.jsx'

const ACTIVE = ['running', 'queued']
const KIND_LABEL = {
  chat: 'Chat',
  subagent: 'Subagent',
  'memory-writer': 'Memory writer',
  background: 'Background',
}

function elapsed(run) {
  if (!run.started_at) return ''
  const start = new Date(run.started_at)
  const end = run.finished_at ? new Date(run.finished_at) : new Date()
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function tokens(run) {
  const t = run.tokens || {}
  const total = (t.prompt_tokens || 0) + (t.completion_tokens || 0)
  return total > 0 ? `${total} tokens` : ''
}

export function RunsView({ projects = [], onOpenSession }) {
  const [runs, setRuns] = useState([])
  const [error, setError] = useState(null)

  const load = () =>
    api
      .listRuns()
      .then(setRuns)
      .catch((e) => setError(e.message || String(e)))

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!runs.some((r) => ACTIVE.includes(r.status))) return
    const timer = setInterval(load, 2000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs])

  const stop = (id) =>
    api.stopRun(id).then(load).catch((e) => setError(e.message || String(e)))
  const projectName = (id) => projects.find((p) => p.id === id)?.name || ''

  const card = (r) => {
    const active = ACTIVE.includes(r.status)
    const progress = active && r.last_event?.text ? r.last_event.text : ''
    return (
      <div key={r.id} className="card">
        <h3>
          <span className={`badge ${active ? 'accent' : r.status === 'done' ? '' : 'err'}`}>
            {r.status}
          </span>
          <span className="badge">{KIND_LABEL[r.kind] || r.kind}</span>
          {r.title || r.id.slice(0, 8)}
        </h3>
        <div className="meta">
          {[projectName(r.project_id), r.parent_run_id && 'child run', elapsed(r), r.steps && `${r.steps} steps`, tokens(r)]
            .filter(Boolean)
            .join(' · ')}
        </div>
        {progress && <div className="meta run-progress">{progress}</div>}
        {r.error ? (
          <div className="meta job-result err">{r.error}</div>
        ) : (
          r.result && <div className="meta job-result">{r.result}</div>
        )}
        <div className="row" style={{ marginTop: 8, marginBottom: 0 }}>
          {active && (
            <button className="btn" onClick={() => stop(r.id)}>
              <Icon name="stop" size={13} /> Stop
            </button>
          )}
          {r.session_id && r.project_id && (
            <button
              className="btn"
              onClick={() => onOpenSession && onOpenSession(r.project_id, r.session_id)}
            >
              <Icon name="chat" size={13} /> Open chat
            </button>
          )}
        </div>
      </div>
    )
  }

  const active = runs.filter((r) => ACTIVE.includes(r.status))
  const recent = runs.filter((r) => !ACTIVE.includes(r.status))

  return (
    <div className="center-col">
      <div className="page-head">
        <h2>Runs</h2>
        <span className="muted">chat turns, subagents, and background tasks</span>
      </div>
      {error && <p className="error-text">{error}</p>}
      {runs.length === 0 && <p className="empty">Nothing has run yet.</p>}
      {active.length > 0 && (
        <>
          <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
            Active
          </h3>
          <div className="cards">{active.map(card)}</div>
        </>
      )}
      {recent.length > 0 && (
        <>
          <h3 className="faint" style={{ fontSize: 13, fontWeight: 600, marginTop: 18 }}>
            Recent
          </h3>
          <div className="cards">{recent.slice(0, 30).map(card)}</div>
        </>
      )}
    </div>
  )
}
