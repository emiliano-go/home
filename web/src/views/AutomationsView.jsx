import { useState } from 'react'
import { api } from '../api.js'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'

export const SCHEDULE_ACTIONS = [
  'github-scan',
  'code-reviewer',
  'memory-keeper',
  'docs',
  'explore',
  'writer',
  'chat',
]

export const SCHEDULE_INTERVALS = [
  { label: 'Every 6 hours', minutes: 360 },
  { label: 'Daily', minutes: 1440 },
  { label: 'Weekly', minutes: 10080 },
]

export const SCHEDULE_EVENTS = [
  ['ci_failure', 'CI failure'],
  ['pr_opened', 'Pull request opened'],
  ['issue_opened', 'Issue opened'],
  ['watch_hit', 'Watch matched'],
  ['task_review', 'Task entered review'],
  ['task_done', 'Task completed'],
]

export const SCHEDULE_PRESETS = [
  {
    label: 'Nightly repo digest',
    action: 'github-scan',
    interval_minutes: 1440,
    instruction:
      'Summarize what changed in this repository in the last 24 hours: commits, open pull requests, issues, and CI failures. Write the digest to the workspace at digests/{date}.md with workspace_write, then report the path and highlights.',
  },
  {
    label: 'Daily PR review',
    action: 'code-reviewer',
    interval_minutes: 1440,
    instruction:
      'Review the open pull requests on GitHub. For each, summarize the change and flag risks ordered by severity. Write the review to the workspace at reviews/{date}.md with workspace_write, then report.',
  },
  {
    label: 'Weekly memory curation',
    action: 'memory-keeper',
    interval_minutes: 10080,
    instruction:
      'Review Totem project memory: find stale or wrong entries, duplicates, and missing decisions worth recording. Fix what is clearly wrong and create what is missing, then report every change.',
  },
]

export function intervalLabel(minutes) {
  if (minutes % 10080 === 0) return `${minutes / 10080}w`
  if (minutes % 1440 === 0) return `${minutes / 1440}d`
  if (minutes % 60 === 0) return `${minutes / 60}h`
  return `${minutes}m`
}

