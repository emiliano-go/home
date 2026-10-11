import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { DetailRow } from '../components/Detail.jsx'
import { Modal } from '../components/Modal.jsx'
import { Icon } from '../icons.jsx'
import { relDate } from '../lib/format.js'
import { mdToHtml } from '../lib/markdown.js'
import { clickable } from '../lib/ui.js'

export function MemoryView({ projectId, providerId, onStart }) {
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [searching, setSearching] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [fixing, setFixing] = useState(false)
  const [fixReport, setFixReport] = useState(null)
  const [fixError, setFixError] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [candError, setCandError] = useState(null)

  const search = (e) => {
    e?.preventDefault()
    setSearching(true)
    setError(null)
    api
      .searchMemory(projectId, q)
      .then(setItems)
      .catch((err) => setError(err.message || String(err)))
      .finally(() => setSearching(false))
  }

  const loadCandidates = () =>
    api
      .listCandidates(projectId)
      .then(setCandidates)
      .catch((err) => setCandError(err.message || String(err)))

  useEffect(() => {
    search()
    loadCandidates()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const decideCandidate = (id, accept) => {
    const req = accept ? api.acceptCandidate(id) : api.rejectCandidate(id)
    req.then(loadCandidates).catch((err) => setCandError(err.message || String(err)))
  }

  const acceptAll = () =>
    api
      .acceptAllCandidates(projectId)
      .then(() => {
        loadCandidates()
        search()
      })
      .catch((err) => setCandError(err.message || String(err)))

  const runFix = (e) => {
    e?.preventDefault()
    if (!instruction.trim() || fixing) return
    setFixing(true)
    setFixError(null)
    setFixReport(null)
    const pid = parseInt(providerId, 10)
    api
      .fixMemory(projectId, {
        instruction: instruction.trim(),
        provider_id: Number.isFinite(pid) ? pid : undefined,
      })
      .then((r) => {
        setFixReport(r.report || '(no report)')
        search()
      })
      .catch((err) => setFixError(err.message || String(err)))
      .finally(() => setFixing(false))
  }

  return (
    <div className="center-col">
      <div className="page-head">
        <h2>Memory</h2>
      </div>
      {candidates.length > 0 && (
        <section className="panel candidate-panel">
          <div className="panel-head row-between">
            <div>
              <h3>Memory candidates</h3>
              <p>Proposed by the memory writer or checkpoint; accept to store them in Totem.</p>
            </div>
            <button className="btn" onClick={acceptAll}>
              <Icon name="check" size={14} /> Accept all
            </button>
          </div>
          {candError && <p className="error-text">{candError}</p>}
          <div className="candidate-list">
            {candidates.map((c) => (
              <div key={c.id} className="candidate-row">
                <div className="candidate-main">
                  <div className="candidate-title">
                    <span className="badge accent">{c.type}</span>
                    {c.title}
                    <span className="badge">{Math.round((c.confidence || 0) * 100)}%</span>
                    {c.source && c.source !== 'agent' && <span className="badge">{c.source}</span>}
                  </div>
                  <div className="meta">{c.statement}</div>
                </div>
                <div className="row" style={{ marginBottom: 0, flex: 'none' }}>
                  <button className="btn primary" onClick={() => decideCandidate(c.id, true)}>
                    Accept
                  </button>
                  <button className="btn" onClick={() => decideCandidate(c.id, false)}>
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="fix-panel">
        <form className="fix-row" onSubmit={runFix}>
          <input
            placeholder="Tell the agent what to fix, e.g. mark Flask memories as stale"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <button className="btn primary" disabled={fixing || !instruction.trim()}>
            {fixing ? 'Running...' : 'Fix with agent'}
          </button>
        </form>
        {fixError && <p className="error-text" style={{ marginTop: 8 }}>{fixError}</p>}
        {fixReport !== null && (
          <div className="fix-report">
            <div className="reader-body prose" dangerouslySetInnerHTML={{ __html: mdToHtml(fixReport) }} />
          </div>
        )}
      </div>
      <form className="search-row" onSubmit={search}>
        <input
          placeholder="Search memory..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn" disabled={searching}>
          <Icon name="search" size={14} />
          {searching ? 'Searching' : 'Search'}
        </button>
      </form>
      {error && <p className="error-text">{error}</p>}
      {items && items.length === 0 && (
        <p className="empty">
          {q ? 'No memory items match your search.' : 'No memory items yet.'}
        </p>
      )}
      <div className="cards">
        {(items || []).map((m) => (
          <div key={m.id} className="card clickable" {...clickable(() => setSelected(m))}>
            <h3>
              <span className="badge">{m.type}</span>
              {m.title}
              {m.applicability && <span className="badge">{m.applicability}</span>}
              {m.assertedBy && <span className="badge">{m.assertedBy}</span>}
              {(m.warnings || []).length > 0 && <span className="badge err">stale</span>}
            </h3>
            <div className="meta">{m.statement}</div>
            <div className="meta" style={{ marginTop: 6 }}>
              {(m.tags || []).map((t) => (
                <span key={t} className="badge">
                  {t}
                </span>
              ))}{' '}
              {relDate(m.updatedAt || m.updated_at)}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <MemoryDetailModal
          item={selected}
          onClose={() => setSelected(null)}
          onStart={onStart}
        />
      )}
    </div>
  )
}

export function MemoryDetailModal({ item, onClose, onStart }) {
  const tags = item.tags || []
  return (
    <Modal title={item.title} onClose={onClose}>
      <div className="detail-rows">
        <DetailRow label="Type" value={item.type} />
        <DetailRow label="Statement" value={item.statement} />
        {item.details && <DetailRow label="Details" value={item.details} />}
        {tags.length > 0 && <DetailRow label="Tags" value={tags.join(', ')} />}
        {item.confidence != null && <DetailRow label="Confidence" value={item.confidence} />}
        {item.importance != null && <DetailRow label="Importance" value={item.importance} />}
        {item.scope && <DetailRow label="Scope" value={item.scope} />}
        {item.assertedBy && <DetailRow label="Asserted by" value={item.assertedBy} />}
        {item.applicability && <DetailRow label="Applicability" value={item.applicability} />}
        {(item.warnings || []).length > 0 && (
          <DetailRow label="Warnings" value={item.warnings.join('; ')} />
        )}
        <DetailRow label="Updated" value={relDate(item.updatedAt || item.updated_at)} />
      </div>
      {onStart && (
        <div className="row" style={{ marginTop: 16, marginBottom: 0 }}>
          <button
            className="btn primary"
            onClick={() => {
              onClose()
              onStart(
                `Let's revisit this project memory: "${item.title}". ${item.statement}`
              )
            }}
          >
            <Icon name="chat" size={13} /> Ask about this
          </button>
        </div>
      )}
    </Modal>
  )
}
