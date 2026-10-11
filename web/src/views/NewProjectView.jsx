import { useState } from 'react'
import { api } from '../api.js'
import { Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

const STEPS = ['Basics', 'Repositories', 'Options', 'Review']

function slugPreview(name) {
  return (name || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function aliasFromUrl(url) {
  const last = (url || '')
    .trim()
    .replace(/\/+$/, '')
    .replace(/\.git$/, '')
    .split('/')
    .pop()
  return (last || '')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
}

function defaultRepo() {
  return { url: '', alias: '', primary: true }
}

export function NewProjectView({ onCreated, onCancel }) {
  const providersReq = useAsync(api.listProviders, [])
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [repos, setRepos] = useState([defaultRepo()])
  const [providerId, setProviderId] = useState('')
  const [gitWrites, setGitWrites] = useState(false)
  const [localBrowser, setLocalBrowser] = useState(false)
  const [creating, setCreating] = useState(false)
  const [steps, setSteps] = useState([])
  const [percent, setPercent] = useState(null)
  const [detail, setDetail] = useState('')
  const [error, setError] = useState(null)

  const providers = providersReq.data || []
  const filledRepos = repos.filter((r) => r.url.trim())

  const setRepo = (index, patch) => {
    setRepos((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }
  const addRepo = () => setRepos((prev) => [...prev, { ...defaultRepo(), primary: prev.length === 0 }])
  const removeRepo = (index) => {
    setRepos((prev) => {
      const next = prev.filter((_, i) => i !== index)
      if (next.length && !next.some((r) => r.primary)) next[0].primary = true
      return next.length ? next : [defaultRepo()]
    })
  }
  const setPrimary = (index) =>
    setRepos((prev) => prev.map((r, i) => ({ ...r, primary: i === index })))

  const aliasFor = (repo) => repo.alias.trim().toLowerCase() || aliasFromUrl(repo.url)

  const stepError = () => {
    if (step === 0) {
      if (!name.trim()) return 'Give the project a name.'
      if (!slugPreview(name)) return 'The name needs at least one letter or digit.'
    }
    if (step === 1) {
      const aliases = filledRepos.map(aliasFor).filter(Boolean)
      if (aliases.length !== new Set(aliases).size) return 'Repo aliases must be unique.'
      for (const alias of aliases) {
        if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(alias)) {
          return `Alias "${alias}" is invalid: lowercase letters, digits, - or _ (max 32).`
        }
      }
    }
    return null
  }

  const next = () => {
    const problem = stepError()
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setStep((s) => Math.min(s + 1, STEPS.length - 1))
  }

  const create = () => {
    setCreating(true)
    setError(null)
    setSteps([])
    setPercent(null)
    setDetail('')
    const payload = {
      name: name.trim(),
      description: description.trim(),
      repos: filledRepos.map((r) => ({
        url: r.url.trim(),
        alias: aliasFor(r) || undefined,
        primary: r.primary,
      })),
      provider_id: providerId ? Number(providerId) : undefined,
      allow_git_writes: gitWrites,
      allow_local_browser: localBrowser,
    }
    api
      .createProjectStream(payload, {
        onEvent: (evt) => {
          if (evt.event === 'step') {
            setSteps((prev) => {
              const next = prev.filter((s) => s.step !== evt.step)
              const existing = prev.find((s) => s.step === evt.step)
              next.push({
                step: evt.step,
                label: evt.label || existing?.label || evt.step,
                status: evt.status,
              })
              return next
            })
          } else if (evt.event === 'progress') {
            setPercent(evt.percent)
            if (evt.detail) setDetail(evt.detail)
          } else if (evt.event === 'error') {
            setError(evt.detail || 'Could not create the project')
            setCreating(false)
          } else if (evt.event === 'done') {
            onCreated(evt.project)
          }
        },
      })
      .catch((err) => {
        setError(err.message || String(err))
        setCreating(false)
      })
  }

  return (
    <div className="center-col wizard">
      <div className="page-head">
        <h2>New project</h2>
        {onCancel && (
          <button className="btn" onClick={onCancel} disabled={creating}>
            Cancel
          </button>
        )}
      </div>

      <div className="wizard-steps">
        {STEPS.map((label, i) => (
          <button
            key={label}
            type="button"
            className={`wizard-step ${i === step ? 'on' : ''} ${i < step ? 'done' : ''}`}
            onClick={() => !creating && i < step && setStep(i)}
          >
            <span className="wizard-step-num">{i < step ? <Icon name="check" size={12} /> : i + 1}</span>
            {label}
          </button>
        ))}
      </div>

      {step === 0 && (
        <section className="panel">
          <div className="panel-head">
            <h3>Basics</h3>
            <p>Name the workspace. It can start empty and get repositories later.</p>
          </div>
          <label className="field">
            <span className="field-label">Name</span>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Acme platform"
              disabled={creating}
            />
            <span className="field-hint">
              Stored under <code>repos/{slugPreview(name) || '…'}</code>
            </span>
          </label>
          <label className="field">
            <span className="field-label">Description (optional)</span>
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this project? Shown on the overview."
              disabled={creating}
            />
          </label>
        </section>
      )}

      {step === 1 && (
        <section className="panel">
          <div className="panel-head">
            <h3>Repositories</h3>
            <p>
              One or many Git repositories, each with a short alias the agent uses
              (for example <code>api</code> or <code>web</code>). Leave the list
              empty for a workspace-only project.
            </p>
          </div>
          {repos.map((repo, i) => (
            <div key={i} className="repo-row">
              <label className="field">
                <span className="field-label">Git URL</span>
                <input
                  value={repo.url}
                  onChange={(e) => setRepo(i, { url: e.target.value })}
                  placeholder="https://github.com/org/repo.git"
                  disabled={creating}
                />
              </label>
              <label className="field narrow">
                <span className="field-label">Alias</span>
                <input
                  value={repo.alias}
                  onChange={(e) => setRepo(i, { alias: e.target.value })}
                  placeholder={aliasFromUrl(repo.url) || 'auto'}
                  disabled={creating}
                />
              </label>
              <label className="dep-item repo-primary">
                <input
                  type="radio"
                  name="primary-repo"
                  checked={repo.primary}
                  onChange={() => setPrimary(i)}
                  disabled={creating}
                />
                primary
              </label>
              <button
                type="button"
                className="icon-btn"
                title="Remove repository"
                onClick={() => removeRepo(i)}
                disabled={creating}
              >
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
          <div className="row">
            <button type="button" className="btn" onClick={addRepo} disabled={creating}>
              <Icon name="plus" size={14} /> Add repository
            </button>
          </div>
          {filledRepos.length === 0 && (
            <p className="note">
              No repositories: the project gets workspace tools only until you add
              one (the agent can do it later with <code>repo_add</code>).
            </p>
          )}
        </section>
      )}

      {step === 2 && (
        <section className="panel">
          <div className="panel-head">
            <h3>Options</h3>
            <p>All of these can be changed later in the project's About tab.</p>
          </div>
          <label className="field">
            <span className="field-label">Default provider (optional)</span>
            <select
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
              disabled={creating}
            >
              <option value="">App default</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} {p.model ? `(${p.model})` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="dep-item" style={{ flex: 'none' }}>
            <input
              type="checkbox"
              checked={gitWrites}
              onChange={(e) => setGitWrites(e.target.checked)}
              disabled={creating}
            />
            Enable git writes (the agent may branch, commit, push, and open PRs)
          </label>
          <label className="dep-item" style={{ flex: 'none' }}>
            <input
              type="checkbox"
              checked={localBrowser}
              onChange={(e) => setLocalBrowser(e.target.checked)}
              disabled={creating}
            />
            Allow the browser to reach localhost (UI debugging on dev servers)
          </label>
        </section>
      )}

      {step === 3 && (
        <section className="panel">
          <div className="panel-head">
            <h3>Review</h3>
            <p>Creating clones every repository; this can take a while.</p>
          </div>
          <div className="review-list">
            <div className="review-row">
              <span className="review-key">Name</span>
              <span>{name}</span>
            </div>
            {description && (
              <div className="review-row">
                <span className="review-key">Description</span>
                <span>{description}</span>
              </div>
            )}
            <div className="review-row">
              <span className="review-key">Repositories</span>
              <span>
                {filledRepos.length === 0
                  ? 'none (workspace-only)'
                  : filledRepos
                      .map((r) => `${aliasFor(r) || 'auto'}${r.primary ? ' (primary)' : ''}`)
                      .join(', ')}
              </span>
            </div>
            <div className="review-row">
              <span className="review-key">Provider</span>
              <span>
                {providerId
                  ? providers.find((p) => String(p.id) === providerId)?.name || providerId
                  : 'app default'}
              </span>
            </div>
            <div className="review-row">
              <span className="review-key">Options</span>
              <span>
                {[gitWrites && 'git writes', localBrowser && 'local browser']
                  .filter(Boolean)
                  .join(', ') || 'defaults'}
              </span>
            </div>
          </div>

          {creating && (
            <div className="clone-steps">
              {steps.map((s) => (
                <div key={s.step} className={`clone-step ${s.status}`}>
                  <span className="clone-step-icon">
                    {s.status === 'done' ? <Icon name="check" size={12} /> : <Spinner size={12} />}
                  </span>
                  <span className="clone-step-label">{s.label}</span>
                  {s.step.startsWith('clone') && s.status === 'running' && percent != null && (
                    <span className="clone-step-pct">{percent}%</span>
                  )}
                </div>
              ))}
              {detail && <div className="clone-detail">{detail}</div>}
            </div>
          )}
        </section>
      )}

      {error && <div className="error-banner">{error}</div>}

      <div className="row wizard-actions">
        {step > 0 && (
          <button className="btn" onClick={() => setStep((s) => s - 1)} disabled={creating}>
            Back
          </button>
        )}
        {step < STEPS.length - 1 ? (
          <button className="btn primary" onClick={next} disabled={creating}>
            Continue
          </button>
        ) : (
          <button className="btn primary" onClick={create} disabled={creating}>
            {creating ? (
              <>
                <Spinner size={14} /> Creating
              </>
            ) : (
              'Create project'
            )}
          </button>
        )}
      </div>
    </div>
  )
}
