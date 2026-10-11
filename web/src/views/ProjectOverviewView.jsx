import { useState } from 'react'
import { api } from '../api.js'
import { DetailItem, DetailRow } from '../components/Detail.jsx'
import { Modal } from '../components/Modal.jsx'
import { Composer, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { fmtTokens, relDate, truncate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'
import { clickable, handleArrowNav } from '../lib/ui.js'

export const WELCOME_SUGGESTIONS = [
  'Explain how this codebase is structured',
  'Find and fix a bug in the repository',
  'Write tests for the core module',
  'Draft a plan for a new feature',
]

export function Stat({ icon, label, value, tone, onClick, sub }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      className={`stat ${tone || ''} ${onClick ? 'clickable' : ''}`}
      onClick={onClick}
    >
      <span className="stat-top">
        <Icon name={icon} size={14} className="stat-icon" />
        <span className="stat-label">{label}</span>
      </span>
      <span className="stat-value-wrap">
        <span className="stat-value">{value}</span>
        {sub && <span className="stat-sub">{sub}</span>}
      </span>
      {onClick && <Icon name="chevronRight" size={14} className="stat-arrow" />}
    </Tag>
  )
}

export const CHANGE_FIELDS = [
  { key: 'commits', label: 'commits', icon: 'git' },
  { key: 'memories', label: 'memories', icon: 'memory' },
  { key: 'files', label: 'files', icon: 'files' },
  { key: 'prs', label: 'PRs', icon: 'git' },
  { key: 'issues', label: 'issues', icon: 'chat' },
  { key: 'failed_runs', label: 'failed runs', icon: 'alert' },
]

export function DocsSection({ projectId }) {
  const [kind, setKind] = useState('architecture')
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const generate = () => {
    setBusy(true)
    setError(null)
    setResult(null)
    api
      .generateDoc(projectId, { kind, topic: kind === 'adr' ? topic : undefined })
      .then(setResult)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="docs-card">
      <div className="docs-head">
        <Icon name="files" size={15} />
        <span>Generated docs</span>
        <span className="muted">from Totem memory</span>
      </div>
      <div className="row" style={{ marginBottom: 0 }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="architecture">Architecture · ARCHITECTURE.md</option>
          <option value="onboarding">Onboarding · ONBOARDING.md</option>
          <option value="adr">ADR · adr/&lt;topic&gt;.md</option>
        </select>
        {kind === 'adr' && (
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Decision topic"
          />
        )}
        <button
          className="btn"
          onClick={generate}
          disabled={busy || (kind === 'adr' && !topic.trim())}
        >
          {busy ? (
            <>
              <Spinner size={13} /> Generating
            </>
          ) : (
            <>
              <Icon name="sparkles" size={13} /> Generate
            </>
          )}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <p className="note">
          Wrote <code>{result.path}</code>. {result.report}
        </p>
      )}
    </div>
  )
}

export function GitDetail({ id, git }) {
  if (!git) return <p className="muted">No repository data.</p>
  if (id === 'commit') {
    const c = git.last_commit
    if (!c) return <p className="muted">No commits yet.</p>
    const r = git.remote?.last_commit
    return (
      <>
        <DetailRow label="Local subject" value={c.subject} />
        <DetailRow label="Local SHA" value={c.sha} />
        <DetailRow label="Author" value={c.author} />
        <DetailRow label="Date" value={relDate(c.date)} />
        {r && (
          <>
            <DetailRow label="Remote" value={git.remote.ref} />
            <DetailRow label="Remote subject" value={r.subject} />
            <DetailRow label="Remote SHA" value={r.sha} />
            <DetailRow label="Remote date" value={relDate(r.date)} />
          </>
        )}
      </>
    )
  }
  return (
    <>
      {id === 'branch' && <DetailRow label="Branch" value={git.branch} />}
      {id === 'branch' && <DetailRow label="HEAD" value={git.head} />}
      <DetailRow label="Ahead" value={`${git.ahead} commit(s)`} />
      <DetailRow label="Behind" value={`${git.behind} commit(s)`} />
      <DetailRow label="Working tree" value={git.dirty ? 'Uncommitted changes' : 'Clean'} />
    </>
  )
}

