import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { Modal, ConfirmModal } from '../components/Modal.jsx'
import { Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate, truncate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'
import { mdToHtml } from '../lib/markdown.js'

export const TASK_COLUMNS = [
  { key: 'backlog', label: 'Backlog' },
  { key: 'todo', label: 'To do' },
  { key: 'doing', label: 'In progress' },
  { key: 'review', label: 'Review' },
  { key: 'done', label: 'Done' },
]

export const PRIORITY_LABEL = { low: 'Low', medium: 'Medium', high: 'High' }

export function dueInfo(due) {
  if (!due) return null
  const d = new Date(due)
  if (Number.isNaN(d.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((d - today) / 86400000)
  return {
    text: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    overdue: d < today,
    soon: days >= 0 && days <= 2,
  }
}

export function TaskEditor({ task, projectId, onClose, onSaved, onImplement, gitWrites }) {
  const isNew = !task.id
  const [title, setTitle] = useState(task.title || '')
  const [description, setDescription] = useState(task.description || '')
  const [status, setStatus] = useState(task.status || 'backlog')
  const [priority, setPriority] = useState(task.priority || 'medium')
  const [milestoneId, setMilestoneId] = useState(task.milestone_id || '')
  const [dueDate, setDueDate] = useState((task.due_at || '').slice(0, 10))
  const [dependsOn, setDependsOn] = useState(task.depends_on || [])
  const [acceptance, setAcceptance] = useState(task.acceptance || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [commentBody, setCommentBody] = useState('')
  const [posting, setPosting] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [running, setRunning] = useState(false)
  const [issueNumber, setIssueNumber] = useState(task.github_issue || null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pendingDone, setPendingDone] = useState(null)
  const milestonesReq = useAsync(() => api.listMilestones(projectId), [projectId])
  const milestones = milestonesReq.data || []
  const tasksReq = useAsync(() => api.listTasks(projectId), [projectId])
  const otherTasks = (tasksReq.data || []).filter((t) => t.id !== task.id)
  const commentsReq = useAsync(
    () => (task.id ? api.listComments(task.id) : Promise.resolve([])),
    [task.id]
  )
  const comments = commentsReq.data || []

  const toggleDep = (id) => {
    setDependsOn((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    )
  }

  const postComment = (e) => {
    e.preventDefault()
    if (!commentBody.trim()) return
    setPosting(true)
    api
      .addComment(task.id, { body: commentBody.trim() })
      .then(() => {
        setCommentBody('')
        commentsReq.reload()
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setPosting(false))
  }

  const implement = () => {
    const brief = [
      `Implement this task from the project board.`,
      ``,
      `## Task #${task.id}: ${task.title}`,
      description || '(no description)',
      ``,
      `Acceptance criteria: ${acceptance || '(none)'}`,
      ...(task.blocked_by?.length ? [`Blocked by: task ${task.blocked_by.join(', ')}`] : []),
      ...(comments.length
        ? [``, `Comments:`, ...comments.map((c) => `- ${c.author}: ${c.body}`)]
        : []),
      ``,
      `When you are done, leave a comment with task_comment and move the task to review with task_update.`,
    ].join('\n')
    api.updateTask(task.id, { status: 'doing' }).catch(() => {})
    onImplement(brief)
  }

  const runInBackground = () => {
    setRunning(true)
    setError(null)
    api
      .implementTask(task.id)
      .then(() => {
        onSaved?.()
        onClose()
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setRunning(false))
  }

  const syncIssue = () => {
    setSyncing(true)
    setError(null)
    api
      .syncIssues(projectId, { task_ids: [task.id] })
      .then((r) => {
        const created = (r.created || [])[0]
        if (created) setIssueNumber(created.issue)
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSyncing(false))
  }

  const save = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    const body = {
      title: title.trim(),
      description,
      acceptance,
      status,
      priority,
      milestone_id: milestoneId ? parseInt(milestoneId, 10) : 0,
      depends_on: dependsOn,
      due_at: dueDate || '',
    }
    if (!isNew && status === 'done' && task.status !== 'done' && acceptance.trim()) {
      setPendingDone(body)
      return
    }
    submitUpdate(body)
  }

  const submitUpdate = (body) => {
    setSaving(true)
    setError(null)
    const req = isNew
      ? api.createTask(projectId, body)
      : api.updateTask(task.id, body)
    req
      .then(onSaved)
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  const remove = () => {
    if (isNew) return onClose()
    api.deleteTask(task.id).then(onSaved).catch((err) => setError(err.message))
  }

  return (
    <Modal title={isNew ? 'New task' : 'Edit task'} onClose={onClose}>
      <form className="agent-form" onSubmit={save}>
        <label className="field">
          <span className="field-label">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus required />
        </label>
        <label className="field">
          <span className="field-label">Description</span>
          <textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional detail, links..."
          />
        </label>
        <label className="field">
          <span className="field-label">Acceptance criteria</span>
          <textarea
            rows={2}
            value={acceptance}
            onChange={(e) => setAcceptance(e.target.value)}
            placeholder="How do we verify this is done? (gates the Done column)"
          />
        </label>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Column</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              {TASK_COLUMNS.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Priority</span>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              {Object.entries(PRIORITY_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Due date</span>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">Milestone</span>
            <select value={milestoneId} onChange={(e) => setMilestoneId(e.target.value)}>
              <option value="">No milestone</option>
              {milestones.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        {otherTasks.length > 0 && (
          <div className="field">
            <span className="field-label">Blocked by</span>
            <div className="dep-list">
              {otherTasks.map((t) => (
                <label key={t.id} className="dep-item">
                  <input
                    type="checkbox"
                    checked={dependsOn.includes(t.id)}
                    onChange={() => toggleDep(t.id)}
                  />
                  <span className="dep-title">{t.title}</span>
                  <span className={`badge ${t.status === 'done' ? 'ok' : ''}`}>{t.status}</span>
                </label>
              ))}
            </div>
            <span className="field-hint">
              This task is blocked until every selected task is done.
            </span>
          </div>
        )}
        {!isNew && (
          <div className="field">
            <span className="field-label">Comments</span>
            <div className="comment-list">
              {comments.length === 0 && <div className="field-hint">No comments yet.</div>}
              {comments.map((c) => (
                <div key={c.id} className="comment-row">
                  <span className="comment-author">{c.author}</span>
                  <span className="comment-body">{c.body}</span>
                  <span className="comment-time">{relDate(c.created_at)}</span>
                </div>
              ))}
            </div>
            <div className="row" style={{ marginBottom: 0 }}>
              <input
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                placeholder="Leave a note for the next session..."
              />
              <button
                type="button"
                className="btn"
                disabled={posting || !commentBody.trim()}
                onClick={postComment}
              >
                {posting ? <Spinner size={13} /> : 'Comment'}
              </button>
            </div>
          </div>
        )}
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={saving || !title.trim()}>
            {saving ? (
              <>
                <Spinner size={14} /> Saving
              </>
            ) : isNew ? (
              'Create task'
            ) : (
              'Save changes'
            )}
          </button>
          {!isNew && onImplement && (
            <button type="button" className="btn" onClick={implement}>
              <Icon name="sparkles" size={14} /> Implement with agent
            </button>
          )}
          {!isNew && gitWrites && (
            <button type="button" className="btn" disabled={running} onClick={runInBackground}>
              {running ? (
                <>
                  <Spinner size={13} /> Starting
                </>
              ) : (
                <>
                  <Icon name="play" size={14} /> Run in background
                </>
              )}
            </button>
          )}
          {task.pr_url && (
            <a className="note" href={task.pr_url} target="_blank" rel="noreferrer">
              Pull request
            </a>
          )}
          {!isNew && gitWrites && !issueNumber && (
            <button type="button" className="btn" disabled={syncing} onClick={syncIssue}>
              {syncing ? (
                <>
                  <Spinner size={13} /> Pushing
                </>
              ) : (
                <>
                  <Icon name="git" size={14} /> Push to GitHub
                </>
              )}
            </button>
          )}
          {issueNumber && <span className="badge">issue #{issueNumber}</span>}
          {!isNew && (
            <button type="button" className="btn danger" onClick={() => setConfirmDelete(true)}>
              Delete
            </button>
          )}
        </div>
        {error && <div className="error-text">{error}</div>}
        {confirmDelete && (
          <ConfirmModal
            title="Delete task"
            confirmLabel="Delete"
            danger
            onClose={() => setConfirmDelete(false)}
            onConfirm={() => {
              setConfirmDelete(false)
              remove()
            }}
          >
            <p className="note">
              Delete task <strong>{title.trim() || 'Untitled'}</strong>? This cannot be undone.
            </p>
          </ConfirmModal>
        )}
        {pendingDone && (
          <ConfirmModal
            title="Mark task done"
            confirmLabel="Confirm review"
            onClose={() => setPendingDone(null)}
            onConfirm={() => {
              const body = { ...pendingDone, reviewed: true }
              setPendingDone(null)
              submitUpdate(body)
            }}
          >
            <p className="note">Acceptance criteria:</p>
            <pre style={{ whiteSpace: 'pre-wrap' }}>{acceptance}</pre>
            <p className="note">Confirm the review and mark this task done?</p>
          </ConfirmModal>
        )}
      </form>
    </Modal>
  )
}

export function TasksView({ projectId, onImplement, gitWrites }) {
  const { data, error, loading, reload } = useAsync(() => api.listTasks(projectId), [projectId])
  const [tasks, setTasks] = useState([])
  const [dragId, setDragId] = useState(null)
  const [editor, setEditor] = useState(null)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestReport, setSuggestReport] = useState(null)
  const [suggestError, setSuggestError] = useState(null)
  const [runningNext, setRunningNext] = useState(false)

  // Let a vertical mouse wheel scroll the board horizontally.
  const wheelCleanup = useRef(null)
  const kanbanRef = useCallback((el) => {
    wheelCleanup.current?.()
    wheelCleanup.current = null
    if (!el) return
    const onWheel = (e) => {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
      const max = el.scrollWidth - el.clientWidth
      if (max <= 0) return
      if ((e.deltaY < 0 && el.scrollLeft <= 0) || (e.deltaY > 0 && el.scrollLeft >= max - 1)) return
      e.preventDefault()
      el.scrollLeft += e.deltaY
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    wheelCleanup.current = () => el.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => () => wheelCleanup.current?.(), [])

  const runNext = () => {
    setRunningNext(true)
    setSuggestError(null)
    api
      .runNextTask(projectId)
      .then(() => reload())
      .catch((e) => setSuggestError(e.message || String(e)))
      .finally(() => setRunningNext(false))
  }

  const suggest = () => {
    setSuggesting(true)
    setSuggestError(null)
    setSuggestReport(null)
    api
      .suggestTasks(projectId)
      .then((r) => {
        setSuggestReport(r)
        reload()
      })
      .catch((e) => setSuggestError(e.message || String(e)))
      .finally(() => setSuggesting(false))
  }

  useEffect(() => {
    if (data) setTasks(data)
  }, [data])

  const columns = useMemo(() => {
    const sorted = [...tasks].sort((a, b) => a.position - b.position)
    return TASK_COLUMNS.map((col) => ({
      ...col,
      tasks: sorted.filter((t) => t.status === col.key),
    }))
  }, [tasks])

  const move = (taskId, status, beforeTask = null) => {
    const task = tasks.find((t) => t.id === taskId)
    if (!task) return
    const siblings = tasks
      .filter((t) => t.status === status && t.id !== taskId)
      .sort((a, b) => a.position - b.position)
    let position
    if (beforeTask) {
      const idx = siblings.findIndex((t) => t.id === beforeTask.id)
      const prev = siblings[idx - 1]
      const next = siblings[idx] || beforeTask
      position = prev ? (prev.position + next.position) / 2 : next.position - 1
    } else {
      position = siblings.length ? siblings[siblings.length - 1].position + 1 : 0
    }
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status, position } : t))
    )
    api.updateTask(taskId, { status, position }).then(reload).catch(() => reload())
  }

  const onDropColumn = (e, status) => {
    e.preventDefault()
    if (dragId != null) move(dragId, status)
    setDragId(null)
  }

  const onDropCard = (e, card) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragId != null && dragId !== card.id) move(dragId, card.status, card)
    setDragId(null)
  }

  return (
    <div className="tasks">
      <div className="page-head">
        <h2>Tasks</h2>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn" disabled={suggesting} onClick={suggest}>
            {suggesting ? (
              <>
                <Spinner size={13} /> Thinking
              </>
            ) : (
              <>
                <Icon name="sparkles" size={14} /> Suggest next work
              </>
            )}
          </button>
          {gitWrites && (
            <button className="btn" disabled={runningNext} onClick={runNext}>
              {runningNext ? (
                <>
                  <Spinner size={13} /> Starting
                </>
              ) : (
                <>
                  <Icon name="play" size={14} /> Run next
                </>
              )}
            </button>
          )}
          <button className="btn primary" onClick={() => setEditor({ status: 'backlog' })}>
            <Icon name="plus" size={14} /> New task
          </button>
        </div>
      </div>
      {suggestError && <p className="error-text">{suggestError}</p>}
      {error && <p className="error-text">{error}</p>}
      {loading ? (
        <div className="kanban" ref={kanbanRef}>
          {TASK_COLUMNS.map((c) => (
            <div key={c.key} className="kanban-col">
              <Skeleton className="row-skeleton" />
              <Skeleton className="row-skeleton" style={{ marginTop: 8 }} />
            </div>
          ))}
        </div>
      ) : (
        <div className="kanban" ref={kanbanRef}>
          {columns.map((col) => (
            <div
              key={col.key}
              className={`kanban-col ${dragId != null ? 'droppable' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => onDropColumn(e, col.key)}
            >
              <div className="kanban-col-head">
                <span className="kanban-col-title">{col.label}</span>
                <span className="kanban-count">{col.tasks.length}</span>
              </div>
              <div className="kanban-cards">
                {col.tasks.map((t) => (
                  <div
                    key={t.id}
                    className={`kanban-card ${dragId === t.id ? 'dragging' : ''}`}
                    draggable
                    onDragStart={() => setDragId(t.id)}
                    onDragEnd={() => setDragId(null)}
                    onDrop={(e) => onDropCard(e, t)}
                    onClick={() => setEditor(t)}
                  >
                    <div className="kanban-card-title">{t.title}</div>
                    {t.blocked_by?.length > 0 && (
                      <div className="kanban-card-blocked">
                        <span className="badge err" title={`Blocked by task ${t.blocked_by.join(', ')}`}>
                          blocked
                        </span>
                      </div>
                    )}
                    {t.description && (
                      <div className="kanban-card-desc">{truncate(t.description, 120)}</div>
                    )}
                    <div className="kanban-card-foot">
                      <span className={`priority ${t.priority}`}>
                        {PRIORITY_LABEL[t.priority]}
                      </span>
                      {t.source === 'suggested' && <span className="badge accent">suggested</span>}
                      {(() => {
                        const dl = dueInfo(t.due_at)
                        return (
                          dl && (
                            <span
                              className={`due-chip ${dl.overdue ? 'overdue' : dl.soon ? 'soon' : ''}`}
                              title="Due date"
                            >
                              <Icon name="clock" size={11} /> {dl.text}
                            </span>
                          )
                        )
                      })()}
                      {t.pr_url && (
                        <a
                          className="due-chip"
                          href={t.pr_url}
                          target="_blank"
                          rel="noreferrer"
                          title="Pull request"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Icon name="git" size={11} /> PR
                        </a>
                      )}
                      <span className="kanban-card-time">{relDate(t.updated_at)}</span>
                    </div>
                  </div>
                ))}
                <button
                  className="kanban-add"
                  onClick={() => setEditor({ status: col.key })}
                >
                  <Icon name="plus" size={13} /> Add
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {editor && (
        <TaskEditor
          projectId={projectId}
          task={editor}
          onImplement={onImplement}
          gitWrites={gitWrites}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null)
            reload()
          }}
        />
      )}

      {suggestReport && (
        <Modal title="Suggested next work" onClose={() => setSuggestReport(null)}>
          <div
            className="reader-body prose"
            dangerouslySetInnerHTML={{ __html: mdToHtml(suggestReport.report || '') }}
          />
          <p className="note">
            {suggestReport.task_ids?.length || 0} tasks added to backlog, tagged suggested.
          </p>
        </Modal>
      )}
    </div>
  )
}
