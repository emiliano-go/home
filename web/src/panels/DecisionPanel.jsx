import { useEffect, useState } from 'react'
import { api } from '../api.js'

export function DecisionPanel() {
  const [snapshot, setSnapshot] = useState(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .getDecision()
      .then((s) => {
        setSnapshot(s)
        setBaseUrl(s.settings?.baseUrl || '')
        setModel(s.settings?.model || '')
      })
      .catch((err) => setError(err.message || String(err)))
  }, [])

  const patch = (body) => {
    setBusy(true)
    setError(null)
    setSaved(false)
    api
      .patchDecision(body)
      .then((s) => {
        setSnapshot(s)
        setBaseUrl(s.settings?.baseUrl || '')
        setModel(s.settings?.model || '')
        setSaved(true)
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(false))
  }

  if (!snapshot) return <p className="note">Loading...</p>

  return (
    <form className="agent-form" onSubmit={(e) => { e.preventDefault(); patch({ baseUrl: baseUrl.trim() || undefined, model: model.trim() || undefined }) }}>
      <div className="field">
        <span className="field-label">Evaluation</span>
        <span className="field-hint">
          Judge every finished turn with a local Laya checkpoint; a failing verdict feeds corrective
          feedback back to the agent (up to the retry limit) before the turn ends.
        </span>
        <label className="row">
          <input
            type="checkbox"
            checked={!!snapshot.enabled}
            disabled={busy}
            onChange={(e) => patch({ enabled: e.target.checked })}
          />
          <span>Enabled</span>
        </label>
      </div>
      {!snapshot.hasBaseUrl && (
        <p className="note">Set a base URL such as http://127.0.0.1:8765 to enable evaluation.</p>
      )}
      <label className="field">
        <span className="field-label">Base URL</span>
        <input
          value={baseUrl}
          placeholder="http://127.0.0.1:8765"
          onChange={(e) => setBaseUrl(e.target.value)}
        />
        <span className="field-hint">A Laya `serve` endpoint exposing POST /v1/systemone.</span>
      </label>
      <label className="field">
        <span className="field-label">Model / checkpoint</span>
        <input
          value={model}
          placeholder="coding-decisions"
          onChange={(e) => setModel(e.target.value)}
        />
        <span className="field-hint">Optional checkpoint name passed to the engine.</span>
      </label>
      <p className="note">
        Train a local judge with the laya <code>coding-decisions</code> recipe
        (github.com/emiliano-go/laya → <code>recipes/coding-decisions</code>), then serve it
        with encoder's <code>script/laya-server.py --model &lt;checkpoint-dir&gt;</code> and point
        the base URL here.
      </p>
      <button className="btn primary" disabled={busy}>
        Save
      </button>
      {saved && <span className="note">Saved.</span>}
      {error && <p className="note">{error}</p>}
    </form>
  )
}
