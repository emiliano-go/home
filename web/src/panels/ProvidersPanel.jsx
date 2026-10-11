import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Modal } from '../components/Modal.jsx'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

const EMPTY = { name: '', base_url: '', api_key: '', keys: '', models: [] }
const STEPS = ['Provider', 'API key', 'Models']

function ModelChecklist({ models, selected, onToggle }) {
  if (!models.length) return <p className="muted">No models loaded.</p>
  return (
    <div className="model-checklist">
      {models.map((m) => (
        <label key={m} className="model-check">
          <input type="checkbox" checked={selected.includes(m)} onChange={() => onToggle(m)} />
          <span>{m}</span>
        </label>
      ))}
    </div>
  )
}

function ModelManager({ provider, onClose, onSaved }) {
  const [available, setAvailable] = useState(provider.models)
  const [selected, setSelected] = useState(provider.models)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [custom, setCustom] = useState('')
  const [smallModel, setSmallModel] = useState(provider.small_model || '')

  useEffect(() => {
    api
      .listProviderModels({ provider_id: provider.id })
      .then((r) => setAvailable([...new Set([...(r.models || []), ...provider.models])].sort()))
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false))
  }, [provider.id])

  const toggle = (m) =>
    setSelected((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]))

  const addCustom = () => {
    const m = custom.trim()
    if (m && !available.includes(m)) setAvailable((prev) => [...prev, m].sort())
    if (m && !selected.includes(m)) setSelected((prev) => [...prev, m])
    setCustom('')
  }

  const save = () => {
    setSaving(true)
    setError(null)
    const toAdd = selected.filter((m) => !provider.models.includes(m))
    const toRemove = provider.models.filter((m) => !selected.includes(m))
    Promise.all([
      toAdd.length ? api.addProviderModels(provider.id, toAdd) : null,
      ...toRemove.map((m) => api.removeProviderModel(provider.id, m)),
      api.updateProvider(provider.id, { small_model: smallModel }),
    ])
      .then(onSaved)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setSaving(false))
  }

  return (
    <Modal title={`Models · ${provider.name}`} onClose={onClose}>
      {loading && <p className="note">Loading models...</p>}
      {error && <p className="error-text">{error}</p>}
      <label className="field">
        <span className="field-label">Small model</span>
        <input
          value={smallModel}
          onChange={(e) => setSmallModel(e.target.value)}
          placeholder="Cheap model for titles, summaries, and memory distillation"
        />
      </label>
      <ModelChecklist models={available} selected={selected} onToggle={toggle} />
      <div className="row" style={{ marginTop: 10, marginBottom: 0 }}>
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addCustom())}
          placeholder="Add a custom model id"
        />
        <button type="button" className="btn" onClick={addCustom} disabled={!custom.trim()}>
          Add
        </button>
      </div>
      <div className="row" style={{ marginTop: 14, marginBottom: 0 }}>
        <button className="btn primary" onClick={save} disabled={saving}>
          {saving ? 'Saving...' : 'Save models'}
        </button>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