export function AutomationsView({ projectId }) {
  const { data, error, loading, reload } = useAsync(
    () => api.listSchedules(projectId),
    [projectId]
  )
  const schedules = data || []
  const [editor, setEditor] = useState(false)
  const [running, setRunning] = useState(null)
  const [actionError, setActionError] = useState(null)

  const act = (fn) => {
    setActionError(null)
    fn().then(reload).catch((err) => setActionError(err.message || String(err)))
  }

  const runNow = (schedule) => {
    setRunning(schedule.id)
    setActionError(null)
    api
      .runSchedule(schedule.id)
      .then(reload)
      .catch((err) => setActionError(err.message || String(err)))
      .finally(() => setRunning(null))
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Automations</h2>
          <p className="note">Scheduled agent runs, checked every few minutes.</p>
        </div>
        <button className="btn primary" onClick={() => setEditor(true)}>
          <Icon name="plus" size={14} /> New automation
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
      ) : schedules.length === 0 ? (
        <SectionEmpty
          icon="clock"
          title="No automations yet"
          hint="Create a recurring agent run, or start from a preset."
        />
      ) : (
        <div className="sched-list">
          {schedules.map((s) => (
            <div key={s.id} className={`sched-row ${s.enabled ? '' : 'off'}`}>
              <label className="sched-toggle" title={s.enabled ? 'Disable' : 'Enable'}>
                <input
                  type="checkbox"
                  checked={s.enabled}
                  onChange={() => act(() => api.updateSchedule(s.id, { enabled: !s.enabled }))}
                />
              </label>
              <div className="sched-main">
                <div className="sched-title">
                  <span className="badge">{s.action}</span>
                  <span className="muted">
                    {s.trigger === 'event'
                      ? `when ${(SCHEDULE_EVENTS.find((e) => e[0] === s.event) || [null, s.event])[1]}`
                      : `every ${intervalLabel(s.interval_minutes)}`}
                  </span>
                  {s.last_status && (
                    <span className={`badge ${s.last_status === 'ok' ? 'ok' : 'err'}`}>
                      {s.last_status}
                    </span>
                  )}
                  {s.last_run_at && <span className="muted">last {relDate(s.last_run_at)}</span>}
                </div>
                <div className="sched-instruction">{s.instruction || '(no instruction)'}</div>
                {s.last_report && (
                  <details className="sched-report">
                    <summary>Last report</summary>
                    <pre>{s.last_report}</pre>
                  </details>
                )}
              </div>
              <button className="btn" disabled={running === s.id} onClick={() => runNow(s)}>
                {running === s.id ? (
                  <>
                    <Spinner size={13} /> Running
                  </>
                ) : (
                  <>
                    <Icon name="play" size={13} /> Run now
                  </>
                )}
              </button>
              <button
                className="btn danger"
                title="Delete"
                onClick={() => act(() => api.deleteSchedule(s.id))}
              >
                <Icon name="x" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {editor && (
        <AutomationEditor
          projectId={projectId}
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

export function AutomationEditor({ projectId, onClose, onSaved }) {
  const [form, setForm] = useState({
    action: 'github-scan',
    interval_minutes: 1440,
    instruction: '',
    trigger: 'interval',
    event: 'ci_failure',
    event_filter: '',
  })
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState(null)

  const add = (e) => {
    e.preventDefault()
    setSaving(true)
    setFormError(null)
    api
      .createSchedule(projectId, form)
      .then(onSaved)
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  return (
    <Modal title="New automation" onClose={onClose}>
      <form className="agent-form" onSubmit={add}>
        <div className="row">
          {SCHEDULE_PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="btn"
              onClick={() =>
                setForm({
                  action: p.action,
                  interval_minutes: p.interval_minutes,
                  instruction: p.instruction,
                  trigger: 'interval',
                  event: 'ci_failure',
                  event_filter: '',
                })
              }
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Action</span>
            <select
              value={form.action}
              onChange={(e) => setForm({ ...form, action: e.target.value })}
            >
              {SCHEDULE_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Trigger</span>
            <select
              value={form.trigger}
              onChange={(e) => setForm({ ...form, trigger: e.target.value })}
            >
              <option value="interval">On a schedule</option>
              <option value="event">When an event happens</option>
            </select>
          </label>
        </div>
        {form.trigger === 'interval' ? (
          <label className="field">
            <span className="field-label">Interval</span>
            <select
              value={form.interval_minutes}
              onChange={(e) => setForm({ ...form, interval_minutes: Number(e.target.value) })}
            >
              {SCHEDULE_INTERVALS.map((i) => (
                <option key={i.minutes} value={i.minutes}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="field-row">
            <label className="field">
              <span className="field-label">Event</span>
              <select
                value={form.event}
                onChange={(e) => setForm({ ...form, event: e.target.value })}
              >
                {SCHEDULE_EVENTS.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Filter (optional)</span>
              <input
                value={form.event_filter}
                onChange={(e) => setForm({ ...form, event_filter: e.target.value })}
                placeholder="Substring the title or URL must contain"
              />
            </label>
          </div>
        )}
        <label className="field">
          <span className="field-label">Instruction</span>
          <textarea
            rows={3}
            value={form.instruction}
            onChange={(e) => setForm({ ...form, instruction: e.target.value })}
            placeholder="What should the agent do on each run? Use {date} for today's date."
          />
        </label>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={saving || !form.instruction.trim()}>
            {saving ? (
              <>
                <Spinner size={13} /> Saving
              </>
            ) : (
              <>
                <Icon name="plus" size={13} /> Add automation
              </>
            )}
          </button>
        </div>
        {formError && <p className="error-text">{formError}</p>}
      </form>
    </Modal>
  )
}
