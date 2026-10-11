import { useState } from 'react'
import { api } from '../api.js'
import { loginWithPasskey, passkeysSupported, registerPasskey } from '../auth.js'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { fmtBytes, greeting, relDate } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'
import { mdToHtml } from '../lib/markdown.js'
import { UpcomingReminders } from './RemindersView.jsx'

export function LoginView({ status, onAuthed }) {
  const [setupToken, setSetupToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const supported = passkeysSupported()

  const run = (fn) => {
    setBusy(true)
    setError(null)
    fn()
      .then(onAuthed)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setBusy(false))
  }

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-logo">
          <Icon name="flame" size={22} />
        </div>
        <h1>Hestia</h1>
        <p className="note">Sign in with a passkey to continue.</p>
        {!supported && (
          <p className="error-text">This browser does not support passkeys (WebAuthn).</p>
        )}
        {error && <p className="error-text">{error}</p>}
        {status.has_passkeys && (
          <button
            className="btn primary"
            disabled={busy || !supported}
            onClick={() => run(loginWithPasskey)}
          >
            {busy ? <Spinner size={13} /> : <Icon name="check" size={14} />} Sign in with passkey
          </button>
        )}
        <div className="login-setup">
          <div className="field-label">
            {status.has_passkeys ? 'Add another passkey (recovery)' : 'Register a passkey'}
          </div>
          <div className="row" style={{ marginBottom: 0 }}>
            <input
              type="password"
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
              placeholder="Setup token"
            />
            <button
              className="btn"
              disabled={busy || !supported || !setupToken}
              onClick={() => run(() => registerPasskey(setupToken))}
            >
              {status.has_passkeys ? 'Add passkey' : 'Register'}
            </button>
          </div>
          <div className="field-hint">
            The setup token is the <code>HESTIA_SETUP_TOKEN</code> environment variable.
          </div>
        </div>
      </div>
    </div>
  )
}

export function inboxStatus(item) {
  const text = `${item.title || ''} ${item.subtitle || ''}`.toLowerCase()
  const isFail = /fail|error|red|timed.?out|cancel|behind|pending pull/.test(text)
  const isOk = /success|pass|green|completed|merged|resolved|fixed/.test(text)
  const isPending = /progress|pending|running|queued|waiting|behind|behind origin/.test(text)

  if (item.kind === 'run') {
    if (isOk && !isFail) return { icon: 'check', tone: 'ok' }
    if (isPending && !isFail) return { icon: 'clock', tone: 'pending' }
    return { icon: 'alert', tone: 'fail' }
  }
  if (item.kind === 'pull') return { icon: 'refresh', tone: 'pending' }
  if (item.kind === 'pr') {
    if (isFail) return { icon: 'git', tone: 'fail' }
    if (isOk) return { icon: 'check', tone: 'ok' }
    return { icon: 'git', tone: 'info' }
  }
  if (item.kind === 'issue') {
    if (isFail) return { icon: 'alert', tone: 'fail' }
    if (isOk) return { icon: 'check', tone: 'ok' }
    return { icon: 'chat', tone: 'info' }
  }
  if (isFail) return { icon: 'alert', tone: 'fail' }
  if (isOk) return { icon: 'check', tone: 'ok' }
  if (isPending) return { icon: 'clock', tone: 'pending' }
  return { icon: 'git', tone: 'info' }
}

