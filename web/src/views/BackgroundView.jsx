import { useEffect, useState } from 'react'
import { api } from '../api.js'

export const JOB_ACTIVE = ['queued', 'running']

export function jobWallTime(job) {
  if (!job.started_at) return ''
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const seconds = Math.max(0, Math.round((end - new Date(job.started_at)) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

export function BackgroundView({ projectId }) {
  const [jobs, setJobs] = useState([])
  const [error, setError] = useState(null)

  const load = () =>
    api
      .listJobs(projectId)
      .then(setJobs)
      .catch((e) => setError(e.message || String(e)))

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    if (!jobs.some((j) => JOB_ACTIVE.includes(j.status))) return
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, projectId])

  const stop = (id) => api.stopJob(id).then(load).catch((e) => setError(e.message || String(e)))

  return (
    <div className="center-col">
      <div className="page-head">
        <div className="page-head-title">
          <h2>Background tasks</h2>
          <p className="note">Detached agent runs; the agent is notified when they finish</p>
        </div>
      </div>
      {error && <p className="error-text">{error}</p>}
      {jobs.length === 0 && <p className="empty">No background tasks yet.</p>}
      <div className="cards">
        {jobs.map((j) => (
          <div key={j.id} className="card">
            <h3>
              <span className={`badge ${j.status === 'completed' ? '' : 'err'}`}>{j.status}</span>
              {j.description || j.kind}
            </h3>
            <div className="meta">
              {j.kind} · {j.action} · #{j.id} {jobWallTime(j) && `· ${jobWallTime(j)}`}
            </div>
            {(j.error || j.result) && (
              <div className="meta job-result">{j.error || j.result}</div>
            )}
            {JOB_ACTIVE.includes(j.status) && (
              <div className="row" style={{ marginTop: 8, marginBottom: 0 }}>
                <button className="btn" onClick={() => stop(j.id)}>
                  Stop
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
