import { useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { mdToHtml } from '../lib/markdown.js'

export function CaptureView({ projectId }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const submit = (e) => {
    e.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    setError(null)
    setReport(null)
    api
      .capture(projectId, { text: text.trim() })
      .then((r) => {
        setReport(r.report || '(no report)')
        setText('')
      })
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="center-col">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Capture</h2>
          <p className="note">
            Paste notes, an email, or a thread; the agent structures it into tasks,
            reminders, decisions, and client facts
          </p>
        </div>
      </div>
      <form className="docs-card" onSubmit={submit}>
        <textarea
          rows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste raw notes here..."
        />
        <div className="row" style={{ marginTop: 10, marginBottom: 0 }}>
          <button className="btn primary" disabled={busy || !text.trim()}>
            {busy ? (
              <>
                <Spinner size={13} /> Capturing
              </>
            ) : (
              <>
                <Icon name="plus" size={13} /> Capture
              </>
            )}
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </form>
      {report !== null && (
        <div className="docs-card">
          <div className="docs-head">
            <Icon name="check" size={15} />
            <span>Captured</span>
          </div>
          <div className="reader-body prose" dangerouslySetInnerHTML={{ __html: mdToHtml(report) }} />
        </div>
      )}
    </div>
  )
}
