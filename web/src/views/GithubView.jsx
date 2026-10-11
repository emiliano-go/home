import { useState } from 'react'
import { api } from '../api.js'
import { DetailRow } from '../components/Detail.jsx'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'
import { mdToHtml } from '../lib/markdown.js'
import { clickable } from '../lib/ui.js'

export function GithubItemModal({ item, kind, triaging, reviewing, onClose, onChat, onTriage, onReview, onMerge, mergeMethod, onMergeMethod, merging }) {
  const noun = kind === 'prs' ? 'pull request' : kind === 'issues' ? 'issue' : 'run'
  const name = item.title || item.name || `${noun}`
  const label = item.number != null ? `#${item.number} ${name}` : name
  return (
    <Modal title={label} onClose={onClose}>
      <div className="detail-rows">
        <DetailRow label="Type" value={noun} />
        <DetailRow label="State" value={item.conclusion || item.state || item.status} />
        {item.user && <DetailRow label="Author" value={item.user} />}
        {item.branch && <DetailRow label="Branch" value={item.branch} />}
        {item.event && <DetailRow label="Event" value={item.event} />}
        {item.labels?.length > 0 && <DetailRow label="Labels" value={item.labels.join(', ')} />}
        {item.updated_at && <DetailRow label="Updated" value={relDate(item.updated_at)} />}
      </div>
      <div className="row" style={{ marginTop: 16, marginBottom: 0, flexWrap: 'wrap' }}>
        {onChat && kind !== 'runs' && (
          <button
            className="btn primary"
            onClick={() => {
              onClose()
              onChat(
                `Let's discuss ${noun} #${item.number}: "${name}". Explain the context and what should happen next.`
              )
            }}
          >
            <Icon name="chat" size={13} /> Chat about this
          </button>
        )}
        {onTriage && kind !== 'runs' && (
          <button
            className="btn"
            disabled={triaging === item.number}
            onClick={() => {
              onClose()
              onTriage(item)
            }}
          >
            <Icon name="tasks" size={13} /> Triage
          </button>
        )}
        {onReview && kind !== 'runs' && (
          <button
            className="btn"
            disabled={reviewing === item.number}
            onClick={() => {
              onClose()
              onReview(item)
            }}
          >
            <Icon name="check" size={13} /> Review
          </button>
        )}
        {onMerge && kind === 'prs' && (
          <>
            <select value={mergeMethod} onChange={(e) => onMergeMethod(e.target.value)}>
              <option value="squash">Squash</option>
              <option value="merge">Merge commit</option>
              <option value="rebase">Rebase</option>
            </select>
            <button
              className="btn danger"
              disabled={merging === item.number}
              onClick={() => onMerge(item)}
            >
              <Icon name="git" size={13} />
              {merging === item.number ? 'Merging…' : 'Merge PR'}
            </button>
          </>
        )}
        {item.url && (
          <a className="btn" href={item.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        )}
      </div>
    </Modal>
  )
}

export function GithubView({ projectId, onSummarize, onOpenTasks }) {
  const [kind, setKind] = useState('prs')
  const [state, setState] = useState('open')
  const [selected, setSelected] = useState(null)
  const [triaging, setTriaging] = useState(null)
  const [triageReport, setTriageReport] = useState(null)
  const [reviewing, setReviewing] = useState(null)
  const [reviewReport, setReviewReport] = useState(null)
  const [merging, setMerging] = useState(null)
  const [mergeMethod, setMergeMethod] = useState('squash')
  const [repo, setRepo] = useState('')
  const reposReq = useAsync(() => api.listProjectRepos(projectId), [projectId])
  const repoRows = reposReq.data || []
  const { data, error, loading, reload } = useAsync(
    () => api.projectGithub(projectId, kind, kind === 'runs' ? 'open' : state, repo || undefined),
    [projectId, kind, state, repo]
  )
  const items = (data && data.items) || []

  const badgeTone = (value) => {
    if (['open', 'success'].includes(value)) return 'ok'
    if (['failure', 'closed'].includes(value)) return 'err'
    return ''
  }

  const runTriage = (it) => {
    setTriaging(it.number)
    api
      .triage(projectId, {
        kind: kind === 'prs' ? 'pr' : 'issue',
        number: it.number,
        repo: repo || undefined,
      })
      .then((r) => setTriageReport({ ...r, item: it }))
      .catch((e) => setTriageReport({ error: e.message || String(e), item: it }))
      .finally(() => setTriaging(null))
  }

  const runReview = (it) => {
    setReviewing(it.number)
    api
      .reviewItem(projectId, {
        kind: kind === 'prs' ? 'pr' : 'issue',
        number: it.number,
        repo: repo || undefined,
      })
      .then((r) => setReviewReport({ ...r, item: it }))
      .catch((e) => setReviewReport({ error: e.message || String(e), item: it }))
      .finally(() => setReviewing(null))
  }

  const runMerge = (it) => {
    setMerging(it.number)
    api
      .mergePr(projectId, {
        number: it.number,
        method: mergeMethod,
        repo: repo || undefined,
      })
      .then(() => {
        setSelected(null)
        reload()
      })
      .catch((e) => alert(e.message || String(e)))
      .finally(() => setMerging(null))
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <h2>GitHub</h2>
        <div className="row" style={{ marginBottom: 0 }}>
          {repoRows.length > 1 && (
            <select value={repo} onChange={(e) => setRepo(e.target.value)}>
              <option value="">All repositories (primary)</option>
              {repoRows.map((r) => (
                <option key={r.alias} value={r.alias}>
                  {r.alias}
                </option>
              ))}
            </select>
          )}
          <button className="btn" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={14} />
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="gh-toolbar">
        <div className="segmented">
          <button className={kind === 'prs' ? 'on' : ''} onClick={() => setKind('prs')}>
            Pull requests
          </button>
          <button className={kind === 'issues' ? 'on' : ''} onClick={() => setKind('issues')}>
            Issues
          </button>
          <button className={kind === 'runs' ? 'on' : ''} onClick={() => setKind('runs')}>
            CI runs
          </button>
        </div>
        {kind !== 'runs' && (
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </select>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}
      {data && !data.available && (
        <SectionEmpty
          icon="alert"
          title="GitHub unavailable"
          hint={data.error || 'This project has no GitHub remote, or no token is configured.'}
        />
      )}
      {loading && (
        <div className="gh-list">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="row-skeleton" />
          ))}
        </div>
      )}
      {!loading && data && data.available && items.length === 0 && (
        <SectionEmpty icon="check" title="Nothing here" hint="No items for this filter." />
      )}
      <div className="gh-list">
        {items.map((it) => (
          <div
            key={it.number ?? it.id}
            className="gh-row clickable"
            {...clickable(() => setSelected(it))}
          >
            <Icon
              name={kind === 'runs' ? 'play' : kind === 'issues' ? 'chat' : 'git'}
              size={15}
              className="gh-row-icon"
            />
            <div className="gh-row-main">
              <div className="gh-row-title">
                {it.number != null && <span className="gh-num">#{it.number}</span>}
                {it.title || it.name}
              </div>
              <div className="gh-row-meta">
                {it.user && <span>{it.user}</span>}
                {it.branch && <span>{it.branch}</span>}
                {it.event && <span>{it.event}</span>}
                {it.labels?.length > 0 && <span>{it.labels.join(', ')}</span>}
                {it.updated_at && <span>{relDate(it.updated_at)}</span>}
              </div>
            </div>
            <span className={`badge ${badgeTone(it.conclusion || it.state)}`}>
              {it.conclusion || it.state}
            </span>
            <div className="gh-row-actions" onClick={(e) => e.stopPropagation()}>
              {kind !== 'runs' && (
                <button
                  className="btn primary"
                  title="Turn into a plan + tasks"
                  disabled={triaging === it.number}
                  onClick={() => runTriage(it)}
                >
                  {triaging === it.number ? (
                    <>
                      <Spinner size={13} /> Triaging
                    </>
                  ) : (
                    <>
                      <Icon name="tasks" size={13} /> Triage
                    </>
                  )}
                </button>
              )}
              {kind !== 'runs' && (
                <button
                  className="btn"
                  title="Review with the code-reviewer agent"
                  disabled={reviewing === it.number}
                  onClick={() => runReview(it)}
                >
                  {reviewing === it.number ? (
                    <>
                      <Spinner size={13} /> Reviewing
                    </>
                  ) : (
                    <>
                      <Icon name="check" size={13} /> Review
                    </>
                  )}
                </button>
              )}
              {onSummarize && kind !== 'runs' && (
                <button
                  className="btn"
                  title="Summarize with the agent"
                  onClick={() =>
                    onSummarize(
                      `Summarize ${kind === 'prs' ? 'pull request' : 'issue'} #${it.number}: "${it.title}". Explain what it is, what changed or is requested, and anything notable.`
                    )
                  }
                >
                  <Icon name="sparkles" size={13} />
                </button>
              )}
              {it.url && (
                <a className="btn" href={it.url} target="_blank" rel="noreferrer">
                  Open
                </a>
              )}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <GithubItemModal
          item={selected}
          kind={kind}
          triaging={triaging}
          reviewing={reviewing}
          onClose={() => setSelected(null)}
          onChat={onSummarize}
          onTriage={runTriage}
          onReview={runReview}
          onMerge={runMerge}
          mergeMethod={mergeMethod}
          onMergeMethod={setMergeMethod}
          merging={merging}
        />
      )}

      {reviewReport && (
        <Modal title={`Review · ${reviewReport.item.title}`} onClose={() => setReviewReport(null)}>
          {reviewReport.error && <p className="error-text">{reviewReport.error}</p>}
          {reviewReport.report && (
            <div
              className="reader-body prose"
              dangerouslySetInnerHTML={{ __html: mdToHtml(reviewReport.report) }}
            />
          )}
          {reviewReport.path && (
            <p className="note">
              Review: <code>{reviewReport.path}</code>
            </p>
          )}
        </Modal>
      )}

      {triageReport && (
        <Modal title={`Triage · ${triageReport.item.title}`} onClose={() => setTriageReport(null)}>
          {triageReport.error && <p className="error-text">{triageReport.error}</p>}
          {triageReport.report && (
            <div
              className="reader-body prose"
              dangerouslySetInnerHTML={{ __html: mdToHtml(triageReport.report) }}
            />
          )}
          {triageReport.path && (
            <p className="note">
              Plan: <code>{triageReport.path}</code>
            </p>
          )}
          <div className="row" style={{ marginTop: 14, marginBottom: 0 }}>
            <button
              className="btn"
              onClick={() => {
                setTriageReport(null)
                if (onOpenTasks) onOpenTasks()
              }}
            >
              <Icon name="tasks" size={14} /> View tasks
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