export function ProvidersPanel() {
  const { data: providers, error, loading, reload } = useAsync(api.listProviders, [])
  const presetsReq = useAsync(api.listPresets, [])
  const [step, setStep] = useState(0)
  const [presetKey, setPresetKey] = useState('')
  const [form, setForm] = useState(EMPTY)
  const [available, setAvailable] = useState([])
  const [custom, setCustom] = useState('')
  const [loadingModels, setLoadingModels] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState(null)
  const [testResults, setTestResults] = useState({})
  const [managing, setManaging] = useState(null)

  const presets = presetsReq.data || {}
  const isCustom = presetKey === 'custom'

  const reset = () => {
    setStep(0)
    setPresetKey('')
    setForm(EMPTY)
    setAvailable([])
    setCustom('')
    setFormError(null)
  }

  const choosePreset = (key) => {
    const p = presets[key] || {}
    setPresetKey(key)
    setForm({
      name: p.name || key,
      base_url: p.base_url || '',
      api_key: '',
      keys: '',
      models: p.model ? [p.model] : [],
    })
    setAvailable([])
    setFormError(null)
    setStep(1)
  }

  const toggleModel = (m) =>
    setForm((f) => ({
      ...f,
      models: f.models.includes(m) ? f.models.filter((x) => x !== m) : [...f.models, m],
    }))

  const addCustomModel = () => {
    const m = custom.trim()
    if (!m) return
    if (!available.includes(m)) setAvailable((prev) => [...prev, m].sort())
    if (!form.models.includes(m)) setForm((f) => ({ ...f, models: [...f.models, m] }))
    setCustom('')
  }

  const loadModels = () => {
    if (!form.base_url.trim()) {
      setFormError('Base URL is required.')
      return
    }
    setLoadingModels(true)
    setFormError(null)
    api
      .listProviderModels({ base_url: form.base_url, api_key: form.api_key })
      .then((r) => {
        const list = r.models || []
        setAvailable(list)
        setForm((f) => ({
          ...f,
          models: f.models.filter((m) => list.includes(m)),
        }))
        if (!list.length) setFormError('No models returned for that key.')
        setStep(2)
      })
      .catch((err) => {
        setFormError(err.message || String(err))
        setStep(2)
      })
      .finally(() => setLoadingModels(false))
  }

  const submit = (e) => {
    e.preventDefault()
    setSaving(true)
    setFormError(null)
    api
      .createProvider(form)
      .then(() => {
        reset()
        reload()
      })
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setSaving(false))
  }

  const test = (id) => {
    setTestResults((prev) => ({ ...prev, [id]: { testing: true } }))
    api
      .testProvider(id)
      .then((r) => setTestResults((prev) => ({ ...prev, [id]: r })))
      .catch((e) =>
        setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: e.message } }))
      )
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div>
      <div className="wizard">
        <div className="wizard-steps">
          {STEPS.map((label, i) => (
            <div
              key={label}
              className={`wizard-step ${step === i ? 'active' : ''} ${step > i ? 'done' : ''}`}
            >
              <span className="wizard-dot">{step > i ? '✓' : i + 1}</span>
              <span className="wizard-label">{label}</span>
            </div>
          ))}
        </div>

        {step === 0 && (
          <div className="wizard-body">
            <p className="note">Pick a provider, then choose the models to enable.</p>
            <div className="preset-grid">
              {Object.entries(presets).map(([k, p]) => (
                <button key={k} type="button" className="preset-card" onClick={() => choosePreset(k)}>
                  <span className="preset-name">{p.name || k}</span>
                  <span className="preset-url">{p.base_url}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 1 && (
          <form
            className="wizard-body"
            onSubmit={(e) => {
              e.preventDefault()
              loadModels()
            }}
          >
            <p className="note">
              {form.name} · <code>{form.base_url}</code>
            </p>
            {isCustom && (
              <label className="field">
                <span className="field-label">Base URL</span>
                <input
                  value={form.base_url}
                  onChange={set('base_url')}
                  placeholder="https://api.example.com"
                  required
                />
              </label>
            )}
            <label className="field">
              <span className="field-label">API key</span>
              <input
                type="password"
                value={form.api_key}
                onChange={set('api_key')}
                placeholder="Paste your API key (blank for local endpoints)"
                autoFocus
              />
            </label>
            <label className="field">
              <span className="field-label">Extra keys (rotation)</span>
              <textarea
                rows={2}
                value={form.keys}
                onChange={set('keys')}
                placeholder="Optional, one per line. Tried when a key is rate-limited or rejected."
              />
            </label>
            {formError && <div className="error-text">{formError}</div>}
            <div className="row" style={{ marginBottom: 0 }}>
              <button type="button" className="btn" onClick={() => setStep(0)}>
                Back
              </button>
              <button className="btn primary" disabled={loadingModels || !form.base_url.trim()}>
                {loadingModels ? (
                  <>
                    <Spinner size={13} /> Loading models
                  </>
                ) : (
                  'Continue'
                )}
              </button>
            </div>
          </form>
        )}

        {step === 2 && (
          <form className="wizard-body" onSubmit={submit}>
            <label className="field">
              <span className="field-label">Models ({form.models.length} selected)</span>
              <ModelChecklist
                models={available}
                selected={form.models}
                onToggle={toggleModel}
              />
              <div className="row" style={{ marginTop: 8, marginBottom: 0 }}>
                <input
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addCustomModel())}
                  placeholder="Add a custom model id"
                />
                <button type="button" className="btn" onClick={addCustomModel} disabled={!custom.trim()}>
                  Add
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={loadModels}
                  disabled={loadingModels}
                >
                  {loadingModels ? <Spinner size={13} /> : 'Reload'}
                </button>
              </div>
            </label>
            <label className="field">
              <span className="field-label">Name</span>
              <input value={form.name} onChange={set('name')} placeholder="e.g. OpenCode Go" required />
            </label>
            {formError && <div className="error-text">{formError}</div>}
            <div className="row" style={{ marginBottom: 0 }}>
              <button type="button" className="btn" onClick={() => setStep(1)}>
                Back
              </button>
              <button className="btn primary" disabled={saving || !form.name.trim()}>
                {saving ? 'Saving...' : 'Add provider'}
              </button>
            </div>
          </form>
        )}
      </div>

      {loading && <p className="note">Loading...</p>}
      {error && <p className="error-text">{error}</p>}
      {providers && providers.length === 0 && <p className="error-banner">No providers configured.</p>}
      <div className="cards">
        {(providers || []).map((p) => {
          const tr = testResults[p.id]
          return (
            <div key={p.id} className="card">
              <h3>
                {p.name}
                {tr && !tr.testing && (
                  <span className={`badge ${tr.ok ? 'ok' : 'err'}`}>
                    {tr.ok ? `ok: ${tr.model || p.model}` : 'error'}
                  </span>
                )}
              </h3>
              <div className="meta">
                {p.base_url} ({p.has_key ? 'key stored' : 'no key'})
              </div>
              <div className="link-chips" style={{ marginTop: 8 }}>
                {p.models.length === 0 && <span className="muted">No models configured.</span>}
                {p.models.map((m) => (
                  <span key={m} className={`link-chip ${m === p.model ? 'static' : ''}`}>
                    {m}
                  </span>
                ))}
              </div>
              {tr && !tr.testing && !tr.ok && tr.error && (
                <div className="meta error-text">{tr.error}</div>
              )}
              <div className="row" style={{ marginTop: 10, marginBottom: 0 }}>
                <button className="btn primary" onClick={() => setManaging(p)}>
                  <Icon name="settings" size={13} /> Models
                </button>
                <button className="btn" onClick={() => test(p.id)} disabled={tr?.testing}>
                  {tr?.testing ? 'Testing...' : 'Test'}
                </button>
                <button
                  className="btn danger"
                  onClick={() =>
                    api.deleteProvider(p.id).then(reload).catch((e) => alert(e.message))
                  }
                >
                  Delete
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {managing && (
        <ModelManager
          provider={managing}
          onClose={() => setManaging(null)}
          onSaved={() => {
            setManaging(null)
            reload()
          }}
        />
      )}
    </div>
  )
}