export function InboxCard({ onOpenProject, onStartChat }) {
  const { data, loading, reload } = useAsync(api.listInbox, [])
  const [polling, setPolling] = useState(false)
  const [busy, setBusy] = useState(null)
  const [report, setReport] = useState(null)
  const [actionError, setActionError] = useState(null)
  const items = (data && data.items) || []
  const unread = (data && data.unread) || 0

  if (loading || items.length === 0) return null

  const poll = () => {
    setPolling(true)
    api
      .pollInbox()
      .then(reload)
      .catch(() => {})
      .finally(() => setPolling(false))
  }

  const open = (item) => {
    if (!item.read) api.markInboxRead(item.id).then(reload).catch(() => {})
    if (item.url) window.open(item.url, '_blank', 'noreferrer')
    else onOpenProject(item.project_id)
  }

  const triage = (item) => {
    const [kind, number] = (item.external_id || '').split(':')
    if (!number) return
    setBusy(item.id)
    setActionError(null)
    api
      .triage(item.project_id, { kind: kind === 'pr' ? 'pr' : 'issue', number: Number(number) })
      .then((r) => setReport({ ...r, item }))
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setBusy(null))
  }

  const diagnose = (item) => {
    if (!item.read) api.markInboxRead(item.id).then(reload).catch(() => {})
    onStartChat(
      item.project_id,
      `Investigate this CI failure from the inbox and propose a fix.\n\nRun: ${item.title}\nURL: ${item.url || '(none)'}\n\nUse gh_ci_runs to fetch the run and its failed jobs, find the likely cause, and write findings to the workspace with workspace_write.`
    )
  }

  const pull = (item) => {
    setBusy(item.id)
    setActionError(null)
    api
      .pullProject(item.project_id)
      .then(() => {
        if (!item.read) api.markInboxRead(item.id).catch(() => {})
        reload()
      })
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setBusy(null))
  }

  return (
    <>
      <div className="inbox-head">
        <h2>
          <Icon name="inbox" size={15} /> Inbox
          {unread > 0 && <span className="badge accent">{unread} new</span>}
        </h2>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn" onClick={poll} disabled={polling}>
            {polling ? <Spinner size={13} /> : <Icon name="refresh" size={13} />} Check now
          </button>
          {unread > 0 && (
            <button className="btn" onClick={() => api.markAllInboxRead().then(reload).catch(() => {})}>
              <Icon name="check" size={13} /> Mark all read
            </button>
          )}
        </div>
      </div>
      <section className="inbox-card">
      {actionError && <p className="error-text">{actionError}</p>}
      <div className="home-list">
        {items.slice(0, 6).map((item) => {
          const status = inboxStatus(item)
          return (
          <button
            key={item.id}
            className={`home-row inbox-item ${item.read ? '' : 'unread'}`}
            onClick={() => open(item)}
          >
            <span className={`home-row-icon status-${status.tone}`}>
              <Icon name={status.icon} size={15} />
            </span>
            <span className="home-row-main">
              <span className="home-row-title">{item.title}</span>
              <span className="home-row-sub">
                {item.project} · {item.subtitle}
              </span>
            </span>
            <span className="home-row-time">{relDate(item.created_at)}</span>
            <span className="inbox-actions" onClick={(e) => e.stopPropagation()}>
              {item.kind === 'pull' ? (
                <button className="btn primary" disabled={busy === item.id} onClick={() => pull(item)}>
                  {busy === item.id ? (
                    <>
                      <Spinner size={13} /> Pulling
                    </>
                  ) : (
                    <>
                      <Icon name="refresh" size={13} /> Pull
                    </>
                  )}
                </button>
              ) : item.kind === 'run' ? (
                <button className="btn" onClick={() => diagnose(item)}>
                  <Icon name="sparkles" size={13} /> Diagnose
                </button>
              ) : (
                <button className="btn" disabled={busy === item.id} onClick={() => triage(item)}>
                  {busy === item.id ? (
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
            </span>
          </button>
          )
        })}
      </div>
      {report && (
        <Modal title={`Triage · ${report.item.title}`} onClose={() => setReport(null)}>
          <div
            className="reader-body prose"
            dangerouslySetInnerHTML={{ __html: mdToHtml(report.report || '') }}
          />
          {report.path && (
            <p className="note">
              Plan: <code>{report.path}</code>
            </p>
          )}
        </Modal>
      )}
      </section>
    </>
  )
}

export function HomeView({ onOpenProject, onOpenSession, onOpenFile, onNewProject, onNavigate, onStartChat }) {
  const { data, error, loading } = useAsync(api.activity, [])
  const { data: settings } = useAsync(api.getSettings, [])
  const counts = (data && data.counts) || { projects: 0, sessions: 0, files: 0 }
  const projects = (data && data.projects) || []
  const sessions = (data && data.sessions) || []
  const files = (data && data.files) || []

  return (
    <div className="home">
      <header className="home-hero">
        <div>
          <h1>{greeting((settings && settings.user_name) || '')}</h1>
          <p>Your projects, recent conversations, and agent-generated files in one place.</p>
        </div>
        <button className="btn primary" onClick={onNewProject}>
          <Icon name="plus" size={15} /> New project
        </button>
      </header>

      {error && <p className="error-text">{error}</p>}

      <InboxCard onOpenProject={onOpenProject} onStartChat={onStartChat} />

      <UpcomingReminders onNavigate={onNavigate} />

      {!loading && counts.projects === 0 && (
        <div className="banner">
          <div className="banner-icon">
            <Icon name="sparkles" size={22} />
          </div>
          <div className="banner-body">
            <h3>No projects yet</h3>
            <p>
              Register a Git repository to get an agent-aware workspace with chat, memory, and
              generated files.
            </p>
          </div>
          <button className="btn primary" onClick={onNewProject}>
            <Icon name="plus" size={15} /> Create your first project
          </button>
        </div>
      )}

      <section className="home-section">
        <div className="home-section-head">
          <h2>Recent projects</h2>
          {onNavigate && (
            <button className="link-btn" onClick={() => onNavigate({ type: 'help' })}>
              <Icon name="help" size={13} /> How it works
            </button>
          )}
        </div>
        {loading ? (
          <div className="cards">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="card-skeleton" />
            ))}
          </div>
        ) : projects.length === 0 ? (
          <SectionEmpty
            icon="folder"
            title="No projects yet"
            hint="Add a Git repository to begin."
            action={
              <button className="btn" onClick={onNewProject}>
                <Icon name="plus" size={14} /> Add a project
              </button>
            }
          />
        ) : (
          <div className="cards">
            {projects.map((p) => (
              <button key={p.id} className="project-card" onClick={() => onOpenProject(p.id)}>
                <div className="project-card-top">
                  <span className="proj-avatar big">{p.name.slice(0, 1)}</span>
                  <span className="project-card-name">{p.name}</span>
                </div>
                <div className="project-card-repo">
                  <Icon name="git" size={12} />
                  <span>{p.repo_url}</span>
                </div>
                <div className="project-card-foot">
                  <Icon name="clock" size={12} />
                  {relDate(p.last_opened_at || p.created_at)}
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="home-grid">
        <section className="home-section">
          <div className="home-section-head">
            <h2>Recent conversations</h2>
          </div>
          {loading ? (
            <div className="home-list">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="row-skeleton" />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <SectionEmpty
              icon="chat"
              title="No conversations yet"
              hint="Open a project and ask the agent something."
            />
          ) : (
            <div className="home-list">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  className="home-row"
                  onClick={() => onOpenSession(s.project_id, s.id)}
                >
                  <span className="home-row-icon">
                    <Icon name="chat" size={15} />
                  </span>
                  <span className="home-row-main">
                    <span className="home-row-title">{s.title || 'Untitled'}</span>
                    <span className="home-row-sub">{s.project}</span>
                  </span>
                  <span className="home-row-time">{relDate(s.updated_at)}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="home-section">
          <div className="home-section-head">
            <h2>Recent files</h2>
          </div>
          {loading ? (
            <div className="home-list">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="row-skeleton" />
              ))}
            </div>
          ) : files.length === 0 ? (
            <SectionEmpty
              icon="files"
              title="No generated files yet"
              hint="Ask the agent to write a plan or spec."
            />
          ) : (
            <div className="home-list">
              {files.map((f) => (
                <button
                  key={`${f.project_id}:${f.path}`}
                  className="home-row"
                  onClick={() => onOpenFile(f)}
                >
                  <span className="home-row-icon">
                    <Icon name="files" size={15} />
                  </span>
                  <span className="home-row-main">
                    <span className="home-row-title">{f.path}</span>
                    <span className="home-row-sub">
                      {f.project} · {fmtBytes(f.bytes)}
                    </span>
                  </span>
                  <span className="home-row-time">{relDate(f.modified)}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