export function UsageDetail({ usage }) {
  if (!usage) return <p className="muted">No usage recorded yet.</p>
  return (
    <>
      <DetailRow label="Total tokens" value={fmtTokens(usage.total.tokens)} />
      <DetailRow label="Agent runs" value={usage.total.runs} />
      <DetailRow label="This month" value={fmtTokens(usage.month.tokens)} />
      {usage.budget?.budget ? (
        <DetailRow
          label="Monthly budget"
          value={`${fmtTokens(usage.budget.budget)} (${usage.budget.percent}%)`}
        />
      ) : null}
    </>
  )
}

export function TasksDetail({ projectId, onStart }) {
  const { data, loading, error } = useAsync(() => api.listTasks(projectId), [projectId])
  if (loading) return <Skeleton className="row-skeleton" />
  if (error) return <p className="error-text">{error}</p>
  const tasks = (data || []).filter((t) => t.status !== 'done')
  if (!tasks.length) return <p className="muted">No open tasks.</p>
  return (
    <div className="detail-list">
      {tasks.map((t) => (
        <DetailItem
          key={t.id}
          title={t.title}
          sub={`${t.status}${t.priority ? ` · ${t.priority}` : ''}`}
          onChat={() => onStart(`Let's work on the task "${t.title}"`)}
        />
      ))}
    </div>
  )
}

