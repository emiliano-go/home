import { useState } from 'react'
import { api } from '../api.js'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { relDate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'

export function ReposView({ projectId }) {
  const { data, error, loading, reload } = useAsync(
    () => api.listProjectRepos(projectId, true),
    [projectId]
  )
  const [url, setUrl] = useState('')
  const [alias, setAlias] = useState('')
  const [busy, setBusy] = useState(false)
  const [pulling, setPulling] = useState(null)
  const [removing, setRemoving] = useState(null)
  const [actionError, setActionError] = useState(null)
  const repos = data || []

  const add = (e) => {
    e.preventDefault()
    if (!url.trim() || busy) return
    setBusy(true)
    setActionError(null)
    api
      .addProjectRepo(projectId, { url: url.trim(), alias: alias.trim().toLowerCase() || undefined })
      .then(() => {
        setUrl('')
        setAlias('')
        reload()
      })
      .catch((err) => setActionError(err.message || String(err)))
      .finally(() => setBusy(false))
  }

  const pull = (repoAlias) => {
    setPulling(repoAlias || 'all')
    setActionError(null)
    api
      .pullProject(projectId, repoAlias || undefined)
      .then(reload)
      .catch((err) => setActionError(err.message || String(err)))
      .finally(() => setPulling(null))
  }

  const remove = (repoAlias) => {
    setActionError(null)
    api
      .removeProjectRepo(projectId, repoAlias)
      .then(() => {
        setRemoving(null)
        reload()
      })
      .catch((err) => setActionError(err.message || String(err)))
  }

  return (
    <div className="center-col">
      <div className="page-head">
        <h2>Repositories</h2>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn" onClick={() => pull(null)} disabled={!repos.length || !!pulling}>
            {pulling === 'all' ? <Spinner size={13} /> : <Icon name="refresh" size={14} />} Pull all
          </button>
          <button className="btn" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}
      {actionError && <p className="error-text">{actionError}</p>}
      {loading && !data && <Skeleton className="block-skeleton" />}

      {!loading && repos.length === 0 && (
        <SectionEmpty
          icon="git"
          title="No repositories yet"
          hint="Workspace-only project: the agent can write plans and notes, but has no code access until you add a Git URL below."
        />
      )}

      <div className="cards">
        {repos.map((r) => (
          <div key={r.alias} className="card repo-card">
            <h3>
              <span className="badge accent">{r.alias}</span>
              {r.is_primary && <span className="badge">primary</span>}
            </h3>
            <div className="meta">
              <a href={r.repo_url} target="_blank" rel="noreferrer">
                {r.repo_url}
              </a>
            </div>
            <div className="meta">
              {r.status?.branch || '—'} · {r.status?.head || 'no commits'}
            </div>
            {r.status?.last_commit && (
              <div className="meta">
                {r.status.last_commit.short} · {r.status.last_commit.author} ·{' '}
                {relDate(r.status.last_commit.date)}
              </div>
            )}
            <div className="meta">
              {r.status?.dirty ? 'local changes' : 'clean'}
              {r.status?.ahead || r.status?.behind
                ? ` · ${r.status.ahead}↑ ${r.status.behind}↓`
                : ''}
            </div>
            {r.github?.available && (
              <div className="meta">
                {r.github.open_prs} PRs · {r.github.open_issues} issues ·{' '}
                {r.github.failing_runs} failing runs
              </div>
            )}
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" onClick={() => pull(r.alias)} disabled={!!pulling}>
                {pulling === r.alias ? <Spinner size={13} /> : 'Pull'}
              </button>
              {removing === r.alias ? (
                <>
                  <button className="btn danger" onClick={() => remove(r.alias)}>
                    Confirm remove
                  </button>
                  <button className="btn" onClick={() => setRemoving(null)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  className="btn"
                  title={
                    repos.length === 1
                      ? 'Removing the last repo makes this a workspace-only project'
                      : 'Remove this repo and its clone'
                  }
                  onClick={() => setRemoving(r.alias)}
                >
                  Remove
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h3>Add repository</h3>
          <p>Clone another Git repository into this project.</p>
        </div>
        <form className="row" onSubmit={add} style={{ marginBottom: 0 }}>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/org/repo.git"
            disabled={busy}
          />
          <input
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="alias (auto)"
            style={{ maxWidth: 160 }}
            disabled={busy}
          />
          <button className="btn primary" disabled={busy || !url.trim()}>
            {busy ? <Spinner size={13} /> : 'Add'}
          </button>
        </form>
      </section>
    </div>
  )
}
