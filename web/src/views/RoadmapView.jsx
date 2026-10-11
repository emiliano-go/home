import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { Modal, ConfirmModal } from '../components/Modal.jsx'
import { ProgressBar, SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'
import { clickable } from '../lib/ui.js'
import { PRIORITY_LABEL } from './TasksView.jsx'

export function fmtDay(value) {
  if (!value) return null
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value)
  const d = dateOnly ? new Date(`${value}T00:00:00`) : new Date(value)
  return isNaN(d) ? value : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function MilestoneEditor({ milestone, projectId, onClose, onSaved }) {
  const isNew = !milestone.id
  const [title, setTitle] = useState(milestone.title || '')
  const [description, setDescription] = useState(milestone.description || '')
  const [targetDate, setTargetDate] = useState(milestone.target_date || '')
  const [status, setStatus] = useState(milestone.status || 'open')
  const [memories, setMemories] = useState(milestone.memories || [])
  const [q, setQ] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const search = (e) => {
    e.preventDefault()
    if (!q.trim()) return
    setSearching(true)
    api
      .searchMemory(projectId, q.trim())
      .then((r) => setResults(r || []))
      .catch(() => setResults([]))
      .finally(() => setSearching(false))
  }

  const addMemory = (m) => {
    if (!memories.some((x) => x.id === m.id)) {
      setMemories((prev) => [...prev, { id: m.id, title: m.title }])
    }
  }
  const removeMemory = (id) => setMemories((prev) => prev.filter((x) => x.id !== id))

  const save = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    const body = {
      title: title.trim(),
      description,
      target_date: targetDate || null,
      status,
      memories,
    }
    const req = isNew
      ? api.createMilestone(projectId, body)
      : api.updateMilestone(milestone.id, body)
    req
      .then(onSaved)
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  const remove = () => {
    if (isNew) return onClose()
    api.deleteMilestone(milestone.id).then(onSaved).catch((err) => setError(err.message))
  }

  return (
    <Modal title={isNew ? 'New milestone' : 'Edit milestone'} onClose={onClose}>
      <form className="agent-form" onSubmit={save}>
        <label className="field">
          <span className="field-label">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus required />
        </label>
        <label className="field">
          <span className="field-label">Description</span>
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What does this milestone deliver?"
          />
        </label>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Target date</span>
            <input type="date" value={targetDate || ''} onChange={(e) => setTargetDate(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="open">Open</option>
              <option value="done">Done</option>
            </select>
          </label>
        </div>

        <div className="field">
          <span className="field-label">Linked memories (Totem)</span>
          {memories.length > 0 && (
            <div className="link-chips">
              {memories.map((m) => (
                <span key={m.id} className="link-chip">
                  <Icon name="memory" size={12} />
                  {m.title || m.id}
                  <button type="button" onClick={() => removeMemory(m.id)} title="Unlink">
                    <Icon name="x" size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <form className="search-row compact" onSubmit={search}>
            <input
              placeholder="Search memory to link a decision or constraint..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button className="btn" disabled={searching}>
              {searching ? <Spinner size={14} /> : <Icon name="search" size={14} />}
            </button>
          </form>
          {results && results.length === 0 && (
            <span className="field-hint">No memories match.</span>
          )}
          {results && results.length > 0 && (
            <div className="search-results">
              {results.slice(0, 6).map((m) => (
                <button
                  type="button"
                  key={m.id}
                  className="search-result"
                  onClick={() => addMemory(m)}
                  disabled={memories.some((x) => x.id === m.id)}
                >
                  <span className="badge">{m.type}</span>
                  <span className="search-result-title">{m.title}</span>
                  <Icon name="plus" size={13} />
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={saving || !title.trim()}>
            {saving ? (
              <>
                <Spinner size={14} /> Saving
              </>
            ) : isNew ? (
              'Create milestone'
            ) : (
              'Save changes'
            )}
          </button>
          {!isNew && (
            <button type="button" className="btn danger" onClick={() => setConfirmDelete(true)}>
              Delete
            </button>
          )}
        </div>
        {error && <div className="error-text">{error}</div>}
        {confirmDelete && (
          <ConfirmModal
            title="Delete milestone"
            confirmLabel="Delete"
            danger
            onClose={() => setConfirmDelete(false)}
            onConfirm={() => {
              setConfirmDelete(false)
              remove()
            }}
          >
            <p className="note">
              Delete milestone <strong>{title.trim() || 'Untitled'}</strong>? Its tasks are kept,
              just unassigned.
            </p>
          </ConfirmModal>
        )}
      </form>
    </Modal>
  )
}

export const STATUS_DOT = { backlog: 'todo', todo: 'todo', doing: 'doing', review: 'review', done: 'done' }

export function RoadmapView({ projectId, onOpenTasks }) {
  const { data, error, loading, reload } = useAsync(
    () => api.listMilestones(projectId),
    [projectId]
  )
  const tasksReq = useAsync(() => api.listTasks(projectId), [projectId])
  const milestones = data || []
  const tasks = tasksReq.data || []
  const [editor, setEditor] = useState(null)

  const byMilestone = useMemo(() => {
    const map = {}
    for (const t of tasks) {
      if (t.milestone_id != null) (map[t.milestone_id] ||= []).push(t)
    }
    return map
  }, [tasks])
  const unassigned = tasks.filter((t) => t.milestone_id == null)

  const reopen = () => {
    reload()
    tasksReq.reload()
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <h2>Roadmap</h2>
        <button className="btn primary" onClick={() => setEditor({})}>
          <Icon name="plus" size={14} /> New milestone
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {loading ? (
        <div className="milestone-grid">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="block-skeleton" />
          ))}
        </div>
      ) : milestones.length === 0 ? (
        <SectionEmpty
          icon="flag"
          title="No milestones yet"
          hint="Group tasks into a goal and track progress toward it."
          action={
            <button className="btn" onClick={() => setEditor({})}>
              <Icon name="plus" size={14} /> Add a milestone
            </button>
          }
        />
      ) : (
        <div className="milestone-grid">
          {milestones.map((m) => {
            const list = byMilestone[m.id] || []
            return (
              <div
                key={m.id}
                className={`milestone ${m.status} clickable`}
                {...clickable(() => setEditor(m))}
              >
                <div className="milestone-head">
                  <div className="milestone-title-row">
                    <span className="milestone-title">{m.title}</span>
                    {m.status === 'done' && <span className="badge ok">done</span>}
                    {m.target_date && (
                      <span className="milestone-date">
                        <Icon name="clock" size={12} /> {fmtDay(m.target_date)}
                      </span>
                    )}
                  </div>
                  <button
                    className="icon-btn small"
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditor(m)
                    }}
                    title="Edit"
                  >
                    <Icon name="settings" size={15} />
                  </button>
                </div>
                {m.description && <div className="milestone-desc">{m.description}</div>}

                <div className="milestone-progress">
                  <ProgressBar percent={m.progress.percent} />
                  <span className="milestone-percent">
                    {m.progress.done}/{m.progress.total} · {m.progress.percent}%
                  </span>
                </div>

                {m.memories.length > 0 && (
                  <div className="link-chips">
                    {m.memories.map((mem) => (
                      <span key={mem.id} className="link-chip static">
                        <Icon name="memory" size={12} />
                        {mem.title || mem.id}
                      </span>
                    ))}
                  </div>
                )}

                {list.length > 0 ? (
                  <div className="milestone-tasks">
                    {list.map((t) => (
                      <div key={t.id} className="milestone-task">
                        <span className={`dot-status ${STATUS_DOT[t.status] || 'todo'}`} />
                        <span className="milestone-task-title">{t.title}</span>
                        <span className={`priority ${t.priority}`}>{PRIORITY_LABEL[t.priority]}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="milestone-empty">No tasks assigned yet.</div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {!loading && unassigned.length > 0 && (
        <div className="milestone-unassigned">
          <div className="home-section-head">
            <h2>Unassigned tasks</h2>
            <button className="link-btn" onClick={onOpenTasks}>
              <Icon name="tasks" size={13} /> Open board
            </button>
          </div>
          <div className="milestone-tasks">
            {unassigned.map((t) => (
              <div key={t.id} className="milestone-task">
                <span className={`dot-status ${STATUS_DOT[t.status] || 'todo'}`} />
                <span className="milestone-task-title">{t.title}</span>
                <span className={`priority ${t.priority}`}>{PRIORITY_LABEL[t.priority]}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {editor && (
        <MilestoneEditor
          projectId={projectId}
          milestone={editor}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null)
            reopen()
          }}
        />
      )}
    </div>
  )
}