export function GithubDetail({ projectId, kind, state = 'open', max, onStart }) {
  const { data, loading, error } = useAsync(
    () => api.projectGithub(projectId, kind, state),
    [projectId, kind, state]
  )
  if (loading) return <Skeleton className="row-skeleton" />
  if (error) return <p className="error-text">{error}</p>
  if (data && data.available === false)
    return <p className="muted">{data.error || 'GitHub is unavailable for this project.'}</p>
  let items = (data && data.items) || []
  if (max) items = items.slice(0, max)
  if (!items.length) return <p className="muted">Nothing to show.</p>
  const noun = kind === 'prs' ? 'PR' : kind === 'issues' ? 'issue' : 'run'
  return (
    <div className="detail-list">
      {items.map((it) => {
        const key = it.number ?? it.id
        const name = it.title || it.name || `${noun} ${key}`
        return (
          <DetailItem
            key={key}
            title={it.number ? `#${it.number} ${name}` : name}
            sub={[it.state || it.conclusion || it.status, it.user, it.branch]
              .filter(Boolean)
              .join(' · ')}
            url={it.url}
            onChat={() => onStart(`Let's discuss ${noun} ${it.number ? `#${it.number}` : ''}: ${name}`)}
          />
        )
      })}
    </div>
  )
}

export function OverviewDetailModal({ detail, project, git, usage, github, onStart, onClose, onOpenSettings }) {
  return (
    <Modal title={detail.title} onClose={onClose}>
      {['branch', 'commit', 'sync'].includes(detail.id) && (
        <GitDetail id={detail.id} git={git} />
      )}
      {detail.id === 'tasks' && <TasksDetail projectId={project.id} onStart={onStart} />}
      {detail.id === 'tokens' && <UsageDetail usage={usage} />}
      {['prs', 'issues', 'runs', 'ci'].includes(detail.id) && (
        <GithubDetail
          projectId={project.id}
          kind={detail.id === 'ci' ? 'runs' : detail.id}
          max={detail.id === 'ci' ? 1 : undefined}
          onStart={onStart}
        />
      )}
      {detail.id === 'github' && (
        <>
          <p className="muted">{github?.reason || 'GitHub is not connected for this project.'}</p>
          <div className="row" style={{ marginTop: 14, marginBottom: 0 }}>
            <button className="btn primary" onClick={() => onOpenSettings('github')}>
              Open GitHub settings
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}

export function ProjectOverviewView({ project, since, onStart, onNavigate, onOpenSettings, onOpenSession }) {
  const ready = since !== undefined
  const { data, error, loading } = useAsync(
    () => (ready ? api.projectStatus(project.id, since || undefined) : Promise.resolve(null)),
    [project.id, since]
  )
  const usageReq = useAsync(() => api.projectUsage(project.id), [project.id])
  const usage = usageReq.data
  const sessionsReq = useAsync(() => api.listSessions(project.id), [project.id])
  const lastSession = (sessionsReq.data || [])
    .slice()
    .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))[0]
  const firstVisit = since === null
  const git = data?.git
  const remoteCommit = git?.remote?.last_commit
  const remoteSub = remoteCommit
    ? `${git.behind > 0 ? `${git.behind} behind · ` : ''}remote: ${truncate(remoteCommit.subject, 40)}`
    : undefined
  const github = data?.github
  const repoEntries = data?.repos || []
  const multi = repoEntries.length > 1
  const githubStats = multi
    ? {
        available: repoEntries.some((r) => r.github?.available),
        open_prs: repoEntries.reduce((n, r) => n + (r.github?.open_prs || 0), 0),
        open_issues: repoEntries.reduce((n, r) => n + (r.github?.open_issues || 0), 0),
        failing_runs: repoEntries.reduce((n, r) => n + (r.github?.failing_runs || 0), 0),
        latest_run: github?.latest_run,
      }
    : github
  const tasks = data?.tasks
  const changes = data?.changes
  const [detail, setDetail] = useState(null)

  const runTone = (run) => {
    if (!run) return ''
    if (run.conclusion === 'success') return 'ok'
    if (run.conclusion === 'failure') return 'err'
    return ''
  }

  return (
    <div className="overview">
      {!firstVisit && changes && changes.total > 0 && (
        <button
          type="button"
          className="digest clickable"
          onClick={() => onNavigate({ type: 'activity' })}
        >
          <span className="digest-head">
            <Icon name="sparkles" size={16} />
            <span>Since your last visit</span>
          </span>
          <span className="digest-chips">
            {CHANGE_FIELDS.filter((f) => changes.counts[f.key] > 0).map((f) => (
              <span key={f.key} className="digest-chip">
                <Icon name={f.icon} size={12} />
                {changes.counts[f.key]} {f.label}
              </span>
            ))}
          </span>
          <Icon name="chevronRight" size={16} className="digest-arrow" />
        </button>
      )}
      {!firstVisit && changes && changes.total === 0 && (
        <div className="digest caught-up">
          <Icon name="check" size={15} /> You are all caught up since your last visit.
        </div>
      )}

      {usage?.budget?.budget && (
        <button
          type="button"
          className={`digest clickable ${usage.budget.over ? 'budget-critical' : usage.budget.percent >= 80 ? 'budget-alert' : ''}`}
          onClick={() => setDetail({ id: 'tokens', title: 'Token usage' })}
        >
          <span className="digest-head">
            <Icon name="alert" size={16} />
            <span>Token budget</span>
          </span>
          <span className="digest-chips">
            <span className="digest-chip">
              {fmtTokens(usage.month.tokens)} / {fmtTokens(usage.budget.budget)} this month (
              {usage.budget.percent}%)
            </span>
            {usage.budget.enforced && (
              <span className="digest-chip">
                scheduled runs {usage.budget.over ? 'paused' : 'allowed'}
              </span>
            )}
          </span>
          <Icon name="chevronRight" size={16} className="digest-arrow" />
        </button>
      )}

      <div className="overview-hero">
        <div>
          <h1>{project.name}</h1>
          <div className="repo">
            <Icon name="git" size={13} />
            {project.repo_url ? (
              <code>{project.repo_url}</code>
            ) : (
              <span className="muted">workspace-only project</span>
            )}
            {multi && (
              <button
                type="button"
                className="badge clickable"
                onClick={() => onNavigate({ type: 'repos' })}
              >
                {repoEntries.length} repositories
              </button>
            )}
          </div>
        </div>
        <button className="btn" onClick={() => onNavigate({ type: 'tasks' })}>
          <Icon name="tasks" size={14} /> Task board
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {loading || !ready ? (
        <div className="stat-grid">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="stat-skeleton" />
          ))}
        </div>
      ) : (
        <div className="stat-grid" onKeyDown={handleArrowNav}>
          <Stat
            icon="git"
            label="Branch"
            value={git?.branch || 'unknown'}
            onClick={() => setDetail({ id: 'branch', title: 'Branch' })}
          />
          <Stat
            icon="git"
            label="Last commit"
            value={truncate(git?.last_commit?.subject, 42) || 'none'}
            sub={remoteSub}
            onClick={() => setDetail({ id: 'commit', title: 'Last commit' })}
          />
          <Stat
            icon="refresh"
            label="Sync"
            value={
              git && (git.ahead || git.behind)
                ? `${git.ahead}↑ ${git.behind}↓`
                : git?.dirty
                  ? 'Local changes'
                  : 'Up to date'
            }
            onClick={() => setDetail({ id: 'sync', title: 'Sync status' })}
          />
          <Stat
            icon="tasks"
            label="Open tasks"
            value={tasks ? tasks.open : '-'}
            onClick={() => setDetail({ id: 'tasks', title: 'Open tasks' })}
          />
          <Stat
            icon="sparkles"
            label="Tokens used"
            value={usage ? fmtTokens(usage.total.tokens) : '-'}
            onClick={() => setDetail({ id: 'tokens', title: 'Token usage' })}
          />
          {multi && (
            <Stat
              icon="git"
              label="Repositories"
              value={repoEntries.length}
              onClick={() => onNavigate({ type: 'repos' })}
            />
          )}
          {githubStats?.available ? (
            <>
              <Stat
                icon="git"
                label={multi ? 'Open PRs (all)' : 'Open PRs'}
                value={githubStats.open_prs}
                onClick={() => setDetail({ id: 'prs', title: 'Open pull requests' })}
              />
              <Stat
                icon="chat"
                label={multi ? 'Open issues (all)' : 'Open issues'}
                value={githubStats.open_issues}
                onClick={() => setDetail({ id: 'issues', title: 'Open issues' })}
              />
              <Stat
                icon="alert"
                label={multi ? 'Failing runs (all)' : 'Failing runs'}
                value={githubStats.failing_runs}
                tone={githubStats.failing_runs ? 'err' : ''}
                onClick={() => setDetail({ id: 'runs', title: 'CI runs' })}
              />
              <Stat
                icon="play"
                label="Latest CI"
                value={
                  githubStats.latest_run
                    ? githubStats.latest_run.conclusion || githubStats.latest_run.status
                    : 'none'
                }
                tone={runTone(githubStats.latest_run)}
                onClick={() => setDetail({ id: 'ci', title: 'Latest CI run' })}
              />
            </>
          ) : (
            <Stat
              icon="alert"
              label="GitHub"
              value="Not connected"
              onClick={() => setDetail({ id: 'github', title: 'GitHub' })}
            />
          )}
        </div>
      )}

      <button
        type="button"
        className={`digest clickable conversation-card ${lastSession ? '' : 'empty'}`}
        onClick={() => lastSession && onOpenSession && onOpenSession(lastSession.id)}
        disabled={!lastSession}
      >
        <span className="digest-head">
          <Icon name="chat" size={16} />
          <span>Last conversation</span>
        </span>
        <span className="digest-chips">
          <span className="digest-chip">
            {lastSession ? truncate(lastSession.title, 60) : 'No conversations yet'}
          </span>
          {lastSession && <span className="digest-chip">{relDate(lastSession.updated_at)}</span>}
        </span>
        {lastSession && <Icon name="chevronRight" size={16} className="digest-arrow" />}
      </button>

      {multi && (
        <div className="repo-table">
          {repoEntries.map((r) => (
            <button
              key={r.alias}
              type="button"
              className="repo-line clickable"
              onClick={() => onNavigate({ type: 'repos' })}
            >
              <span className="badge accent">{r.alias}</span>
              <span>{r.git?.branch || '—'}</span>
              <span className="muted">{truncate(r.git?.last_commit?.subject, 46) || 'no commits'}</span>
              <span className="muted">
                {r.github?.available
                  ? `${r.github.open_prs} PR · ${r.github.open_issues} issues · ${r.github.failing_runs} failing`
                  : '—'}
              </span>
            </button>
          ))}
        </div>
      )}

      {detail && (
        <OverviewDetailModal
          detail={detail}
          project={project}
          git={git}
          usage={usage}
          github={githubStats}
          onStart={onStart}
          onClose={() => setDetail(null)}
          onOpenSettings={onOpenSettings}
        />
      )}

      <DocsSection projectId={project.id} />

      <div className="overview-prompt">
        <Composer
          busy={false}
          placeholder="Ask anything, or describe a task..."
          onSend={(msg) => onStart(msg)}
        />
      </div>
      <div className="suggestions" onKeyDown={handleArrowNav}>
        {WELCOME_SUGGESTIONS.map((s) => (
          <button key={s} className="suggestion" onClick={() => onStart(s)}>
            <span>{s}</span>
            <Icon name="arrowUp" size={14} className="suggestion-arrow" />
          </button>
        ))}
      </div>
    </div>
  )
}
