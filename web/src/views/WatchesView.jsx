import { useState } from 'react'
import { api } from '../api.js'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate, truncate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'
import { intervalLabel } from './AutomationsView.jsx'

export const WATCH_KIND_LABEL = { page: 'Page', feed: 'Feed', condition: 'Condition' }

export function WatchesView({ projects }) {
  const { data, error, loading, reload } = useAsync(api.listWatches, [])
  const watches = data || []
  const [editor, setEditor] = useState(false)
  const [formError, setFormError] = useState(null)
  const [checking, setChecking] = useState(null)

  const act = (fn) => {
    setFormError(null)
    fn().then(reload).catch((err) => setFormError(err.message || String(err)))
  }

  const runNow = (watch) => {
    setChecking(watch.id)
    setFormError(null)
    api
      .checkWatch(watch.id)
      .then(reload)
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setChecking(null))
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Watches</h2>
          <p className="note">Notify only when something happens.</p>
        </div>
        <button className="btn primary" onClick={() => setEditor(true)}>
          <Icon name="plus" size={14} /> New watch
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
      ) : watches.length === 0 ? (
        <SectionEmpty
          icon="refresh"
          title="No watches"
          hint="Watch a page, an RSS feed, or a condition. Ask the agent, or create one."
        />
      ) : (
        <div className="home-list">
          {watches.map((w) => (
            <div key={w.id} className="watch-row">
              <span className={`badge ${w.status === 'active' ? 'accent' : w.status === 'done' ? 'ok' : ''}`}>
                {WATCH_KIND_LABEL[w.kind] || w.kind}
              </span>
              <span className="home-row-main">
                <span className="home-row-title">{w.condition || w.url}</span>
                <span className="home-row-sub">
                  {w.condition && w.url ? `${w.url}, ` : ''}every {intervalLabel(w.interval_minutes)},{' '}
                  {w.status}
                  {w.last_checked_at ? `, checked ${relDate(w.last_checked_at)}` : ''}
                </span>
                {w.last_result && <span className="home-row-sub">{truncate(w.last_result, 140)}</span>}
              </span>
              <button className="btn" title="Check now" disabled={checking === w.id} onClick={() => runNow(w)}>
                {checking === w.id ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}
              </button>
              <button
                className="btn"
                title={w.status === 'active' ? 'Pause' : 'Resume'}
                onClick={() =>
                  act(() =>
                    api.updateWatch(w.id, { status: w.status === 'active' ? 'paused' : 'active' })
                  )
                }
              >
                {w.status === 'active' ? 'Pause' : 'Resume'}
              </button>
              <button className="btn danger" title="Delete" onClick={() => act(() => api.deleteWatch(w.id))}>
                <Icon name="x" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {editor && (
        <WatchEditor
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

export function WatchEditor({ projects, onClose, onSaved }) {
  const [kind, setKind] = useState('page')
  const [url, setUrl] = useState('')
  const [condition, setCondition] = useState('')
  const [notifyOn, setNotifyOn] = useState('change')
  const [interval, setIntervalMinutes] = useState(60)
  const [projectId, setProjectId] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState(null)

  const add = (e) => {
    e.preventDefault()
    setSaving(true)
    setFormError(null)
    api
      .createWatch({
        kind,
        url: kind === 'condition' && !url.trim() ? null : url.trim() || null,
        condition: condition.trim(),
        notify_on: notifyOn,
        interval_minutes: Number(interval),
        project_id: projectId ? Number(projectId) : null,
      })
      .then(onSaved)
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  return (
    <Modal title="New watch" onClose={onClose}>
      <form className="agent-form" onSubmit={add}>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="page">Page changed</option>
              <option value="feed">Feed: new items</option>
              <option value="condition">Condition check (agent)</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Every</span>
            <select value={interval} onChange={(e) => setIntervalMinutes(e.target.value)}>
              <option value={30}>30 minutes</option>
              <option value={60}>1 hour</option>
              <option value={360}>6 hours</option>
              <option value={1440}>1 day</option>
            </select>
          </label>
        </div>
        <label className="field">
          <span className="field-label">URL</span>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
        </label>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Condition or phrase</span>
            <input
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              placeholder={kind === 'condition' ? 'Is the v2 release published?' : 'In stock'}
            />
          </label>
          {kind === 'page' && (
            <label className="field">
              <span className="field-label">Notify on</span>
              <select value={notifyOn} onChange={(e) => setNotifyOn(e.target.value)}>
                <option value="change">Any change</option>
                <option value="appear">Phrase appears</option>
              </select>
            </label>
          )}
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
          <button
            className="btn primary"
            disabled={saving || (kind !== 'condition' && !url.trim()) || (kind === 'condition' && !condition.trim())}
          >
            {saving ? <Spinner size={13} /> : 'Add watch'}
          </button>
        </div>
        {formError && <p className="error-text">{formError}</p>}
      </form>
    </Modal>
  )
}
