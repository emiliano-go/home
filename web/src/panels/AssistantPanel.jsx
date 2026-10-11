import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

export function AssistantPanel() {
  const { data, loading } = useAsync(api.getSettings, [])
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [prefs, setPrefs] = useState(null)
  const [newPref, setNewPref] = useState('')
  const [prefBusy, setPrefBusy] = useState(false)
  const [editPref, setEditPref] = useState(null)
  const [prefDraft, setPrefDraft] = useState('')

  useEffect(() => {
    if (data) setForm(data)
  }, [data])

  useEffect(() => {
    api
      .listPreferences()
      .then((r) => setPrefs(r.preferences || []))
      .catch(() => setPrefs([]))
  }, [])

  const addPref = () => {
    const text = newPref.trim()
    if (!text || prefBusy) return
    setPrefBusy(true)
    api
      .addPreference(text)
      .then((r) => {
        setPrefs(r.preferences || [])
        setNewPref('')
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setPrefBusy(false))
  }

  const removePref = (index) => {
    api
      .removePreference(index)
      .then((r) => setPrefs(r.preferences || []))
      .catch((err) => setError(err.message || String(err)))
  }

  const startEdit = (index) => {
    setEditPref(index)
    setPrefDraft((prefs || [])[index] || '')
  }

  const saveEdit = () => {
    const text = prefDraft.trim()
    if (!text) return
    api
      .setPreference(editPref, text)
      .then((r) => {
        setPrefs(r.preferences || [])
        setEditPref(null)
      })
      .catch((err) => setError(err.message || String(err)))
  }

  if (loading || !form) return <p className="note">Loading...</p>

  const field = (key, value) => {
    setSaved(false)
    setForm({ ...form, [key]: value })
  }

  const save = (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    api
      .updateSettings(form)
      .then((next) => {
        setForm(next)
        setSaved(true)
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  return (
    <form className="agent-form" onSubmit={save}>
      <div className="field-row">
        <label className="field">
          <span className="field-label">Your name</span>
          <input
            value={form.user_name || ''}
            onChange={(e) => field('user_name', e.target.value)}
            placeholder="How the agent should address you"
          />
        </label>
        <label className="field">
          <span className="field-label">Timezone</span>
          <input
            value={form.timezone || ''}
            onChange={(e) => field('timezone', e.target.value)}
            placeholder="Europe/Rome"
          />
          <span className="field-hint">IANA name; used for reminders and the briefing.</span>
        </label>
      </div>
      <label className="field">
        <span className="field-label">Standing instructions</span>
        <textarea
          rows={3}
          value={form.instructions || ''}
          onChange={(e) => field('instructions', e.target.value)}
          placeholder="Always injected into the agent's system prompt, e.g. 'Be concise. Prefer tests first.'"
        />
      </label>
      <div className="field">
        <span className="field-label">Standing preferences</span>
        <span className="field-hint">
          Always injected into every prompt. Add rules the agent must never forget.
        </span>
        <div className="pref-list">
          {(prefs || []).map((p, i) =>
            editPref === i ? (
              <div key={`edit-${i}`} className="pref-item">
                <input
                  autoFocus
                  value={prefDraft}
                  onChange={(e) => setPrefDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      saveEdit()
                    }
                    if (e.key === 'Escape') setEditPref(null)
                  }}
                />
                <button type="button" className="icon-btn" title="Save" onClick={saveEdit}>
                  <Icon name="check" size={13} />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Cancel"
                  onClick={() => setEditPref(null)}
                >
                  <Icon name="x" size={13} />
                </button>
              </div>
            ) : (
              <div key={`${i}-${p}`} className="pref-item">
                <span>{p}</span>
                <button
                  type="button"
                  className="icon-btn"
                  title="Edit preference"
                  onClick={() => startEdit(i)}
                >
                  <Icon name="edit" size={13} />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Remove preference"
                  onClick={() => removePref(i)}
                >
                  <Icon name="x" size={13} />
                </button>
              </div>
            )
          )}
          {prefs && prefs.length === 0 && <span className="note">No preferences yet.</span>}
        </div>
        <div className="row" style={{ marginBottom: 0 }}>
          <input
            value={newPref}
            onChange={(e) => setNewPref(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addPref()
              }
            }}
            placeholder="e.g. Never use em dashes; use ; : , ( ) - instead"
          />
          <button
            type="button"
            className="btn"
            disabled={!newPref.trim() || prefBusy}
            onClick={addPref}
          >
            {prefBusy ? 'Adding' : 'Add'}
          </button>
        </div>
      </div>
      <div className="field-row">
        <label className="field">
          <span className="field-label">Daily briefing</span>
          <select
            value={form.briefing_enabled}
            onChange={(e) => field('briefing_enabled', e.target.value)}
          >
            <option value="0">Off</option>
            <option value="1">On</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Briefing time</span>
          <input
            type="time"
            value={form.briefing_time || '08:00'}
            onChange={(e) => field('briefing_time', e.target.value)}
          />
        </label>
      </div>
      <label className="dep-item" style={{ flex: 'none' }}>
        <input
          type="checkbox"
          checked={form.briefing_agent === '1'}
          onChange={(e) => field('briefing_agent', e.target.checked ? '1' : '0')}
        />
        Let the agent add commentary to the briefing
      </label>
      <div className="field-row">
        <label className="field">
          <span className="field-label">Daily plan</span>
          <select
            value={form.daily_plan_enabled}
            onChange={(e) => field('daily_plan_enabled', e.target.value)}
          >
            <option value="0">Off</option>
            <option value="1">On</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Plan time</span>
          <input
            type="time"
            value={form.daily_plan_time || '08:30'}
            onChange={(e) => field('daily_plan_time', e.target.value)}
          />
        </label>
      </div>
      <div className="field-row">
        <label className="field">
          <span className="field-label">Weekly review</span>
          <select
            value={form.weekly_review_enabled}
            onChange={(e) => field('weekly_review_enabled', e.target.value)}
          >
            <option value="0">Off</option>
            <option value="1">On</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">Review day</span>
          <select
            value={form.weekly_review_day}
            onChange={(e) => field('weekly_review_day', e.target.value)}
          >
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => (
              <option key={d} value={String(i)}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Review time</span>
          <input
            type="time"
            value={form.weekly_review_time || '16:00'}
            onChange={(e) => field('weekly_review_time', e.target.value)}
          />
        </label>
      </div>
      <label className="dep-item" style={{ flex: 'none' }}>
        <input
          type="checkbox"
          checked={form.web_fetch_enabled === '1'}
          onChange={(e) => field('web_fetch_enabled', e.target.checked ? '1' : '0')}
        />
        Allow the agent to fetch web pages (watchers use this too)
      </label>
      <label className="dep-item" style={{ flex: 'none' }}>
        <input
          type="checkbox"
          checked={form.browser_enabled === '1'}
          onChange={(e) => field('browser_enabled', e.target.checked ? '1' : '0')}
        />
        Allow the agent to drive a real browser (browser-use)
      </label>
      <label className="field">
        <span className="field-label">Browser CDP URL (optional)</span>
        <input
          value={form.browser_cdp_url || ''}
          onChange={(e) => field('browser_cdp_url', e.target.value)}
          placeholder="http://localhost:9222"
        />
        <span className="field-hint">
          Attach to your own Chrome (started with --remote-debugging-port=9222) to reuse your
          logins. Leave empty to use the bundled headless browser.
        </span>
      </label>
      <label className="dep-item" style={{ flex: 'none' }}>
        <input
          type="checkbox"
          checked={form.show_thinking !== '0'}
          onChange={(e) => field('show_thinking', e.target.checked ? '1' : '0')}
        />
        Open the model's thinking cards by default (thinking is always recorded)
      </label>
      <div className="row" style={{ marginBottom: 0 }}>
        <button className="btn primary" disabled={saving}>
          {saving ? (
            <>
              <Spinner size={14} /> Saving
            </>
          ) : (
            'Save settings'
          )}
        </button>
        {saved && <span className="note">Saved.</span>}
      </div>
      {error && <div className="error-text">{error}</div>}
    </form>
  )
}
