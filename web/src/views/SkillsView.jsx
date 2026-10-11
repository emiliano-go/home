import { useState } from 'react'
import { api } from '../api.js'
import { Modal } from '../components/Modal.jsx'
import { SectionEmpty, Skeleton, Spinner } from '../components/primitives.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

export function SkillsView() {
  const { data, loading, error, reload } = useAsync(api.listSkills, [])
  const [formError, setFormError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [installer, setInstaller] = useState(false)
  const [viewing, setViewing] = useState(null)

  const skills = data || []

  const remove = (slug) => {
    api.deleteSkill(slug).then(reload).catch((err) => setFormError(err.message || String(err)))
  }

  const open = (slug) => {
    api
      .getSkill(slug)
      .then(setViewing)
      .catch((err) => setFormError(err.message || String(err)))
  }

  return (
    <div className="center-col wide">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Skills</h2>
          <p className="note">Installable instruction packages for your agents.</p>
        </div>
        <button className="btn primary" onClick={() => setInstaller(true)}>
          <Icon name="plus" size={14} /> New skill
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {formError && <p className="error-text">{formError}</p>}
      {notice && <p className="muted">{notice}</p>}

      {loading ? (
        <div className="home-list">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="row-skeleton" />
          ))}
        </div>
      ) : skills.length === 0 ? (
        <SectionEmpty
          icon="sparkles"
          title="No skills installed"
          hint="Install a SKILL.md package from GitHub, npm, or an archive URL below."
        />
      ) : (
        <div className="home-list">
          {skills.map((s) => (
            <div key={s.slug} className="skill-row">
              <span className="home-row-main">
                <span className="home-row-title">{s.name}</span>
                <span className="home-row-sub">{s.description}</span>
                <span className="home-row-sub skill-source">{s.source}</span>
              </span>
              <button className="btn" onClick={() => open(s.slug)}>
                View
              </button>
              <button className="btn danger" title="Remove" onClick={() => remove(s.slug)}>
                <Icon name="x" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      {installer && (
        <SkillInstaller
          onClose={() => setInstaller(false)}
          onSaved={(installed) => {
            setInstaller(false)
            setNotice(`Installed ${installed.map((s) => s.name).join(', ')}`)
            reload()
          }}
        />
      )}

      {viewing && (
        <Modal title={viewing.name} onClose={() => setViewing(null)}>
          <pre className="skill-body">{viewing.body}</pre>
        </Modal>
      )}
    </div>
  )
}

function SkillInstaller({ onClose, onSaved }) {
  const [source, setSource] = useState('')
  const [subpath, setSubpath] = useState('')
  const [installing, setInstalling] = useState(false)
  const [formError, setFormError] = useState(null)

  const install = (e) => {
    e.preventDefault()
    if (!source.trim() || installing) return
    setInstalling(true)
    setFormError(null)
    api
      .installSkill({ source: source.trim(), subpath: subpath.trim() || undefined })
      .then(onSaved)
      .catch((err) => setFormError(err.message || String(err)))
      .finally(() => setInstalling(false))
  }

  return (
    <Modal title="New skill" onClose={onClose}>
      <form className="agent-form" onSubmit={install}>
        <label className="field">
          <span className="field-label">Source</span>
          <input
            placeholder="owner/repo, npm:package, or https://…tar.gz"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            disabled={installing}
          />
        </label>
        <label className="field">
          <span className="field-label">Subpath (optional)</span>
          <input
            placeholder="skills/pdf"
            value={subpath}
            onChange={(e) => setSubpath(e.target.value)}
            disabled={installing}
          />
        </label>
        <div className="row" style={{ marginBottom: 0 }}>
          <button className="btn primary" disabled={installing || !source.trim()}>
            {installing ? (
              <>
                <Spinner size={13} /> Installing…
              </>
            ) : (
              'Install skill'
            )}
          </button>
          <span className="muted skill-hint">
            GitHub <code>owner/repo</code> · npm <code>npm:pkg</code> · archive URL
          </span>
        </div>
        {formError && <p className="error-text">{formError}</p>}
      </form>
    </Modal>
  )
}
