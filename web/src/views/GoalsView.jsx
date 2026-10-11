import { useState } from 'react'
import { api } from '../api.js'
import { Modal, ConfirmModal } from '../components/Modal.jsx'
import { ProgressBar, SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'
import { mdToHtml } from '../lib/markdown.js'
import { clickable } from '../lib/ui.js'

export const GOAL_STATUS_LABEL = {
  drafting: 'Drafting',
  active: 'Active',
  done: 'Done',
  dropped: 'Dropped',
}

export function GoalEditor({ goal, projectId, onClose, onSaved }) {
  const isNew = !goal.id
  const [title, setTitle] = useState(goal.title || '')
  const [description, setDescription] = useState(goal.description || '')
  const [criteria, setCriteria] = useState(goal.success_criteria || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const save = (e) => {
    e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    const body = {
      title: title.trim(),
      description,
      success_criteria: criteria,
    }
    const req = isNew ? api.createGoal(projectId, body) : api.updateGoal(goal.id, body)
    req
      .then(onSaved)
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  return (
    <Modal title={isNew ? 'New goal' : 'Edit goal'} onClose={onClose}>
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
            placeholder="What outcome do you want?"
          />
        </label>
        <label className="field">
          <span className="field-label">Success criteria</span>
          <textarea
            rows={2}
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            placeholder="How will you know it is done?"
          />
        </label>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={saving || !title.trim()}>
            {saving ? (
              <>
                <Spinner size={14} /> Saving
              </>
            ) : isNew ? (
              'Create goal'
            ) : (
              'Save changes'
            )}
          </button>
        </div>
        {error && <div className="error-text">{error}</div>}
      </form>
    </Modal>
  )
}

export function GoalsView({ projectId, onDiscuss, onOpenTasks, onOpenFile }) {
  const { data, error, loading, reload } = useAsync(() => api.listGoals(projectId), [projectId])
  const goals = data || []
  const [editor, setEditor] = useState(null)
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [report, setReport] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const act = (goal, kind) => {
    setBusy(goal.id)
    setActionError(null)
    const call = kind === 'plan' ? api.planGoal : api.convergeGoal
    call(goal.id)
      .then((r) => {
        setReport({ ...r, goal, kind })
        reload()
      })
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setBusy(null))
  }

  const discuss = (goal) => {
    setActionError(null)
    api
      .discussGoal(goal.id)
      .then((r) => onDiscuss(r.session_id, r.seed))
      .catch((e) => setActionError(e.message || String(e)))
  }

  const setStatus = (goal, status) => {
    setActionError(null)
    api.updateGoal(goal.id, { status }).then(reload).catch((e) => setActionError(e.message))
  }

  const remove = (goal) => {
    api.deleteGoal(goal.id).then(reload).catch((e) => setActionError(e.message))
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Goals</h2>
          <p className="note">
            Discuss a goal with the agent, keep a spec in the workspace, then generate a milestone
            and an ordered task board from it.
          </p>
        </div>
        <button className="btn primary" onClick={() => setEditor({})}>
          <Icon name="plus" size={14} /> New goal
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}
      {actionError && <p className="error-text">{actionError}</p>}
      {loading ? (
        <div className="home-list">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="row-skeleton" />
          ))}
        </div>
      ) : goals.length === 0 ? (
        <SectionEmpty
          icon="sparkles"
          title="No goals yet"
          hint="Create one, discuss it with the agent, then generate the board."
        />
      ) : (
        <div className="goal-list">
          {goals.map((goal) => (
            <div
              key={goal.id}
              className="goal-card clickable"
              {...clickable(() => setEditor(goal))}
            >
              <div className="goal-head">
                <span className="goal-title">{goal.title}</span>
                <select
                  className="goal-status"
                  value={goal.status}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setStatus(goal, e.target.value)}
                >
                  {Object.entries(GOAL_STATUS_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              {goal.description && <div className="goal-desc">{goal.description}</div>}
              {goal.success_criteria && (
                <div className="goal-criteria">
                  <strong>Success:</strong> {goal.success_criteria}
                </div>
              )}
              {goal.progress && goal.progress.total > 0 && (
                <div className="goal-progress">
                  <ProgressBar percent={goal.progress.percent} />
                  <span className="muted">
                    {goal.progress.done}/{goal.progress.total} tasks
                  </span>
                </div>
              )}
              <div className="row goal-actions" onClick={(e) => e.stopPropagation()}>
                <button className="btn" onClick={() => discuss(goal)}>
                  <Icon name="chat" size={13} /> Discuss
                </button>
                <button
                  className="btn primary"
                  disabled={busy === goal.id}
                  onClick={() => act(goal, 'plan')}
                >
                  {busy === goal.id ? (
                    <>
                      <Spinner size={13} /> Working
                    </>
                  ) : (
                    <>
                      <Icon name="tasks" size={13} /> Generate board
                    </>
                  )}
                </button>
                <button className="btn" disabled={busy === goal.id} onClick={() => act(goal, 'converge')}>
                  <Icon name="check" size={13} /> Converge
                </button>
                {goal.spec_path && (
                  <button
                    className="btn"
                    onClick={() => onOpenFile({ project_id: projectId, path: goal.spec_path })}
                  >
                    <Icon name="files" size={13} /> Spec
                  </button>
                )}
                {goal.milestone_id && (
                  <button className="btn" onClick={onOpenTasks}>
                    <Icon name="flag" size={13} /> Board
                  </button>
                )}
                <button className="btn" onClick={() => setEditor(goal)}>
                  Edit
                </button>
                <button className="btn danger" onClick={() => setDeleteTarget(goal)}>
                  <Icon name="x" size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editor && (
        <GoalEditor
          projectId={projectId}
          goal={editor}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null)
            reload()
          }}
        />
      )}

      {deleteTarget && (
        <ConfirmModal
          title="Delete goal"
          confirmLabel="Delete"
          danger
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => {
            const goal = deleteTarget
            setDeleteTarget(null)
            remove(goal)
          }}
        >
          <p className="note">
            Delete goal <strong>{deleteTarget.title}</strong>? Tasks and milestone stay on the
            board.
          </p>
        </ConfirmModal>
      )}

      {report && (
        <Modal title={report.kind === 'plan' ? 'Board generated' : 'Converge report'} onClose={() => setReport(null)}>
          <div
            className="reader-body prose"
            dangerouslySetInnerHTML={{ __html: mdToHtml(report.report || '') }}
          />
          {report.spec_path && (
            <p className="note">
              Spec: <code>{report.spec_path}</code>
              {report.plan_path && (
                <>
                  {' '}· Plan: <code>{report.plan_path}</code>
                </>
              )}
            </p>
          )}
          <div className="row" style={{ marginTop: 14, marginBottom: 0 }}>
            <button
              className="btn"
              onClick={() => {
                setReport(null)
                if (onOpenTasks) onOpenTasks()
              }}
            >
              <Icon name="tasks" size={14} /> View board
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
