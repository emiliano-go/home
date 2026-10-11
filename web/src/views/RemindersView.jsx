import { useState } from 'react'
import { api } from '../api.js'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'

export function reminderDue(value) {
  const d = new Date(value)
  return isNaN(d) ? null : d
}

export function RemindersView({ projects }) {
  const { data, error, loading, reload } = useAsync(() => api.listReminders(false), [])
  const reminders = data || []
  const [editor, setEditor] = useState(false)
  const [formError, setFormError] = useState(null)

  const act = (fn) => {
    setFormError(null)
    fn().then(reload).catch((err) => setFormError(err.message || String(err)))
  }

  const now = Date.now()

  return (
    <div className="center-col wide">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Reminders</h2>
          <p className="note">Notifications fire when due.</p>
        </div>
        <button className="btn primary" onClick={() => setEditor(true)}>
          <Icon name="plus" size={14} /> New reminder
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {formError && <p className="error-text">{formError}</p>}

      {loading ? (
        <div className="home-list">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="row-skeleton" />
          ))}
        </div>
      ) : reminders.length === 0 ? (
        <SectionEmpty
          icon="clock"
          title="No reminders"
          hint="Ask the agent to remind you, or create one."
        />
      ) : (
        <div className="home-list">
          {reminders.map((r) => {
            const d = reminderDue(r.due_at)
            const overdue = d && d.getTime() < now
            return (
              <div key={r.id} className="reminder-row">
                <span className={`home-row-icon ${overdue ? 'overdue' : ''}`}>
                  <Icon name="clock" size={15} />
                </span>
                <span className="home-row-main">
                  <span className="home-row-title">{r.text}</span>
                  <span className="home-row-sub">
                    {d ? d.toLocaleString() : r.due_at}
                    {r.recurrence !== 'none' ? `, repeats ${r.recurrence}` : ''}
                    {r.project_id ? `, project #${r.project_id}` : ''}
                  </span>
                </span>
                <button className="btn" onClick={() => act(() => api.updateReminder(r.id, { snooze_minutes: 10 }))}>
                  +10m
                </button>
                <button className="btn" onClick={() => act(() => api.updateReminder(r.id, { snooze_minutes: 1440 }))}>
                  +1d
                </button>
                <button className="btn" onClick={() => act(() => api.updateReminder(r.id, { status: 'done' }))}>
                  <Icon name="check" size={13} />
                </button>
                <button className="btn danger" onClick={() => act(() => api.deleteReminder(r.id))}>
                  <Icon name="x" size={13} />
                </button>
              </div>
            )
          })}
        </div>
      )}

      {editor && (
        <ReminderEditor
          projects={projects}
          onClose={() => setEditor(false)}
          onSaved={() => {
            setEditor(false)
            reload()
          }}
        />
      )}
    </div>
  )
}

export function ReminderEditor({ projects, onClose, onSaved }) {
  const [text, setText] = useState('')
  const [due, setDue] = useState('')
  const [recurrence, setRecurrence] = useState('none')
  const [projectId, setProjectId] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState(null)

  const add = (e) => {
    e.preventDefault()
    if (!text.trim() || !due) return
    setSaving(true)
    setFormError(null)
    api
      .createReminder({
        text: text.trim(),
        due_at: new Date(due).toISOString(),
        recurrence,
        project_id: projectId ? Number(projectId) : null,
      })
      .then(onSaved)
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  return (
    <Modal title="New reminder" onClose={onClose}>
      <form className="agent-form" onSubmit={add}>
        <div className="field-row">
          <label className="field">
            <span className="field-label">What</span>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Review the PR" />
          </label>
          <label className="field">
            <span className="field-label">When</span>
            <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Repeat</span>
            <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)}>
              <option value="none">Once</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Project</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">None</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={saving || !text.trim() || !due}>
            {saving ? <Spinner size={13} /> : 'Add reminder'}
          </button>
        </div>
        {formError && <p className="error-text">{formError}</p>}
      </form>
    </Modal>
  )
}

export function UpcomingReminders({ onNavigate }) {
  const { data } = useAsync(() => api.listReminders(false), [])
  const reminders = (data || []).slice(0, 3)
  if (reminders.length === 0) return null
  return (
    <section className="home-section">
      <div className="home-section-head">
        <h2>Upcoming reminders</h2>
        <button className="link-btn" onClick={() => onNavigate({ type: 'reminders' })}>
          <Icon name="clock" size={13} /> All reminders
        </button>
      </div>
      <div className="home-list">
        {reminders.map((r) => (
          <div key={r.id} className="home-row">
            <span className="home-row-icon">
              <Icon name="clock" size={15} />
            </span>
            <span className="home-row-main">
              <span className="home-row-title">{r.text}</span>
              <span className="home-row-sub">{reminderDue(r.due_at)?.toLocaleString() || r.due_at}</span>
            </span>
            <span className="home-row-time">{relDate(r.due_at)}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
