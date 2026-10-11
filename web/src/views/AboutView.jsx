import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { ConfirmModal } from '../components/Modal.jsx'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { fmtDate, fmtTokens } from '../lib/format.js'
import { useAsync } from '../lib/hooks.js'

export function AboutView({ projectId, onDeleted }) {
  const { data: project, error, loading, reload } = useAsync(
    () => api.getProject(projectId),
    [projectId]
  )
  const usageReq = useAsync(() => api.projectUsage(projectId), [projectId])
  const usage = usageReq.data
  const notifyReq = useAsync(api.notifyStatus, [])
  const [pulling, setPulling] = useState(false)
  const [pullOutput, setPullOutput] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [confirmWrites, setConfirmWrites] = useState(false)
  const [budget, setBudget] = useState('')
  const [enforce, setEnforce] = useState(false)
  const [savingBudget, setSavingBudget] = useState(false)
  const [testingNotify, setTestingNotify] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [sandboxBusy, setSandboxBusy] = useState(false)
  const [notifyResult, setNotifyResult] = useState(null)
  const [notifyError, setNotifyError] = useState(null)

  useEffect(() => {
    if (project) {
      setBudget(project.token_budget ?? '')
      setEnforce(!!project.budget_enforced)
    }
  }, [project])

  if (loading) return <p className="note">Loading...</p>
  if (error) return <p className="error-text">{error}</p>
  if (!project) return null

  const status = project.status || {}

  const pull = () => {
    setPulling(true)
    setActionError(null)
    setPullOutput(null)
    api
      .pullProject(project.id)
      .then((r) => {
        setPullOutput(r.output || '')
        reload()
      })
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setPulling(false))
  }

  const setWrites = (enabled) => {
    setActionError(null)
    api
      .setGitWrites(project.id, enabled)
      .then(() => {
        setConfirmWrites(false)
        reload()
      })
      .catch((e) => setActionError(e.message || String(e)))
  }

  const undoTurn = () => {
    setUndoing(true)
    setActionError(null)
    api
      .revertProject(project.id)
      .then(() => reload())
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setUndoing(false))
  }

  const promoteSandbox = () => {
    setSandboxBusy(true)
    setActionError(null)
    api
      .promoteSandbox(project.id)
      .then(() => reload())
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setSandboxBusy(false))
  }

  const discardSandbox = () => {
    setSandboxBusy(true)
    setActionError(null)
    api
      .discardSandbox(project.id)
      .then(() => reload())
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setSandboxBusy(false))
  }

  const saveBudget = () => {
    setSavingBudget(true)
    setActionError(null)
    api
      .updateProject(project.id, {
        token_budget: budget === '' ? 0 : Number(budget),
        budget_enforced: enforce,
      })
      .then(() => {
        reload()
        usageReq.reload()
      })
      .catch((e) => setActionError(e.message || String(e)))
      .finally(() => setSavingBudget(false))
  }

  const testNotify = () => {
    setTestingNotify(true)
    setNotifyError(null)
    setNotifyResult(null)
    api
      .notifyTest()
      .then(setNotifyResult)
      .catch((e) => setNotifyError(e.message || String(e)))
      .finally(() => setTestingNotify(false))
  }

  return (
    <div className="center-col">
      <div className="page-head">
        <h2>About</h2>
        <button className="btn danger" onClick={() => setConfirmDelete(true)}>
          Delete project
        </button>
      </div>
      {confirmDelete && (
        <ConfirmModal
          title="Delete project"
          confirmLabel="Delete"
          danger
          onClose={() => setConfirmDelete(false)}
          onConfirm={() =>
            api
              .deleteProject(project.id)
              .then(onDeleted)
              .catch((e) => {
                setConfirmDelete(false)
                setActionError(e.message)
              })
          }
        >
          <p className="note">
            Delete <strong>{project.name}</strong>? This removes its registry entry and local
            clone. This cannot be undone.
          </p>
        </ConfirmModal>
      )}
      <dl className="kv">
        <dt>Description</dt>
        <dd>{project.description || '—'}</dd>
        <dt>Repositories</dt>
        <dd>
          {(project.repos || []).length === 0 ? (
            <span className="muted">none (workspace-only project)</span>
          ) : (
            <div className="about-repos">
              {project.repos.map((r) => (
                <div key={r.alias} className="about-repo">
                  <span className="badge accent">{r.alias}</span>
                  {r.is_primary && <span className="badge">primary</span>}
                  <a href={r.repo_url} target="_blank" rel="noreferrer">
                    {r.repo_url}
                  </a>
                  <span className="muted" style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                    {r.local_path}
                  </span>
                </div>
              ))}
            </div>
          )}
        </dd>
        <dt>Branch</dt>
        <dd>{status.branch || 'unknown'}</dd>
        <dt>Head</dt>
        <dd style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{status.head || 'unknown'}</dd>
        <dt>Created</dt>
        <dd>{fmtDate(project.created_at)}</dd>
      </dl>
      <div className="row">
        <button className="btn" onClick={pull} disabled={pulling}>
          {pulling ? 'Pulling...' : 'Pull latest'}
        </button>
      </div>
      {actionError && <p className="error-text">{actionError}</p>}
      {pullOutput !== null && <pre>{pullOutput || '(no output)'}</pre>}
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        Token usage
      </h3>
      {usage && usage.total.runs > 0 ? (
        <>
          <p className="note">
            {fmtTokens(usage.total.tokens)} tokens across {usage.total.runs} agent runs ·{' '}
            {fmtTokens(usage.total.prompt_tokens)} prompt / {fmtTokens(usage.total.completion_tokens)}{' '}
            completion
          </p>
          <div className="usage-list">
            {usage.by_action.map((a) => (
              <div key={a.action} className="usage-row">
                <span className="usage-name">{a.action}</span>
                <span className="muted">{a.runs} runs</span>
                <span>{fmtTokens(a.tokens)}</span>
              </div>
            ))}
            {usage.by_session.map((s) => (
              <div key={`session-${s.session_id}`} className="usage-row">
                <span className="usage-name">
                  <Icon name="chat" size={13} /> {s.title}
                </span>
                <span className="muted">{s.runs} runs</span>
                <span>{fmtTokens(s.tokens)}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className="note">No usage recorded yet.</p>
      )}
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        Monthly budget
      </h3>
      <p className="note">
        {usage && usage.month
          ? `${fmtTokens(usage.month.tokens)} tokens used this month.`
          : 'No usage this month.'}{' '}
        Leave the budget empty for unlimited.
      </p>
      <div className="row">
        <input
          type="number"
          min="0"
          style={{ maxWidth: 160 }}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          placeholder="Unlimited"
        />
        <label className="dep-item" style={{ flex: 'none' }}>
          <input
            type="checkbox"
            checked={enforce}
            onChange={(e) => setEnforce(e.target.checked)}
          />
          Skip scheduled runs when the budget is spent
        </label>
        <button className="btn" onClick={saveBudget} disabled={savingBudget}>
          {savingBudget ? <Spinner size={13} /> : 'Save budget'}
        </button>
      </div>
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        Git writes
      </h3>
      {project.allow_git_writes ? (
        <>
          <p className="note warn-text">
            <Icon name="alert" size={13} /> Enabled: the agent can write files into the clone,
            create branches, commit, push, and open pull requests.
          </p>
          <label className="dep-item" style={{ flex: 'none' }}>
            <input
              type="checkbox"
              checked={!!project.require_write_approval}
              onChange={(e) =>
                api
                  .updateProject(project.id, { require_write_approval: e.target.checked })
                  .then(reload)
                  .catch((err) => setActionError(err.message))
              }
            />
            Require your approval before push or PR
          </label>
          <label className="dep-item" style={{ flex: 'none' }}>
            <input
              type="checkbox"
              checked={!!project.require_plan}
              onChange={(e) =>
                api
                  .updateProject(project.id, { require_plan: e.target.checked })
                  .then(reload)
                  .catch((err) => setActionError(err.message))
              }
            />
            Require a written plan, with a drift check after each step
          </label>
          <label className="dep-item" style={{ flex: 'none' }}>
            <span className="muted">Write mode</span>
            <select
              value={project.write_mode || 'auto'}
              onChange={(e) =>
                api
                  .updateProject(project.id, { write_mode: e.target.value })
                  .then(reload)
                  .catch((err) => setActionError(err.message))
              }
            >
              <option value="ask">ask — approve each edit and command</option>
              <option value="auto">auto — edits and shell run freely</option>
              <option value="yolo">yolo — auto, for throwaway sandboxes</option>
            </select>
          </label>
          <div className="row">
            <button className="btn" onClick={undoTurn} disabled={undoing}>
              {undoing ? 'Reverting…' : 'Undo last turn'}
            </button>
            <span className="muted">
              Restores the clone to the snapshot taken before the last turn.
            </span>
          </div>
          {project.write_mode === 'yolo' && (
            <div className="row">
              <button className="btn" onClick={promoteSandbox} disabled={sandboxBusy}>
                Promote sandbox
              </button>
              <button className="btn danger" onClick={discardSandbox} disabled={sandboxBusy}>
                Discard sandbox
              </button>
              <span className="muted">Yolo turns run against a throwaway /tmp clone.</span>
            </div>
          )}
          <div className="row">
            <button className="btn danger" onClick={() => setWrites(false)}>
              Disable git writes
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="note">
            Disabled: project code is read-only. Enable to let the agent make code changes on a
            branch, push, and open pull requests.
          </p>
          <div className="row">
            <button className="btn" onClick={() => setConfirmWrites(true)}>
              <Icon name="alert" size={14} /> Enable git writes…
            </button>
          </div>
          {confirmWrites && (
            <ConfirmModal
              title="Enable git writes"
              confirmLabel="Confirm enable"
              danger
              onClose={() => setConfirmWrites(false)}
              onConfirm={() => setWrites(true)}
            >
              <p className="note">
                Let the agent modify the clone? It will be able to write files, create branches,
                commit, push, and open pull requests.
              </p>
            </ConfirmModal>
          )}
        </>
      )}
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        Browser
      </h3>
      <p className="note">
        The agent can browse public sites. Allow localhost so it can debug this project's dev
        server (for example <code>http://localhost:5173</code>).
      </p>
      <label className="dep-item" style={{ flex: 'none' }}>
        <input
          type="checkbox"
          checked={!!project.allow_local_browser}
          onChange={(e) =>
            api
              .updateProject(project.id, { allow_local_browser: e.target.checked })
              .then(reload)
              .catch((err) => setActionError(err.message))
          }
        />
        Allow the browser to reach localhost and private addresses
      </label>
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        Notifications
      </h3>
      {notifyReq.data && notifyReq.data.configured.length > 0 ? (
        <>
          <p className="note">
            Channels: {notifyReq.data.configured.join(', ')}. The agent can push with the{' '}
            <code>notify</code> tool; new inbox items and scheduled runs notify automatically.
          </p>
          <div className="row">
            <button className="btn" onClick={testNotify} disabled={testingNotify}>
              {testingNotify ? (
                <>
                  <Spinner size={13} /> Sending
                </>
              ) : (
                <>
                  <Icon name="sparkles" size={13} /> Send test notification
                </>
              )}
            </button>
          </div>
        </>
      ) : (
        <p className="note">
          No channel configured. Set <code>NTFY_TOPIC</code> (optionally <code>NTFY_URL</code>,{' '}
          <code>NTFY_TOKEN</code>), or <code>TELEGRAM_BOT_TOKEN</code> +{' '}
          <code>TELEGRAM_CHAT_ID</code>, then restart Hestia.
        </p>
      )}
      {notifyResult && (
        <p className="note">
          Sent via {Object.entries(notifyResult).map(([k, v]) => `${k} (${v.ok ? 'ok' : 'failed'})`).join(', ')}.
        </p>
      )}
      {notifyError && <p className="error-text">{notifyError}</p>}
      <h3 className="faint" style={{ fontSize: 13, fontWeight: 600 }}>
        AGENTS.md
      </h3>
      <pre>{project.agents_md || '(empty)'}</pre>
    </div>
  )
}
