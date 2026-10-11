import { useCallback, useEffect, useRef, useState } from 'react'
import { version as APP_VERSION } from '../package.json'
import { api } from './api.js'
import { AgentsPage } from './agents/AgentsPage.jsx'
import { Modal } from './components/Modal.jsx'
import { Spinner } from './components/primitives.jsx'
import { Icon } from './icons.jsx'
import { relDate } from './lib/format.js'
import { useAsync } from './lib/hooks.js'
import { parseHash, viewHash } from './lib/routing.js'
import { SettingsView } from './SettingsView.jsx'
import { applyThemeState, loadThemeState, saveThemeState } from './theme.js'
import { AboutView } from './views/AboutView.jsx'
import { ActivityView } from './views/ActivityView.jsx'
import { AutomationsView } from './views/AutomationsView.jsx'
import { BackgroundView } from './views/BackgroundView.jsx'
import { CaptureView } from './views/CaptureView.jsx'
import { ChatView } from './views/ChatView.jsx'
import { FileReaderPane, FilesView, GalleryView } from './views/FilesView.jsx'
import { GithubView } from './views/GithubView.jsx'
import { GoalsView } from './views/GoalsView.jsx'
import { HelpView } from './views/HelpView.jsx'
import { NewProjectView } from './views/NewProjectView.jsx'
import { ReposView } from './views/ReposView.jsx'
import { RunsView } from './views/RunsView.jsx'
import { HomeView, LoginView } from './views/HomeView.jsx'
import { MemoryView } from './views/MemoryView.jsx'
import { ProjectOverviewView } from './views/ProjectOverviewView.jsx'
import { RemindersView } from './views/RemindersView.jsx'
import { RoadmapView } from './views/RoadmapView.jsx'
import { SearchView } from './views/SearchView.jsx'
import { SkillsView } from './views/SkillsView.jsx'
import { TasksView } from './views/TasksView.jsx'
import { WatchesView } from './views/WatchesView.jsx'

export default function App() {
  const projectsReq = useAsync(api.listProjects, [])
  const providersReq = useAsync(api.listProviders, [])
  const agentsReq = useAsync(api.listAgents, [])
  const actionsReq = useAsync(api.listActions, [])

  const projects = projectsReq.data || []
  const [projectId, setProjectId] = useState(null)
  // home | help | welcome(overview) | chat | tasks | github | activity | files | memory | about | agents | gallery
  const [view, setView] = useState({ type: 'home' })
  const [activeRuns, setActiveRuns] = useState(0)
  const [chatSessionId, setChatSessionId] = useState(null)
  const [initialMessage, setInitialMessage] = useState(null)
  const [chatKey, setChatKey] = useState(0)
  const [agentId, setAgentId] = useState('')
  const [providerId, setProviderId] = useState('')
  const [settingsTab, setSettingsTab] = useState('providers')
  const [landingFile, setLandingFile] = useState(null)
  const [prevOpenedAt, setPrevOpenedAt] = useState(undefined)
  const [authState, setAuthState] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // Which project's dropdown is currently expanded. Only one open at a time.
  const [expandedId, setExpandedId] = useState(null)
  // Cache sessions per project so collapsed projects don't refetch on expand.
  const [sessionsByProject, setSessionsByProject] = useState({})

  useEffect(() => {
    api
      .authStatus()
      .then(setAuthState)
      .catch(() => setAuthState({ enabled: false, authenticated: true, has_passkeys: false }))
  }, [])

  const [theme, setTheme] = useState(loadThemeState)

  useEffect(() => {
    applyThemeState(theme)
    saveThemeState(theme)
  }, [theme])

  useEffect(() => {
    if (theme.mode !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = () => applyThemeState(theme)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [theme])

  useEffect(() => {
    const applyHash = () => {
      const parsed = parseHash(window.location.hash)
      if (!parsed) return
      if (parsed.projectId) {
        setProjectId(parsed.projectId)
        api
          .openProject(parsed.projectId)
          .then((p) => setPrevOpenedAt(p.previous_opened_at || null))
          .catch(() => setPrevOpenedAt(null))
      }
      if (parsed.view) {
        setView(parsed.view)
        if (parsed.view.type === 'chat' && !parsed.session) {
          setChatSessionId(null)
        }
      }
      if (parsed.session) setChatSessionId(parsed.session)
    }
    applyHash()
    window.addEventListener('hashchange', applyHash)
    return () => window.removeEventListener('hashchange', applyHash)
  }, [])

  const effectiveProjectId = projectId && projects.some((p) => p.id === projectId)
    ? projectId
    : projects[0]?.id || null

  useEffect(() => {
    if (effectiveProjectId && effectiveProjectId !== projectId) {
      setProjectId(effectiveProjectId)
    }
  }, [effectiveProjectId, projectId])

  useEffect(() => {
    const hash = viewHash(effectiveProjectId, view, chatSessionId)
    if (window.location.hash !== hash) {
      window.history.replaceState(null, '', hash)
    }
  }, [view, effectiveProjectId, chatSessionId])

  const sessionsReq = useAsync(
    () => (effectiveProjectId ? api.listSessions(effectiveProjectId) : Promise.resolve([])),
    [effectiveProjectId]
  )
  const sessions = sessionsReq.data || []

  // Keep the sessions cache in sync for the active project.
  useEffect(() => {
    if (effectiveProjectId && sessionsReq.data) {
      setSessionsByProject((prev) =>
        prev[effectiveProjectId] === sessionsReq.data
          ? prev
          : { ...prev, [effectiveProjectId]: sessionsReq.data }
      )
    }
  }, [effectiveProjectId, sessionsReq.data])

  // Auto-expand the active project. Only one dropdown open at a time.
  const userCollapsedRef = useRef(null)
  useEffect(() => {
    if (effectiveProjectId && userCollapsedRef.current !== effectiveProjectId) {
      setExpandedId(effectiveProjectId)
    }
  }, [effectiveProjectId])

  // Lazily load sessions for an expanded (non-active) project.
  useEffect(() => {
    if (!expandedId || expandedId === effectiveProjectId) return
    if (sessionsByProject[expandedId]) return
    let cancelled = false
    api
      .listSessions(expandedId)
      .then((data) => {
        if (!cancelled) setSessionsByProject((prev) => ({ ...prev, [expandedId]: data }))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [expandedId, effectiveProjectId, sessionsByProject])

  const selectProject = (id) => {
    setProjectId(id)
    setExpandedId(id)
    userCollapsedRef.current = null
    setView({ type: 'welcome' })
    setChatSessionId(null)
    setInitialMessage(null)
    setPrevOpenedAt(undefined)
    api
      .openProject(id)
      .then((p) => setPrevOpenedAt(p.previous_opened_at || null))
      .catch(() => setPrevOpenedAt(null))
  }

  const toggleProject = (id) => {
    if (expandedId === id) {
      // Collapse this dropdown; remember so auto-expand doesn't reopen it
      // until the user navigates to a different project.
      userCollapsedRef.current = id
      setExpandedId(null)
      return
    }
    selectProject(id)
  }

  const openChat = (sessionId) => {
    const session = sessions.find((s) => s.id === sessionId)
    setView({
      type: 'chat',
      action: session?.action && session.action !== 'chat' ? session.action : undefined,
    })
    setChatSessionId(sessionId)
    setInitialMessage(null)
  }

  const openSessionFromLanding = (pid, sessionId) => {
    setProjectId(pid)
    api.openProject(pid).catch(() => {})
    setView({ type: 'chat' })
    setChatSessionId(sessionId)
    setInitialMessage(null)
  }

  const openProjectView = (pid, type) => {
    setProjectId(pid)
    api.openProject(pid).catch(() => {})
    setView({ type })
    setChatSessionId(null)
    setInitialMessage(null)
  }

  const openNewProject = () => {
    setView({ type: 'new-project' })
  }

  useEffect(() => {
    let alive = true
    const tick = () =>
      api
        .listRuns(true)
        .then((rows) => alive && setActiveRuns(rows.length))
        .catch(() => {})
    tick()
    const timer = setInterval(tick, 6000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  // Project-aware navigation used by the per-project dropdowns.
  const startNewChatFor = (pid) => {
    if (pid !== effectiveProjectId) {
      setProjectId(pid)
      api.openProject(pid).catch(() => {})
    }
    setExpandedId(pid)
    userCollapsedRef.current = null
    setView({ type: 'chat' })
    setChatSessionId(null)
    setInitialMessage(null)
    setChatKey((k) => k + 1)
  }

  const openChatFor = (pid, sessionId, action) => {
    if (pid !== effectiveProjectId) {
      setProjectId(pid)
      api.openProject(pid).catch(() => {})
    }
    setExpandedId(pid)
    userCollapsedRef.current = null
    setView({ type: 'chat', action })
    setChatSessionId(sessionId)
    setInitialMessage(null)
  }

  const openProjectViewFor = (pid, type) => {
    if (pid !== effectiveProjectId) {
      setProjectId(pid)
      api.openProject(pid).catch(() => {})
    }
    setExpandedId(pid)
    userCollapsedRef.current = null
    setView({ type })
    setChatSessionId(null)
    setInitialMessage(null)
  }

  const startChatWith = (text) => {
    setView({ type: 'chat' })
    setChatSessionId(null)
    setInitialMessage(text)
    setChatKey((k) => k + 1)
  }

  const openGoalDiscussion = (sessionId, seed) => {
    setView({ type: 'chat', action: 'goal' })
    setChatSessionId(sessionId)
    setInitialMessage(seed)
    setChatKey((k) => k + 1)
  }

  const startProjectChat = (pid, text) => {
    setProjectId(pid)
    api.openProject(pid).catch(() => {})
    setView({ type: 'chat' })
    setChatSessionId(null)
    setInitialMessage(text)
    setChatKey((k) => k + 1)
  }

  const onSessionCreated = useCallback(
    (sid) => {
      setChatSessionId(sid)
      setInitialMessage(null)
      sessionsReq.reload()
    },
    [sessionsReq]
  )

  const agents = agentsReq.data || []
  const providers = providersReq.data || []
  const project = projects.find((p) => p.id === effectiveProjectId)
  const actions = actionsReq.data || []
  const chatDefaultAgentId = actions.find((a) => a.key === 'chat')?.agent_id
  const chatDefaultAgent = agents.find((a) => a.id === chatDefaultAgentId) || null
  const agentLabel = (a) => {
    const model = a.model || providers.find((p) => p.id === a.provider_id)?.model || ''
    return `${a.name}${model ? ` · ${model}` : ''}${a.reasoning_effort ? ` (${a.reasoning_effort})` : ''}`
  }
  const projectDefaultProvider = providers.find((p) => p.id === project?.default_provider_id)
  const inProjectView = [
    'welcome',
    'chat',
    'goals',
    'tasks',
    'roadmap',
    'github',
    'activity',
    'automations',
    'files',
    'memory',
    'about',
  ].includes(view.type)

  if (authState === null) {
    return (
      <div className="login">
        <Spinner size={20} />
      </div>
    )
  }
  if (authState.enabled && !authState.authenticated) {
    return <LoginView status={authState} onAuthed={() => window.location.reload()} />
  }

  return (
    <div className="app">
      <aside
        className={`sidebar ${sidebarOpen ? 'open' : ''}`}
        onClick={() => setSidebarOpen(false)}
      >
        <button className="sidebar-brand" onClick={() => setView({ type: 'home' })}>
          <span className="logo">
            <Icon name="flame" size={15} />
          </span>
          <span className="brand-name">Hestia</span>
          <span className="brand-version">v{APP_VERSION}</span>
        </button>
        <div className="sidebar-scroll">
          <button
            className={`sidebar-item ${view.type === 'home' ? 'active' : ''}`}
            onClick={() => setView({ type: 'home' })}
          >
            <Icon name="home" size={16} className="si-icon" />
            Dashboard
          </button>
          <div className="sidebar-label">
            <span>Projects</span>
            <button title="Add project" onClick={openNewProject}>
              <Icon name="plus" size={14} />
            </button>
          </div>
          {projects.map((p) => {
            const isExpanded = expandedId === p.id
            const isActiveProject = p.id === effectiveProjectId
            const projectSessions = [...(sessionsByProject[p.id] || (isActiveProject ? sessions : []))]
              .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))
            const navActive = (type) => isActiveProject && view.type === type
            return (
              <div key={p.id} className="sidebar-group">
                <button
                  className={`sidebar-item sidebar-project ${
                    inProjectView && isActiveProject ? 'active' : ''
                  }`}
                  onClick={() => toggleProject(p.id)}
                >
                  <span className="proj-avatar">{p.name.slice(0, 1)}</span>
                  <span
                    style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}
                  >
                    {p.name}
                  </span>
                  <Icon
                    name={isExpanded ? 'chevronDown' : 'chevronRight'}
                    size={14}
                    className="si-icon chevron"
                  />
                </button>
                {isExpanded && (
                  <div className="sidebar-sub">
                    <button
                      className={`sidebar-item ${navActive('welcome') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'welcome')}
                    >
                      <Icon name="home" size={16} className="si-icon" />
                      Overview
                    </button>
                    <button
                      className={`sidebar-item ${
                        isActiveProject && view.type === 'chat' && chatSessionId === null
                          ? 'active'
                          : ''
                      }`}
                      onClick={() => startNewChatFor(p.id)}
                    >
                      <Icon name="plus" size={16} className="si-icon" />
                      New chat
                    </button>
                    {projectSessions.map((s) => (
                      <button
                        key={s.id}
                        className={`sidebar-item ${
                          isActiveProject && view.type === 'chat' && chatSessionId === s.id
                            ? 'active'
                            : ''
                        }`}
                        onClick={() =>
                          openChatFor(
                            p.id,
                            s.id,
                            s.action && s.action !== 'chat' ? s.action : undefined
                          )
                        }
                      >
                        <Icon name="chat" size={16} className="si-icon" />
                        <span
                          style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            flex: 1,
                            textAlign: 'left',
                          }}
                        >
                          {s.title || 'Untitled'}
                        </span>
                        <span className="sub">{relDate(s.created_at)}</span>
                      </button>
                    ))}
                    <button
                      className={`sidebar-item ${navActive('goals') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'goals')}
                    >
                      <Icon name="sparkles" size={16} className="si-icon" />
                      Goals
                    </button>
                    <button
                      className={`sidebar-item ${navActive('tasks') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'tasks')}
                    >
                      <Icon name="tasks" size={16} className="si-icon" />
                      Tasks
                    </button>
                    <button
                      className={`sidebar-item ${navActive('roadmap') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'roadmap')}
                    >
                      <Icon name="flag" size={16} className="si-icon" />
                      Roadmap
                    </button>
                    <button
                      className={`sidebar-item ${navActive('github') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'github')}
                    >
                      <Icon name="git" size={16} className="si-icon" />
                      GitHub
                    </button>
                    <button
                      className={`sidebar-item ${navActive('activity') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'activity')}
                    >
                      <Icon name="clock" size={16} className="si-icon" />
                      Activity
                    </button>
                    <button
                      className={`sidebar-item ${navActive('automations') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'automations')}
                    >
                      <Icon name="refresh" size={16} className="si-icon" />
                      Automations
                    </button>
                    <button
                      className={`sidebar-item ${navActive('files') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'files')}
                    >
                      <Icon name="files" size={16} className="si-icon" />
                      Files
                    </button>
                    <button
                      className={`sidebar-item ${navActive('memory') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'memory')}
                    >
                      <Icon name="memory" size={16} className="si-icon" />
                      Memory
                    </button>
                    <button
                      className={`sidebar-item ${navActive('background') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'background')}
                    >
                      <Icon name="play" size={16} className="si-icon" />
                      Background
                    </button>
                    <button
                      className={`sidebar-item ${navActive('capture') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'capture')}
                    >
                      <Icon name="plus" size={16} className="si-icon" />
                      Capture
                    </button>
                    <button
                      className={`sidebar-item ${navActive('about') ? 'active' : ''}`}
                      onClick={() => openProjectViewFor(p.id, 'about')}
                    >
                      <Icon name="info" size={16} className="si-icon" />
                      About
                    </button>
                  </div>
                )}
              </div>
            )
          })}
          {projectsReq.loading && <div className="meta">Loading...</div>}
          {!projectsReq.loading && projects.length === 0 && (
            <div className="meta">No projects yet, click + to add one.</div>
          )}

          <div className="sidebar-section">
            <div className="sidebar-label">
              <span>Global</span>
            </div>
            <button
              className={`sidebar-item ${view.type === 'search' ? 'active' : ''}`}
              onClick={() => setView({ type: 'search' })}
            >
              <Icon name="search" size={16} className="si-icon" />
              Search
            </button>
            <button
              className={`sidebar-item ${view.type === 'reminders' ? 'active' : ''}`}
              onClick={() => setView({ type: 'reminders' })}
            >
              <Icon name="clock" size={16} className="si-icon" />
              Reminders
            </button>
            <button
              className={`sidebar-item ${view.type === 'watches' ? 'active' : ''}`}
              onClick={() => setView({ type: 'watches' })}
            >
              <Icon name="refresh" size={16} className="si-icon" />
              Watches
            </button>
            <button
              className={`sidebar-item ${view.type === 'agents' ? 'active' : ''}`}
              onClick={() => setView({ type: 'agents' })}
            >
              <Icon name="agents" size={16} className="si-icon" />
              Agents
            </button>
            <button
              className={`sidebar-item ${view.type === 'runs' ? 'active' : ''}`}
              onClick={() => setView({ type: 'runs' })}
            >
              <Icon name="play" size={16} className="si-icon" />
              Runs
              {activeRuns > 0 && <span className="sub">{activeRuns}</span>}
            </button>
            <button
              className={`sidebar-item ${view.type === 'skills' ? 'active' : ''}`}
              onClick={() => setView({ type: 'skills' })}
            >
              <Icon name="sparkles" size={16} className="si-icon" />
              Skills
            </button>
            <button
              className={`sidebar-item ${view.type === 'gallery' ? 'active' : ''}`}
              onClick={() => setView({ type: 'gallery' })}
            >
              <Icon name="gallery" size={16} className="si-icon" />
              Gallery
            </button>
            <button
              className={`sidebar-item ${view.type === 'help' ? 'active' : ''}`}
              onClick={() => setView({ type: 'help' })}
            >
              <Icon name="help" size={16} className="si-icon" />
              Help
            </button>
            <button
              className={`sidebar-item ${view.type === 'settings' ? 'active' : ''}`}
              onClick={() => setView({ type: 'settings' })}
            >
              <Icon name="settings" size={16} className="si-icon" />
              Settings
            </button>
          </div>

          {authState?.enabled && (
            <div className="sidebar-section">
              <button
                className="sidebar-item"
                onClick={() => api.authLogout().then(() => window.location.reload())}
              >
                <Icon name="x" size={16} className="si-icon" />
                Log out
              </button>
            </div>
          )}
        </div>
      </aside>

      <button
        className="mobile-nav-btn"
        title="Menu"
        onClick={() => setSidebarOpen((open) => !open)}
      >
        <Icon name="menu" size={18} />
      </button>
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      )}

      <div className="main">
        {project &&
          [
            'welcome',
            'chat',
            'goals',
            'tasks',
            'roadmap',
            'github',
            'activity',
            'automations',
            'files',
            'memory',
            'about',
          ].includes(view.type) && (
          <header className="topbar">
            <div className="topbar-title" title={project.repo_url}>
              <span className="proj-avatar">{project.name.slice(0, 1)}</span>
              <span className="name">{project.name}</span>
              {project.allow_git_writes && (
                <span className="badge err" title="Agent may modify the clone">
                  writes on
                </span>
              )}
            </div>
            <div className="topbar-right">
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">
                  {chatDefaultAgent
                    ? `${agentLabel(chatDefaultAgent)} · chat default`
                    : 'Default agent'}
                </option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {agentLabel(a)}
                  </option>
                ))}
              </select>
              {!agentId && !chatDefaultAgent && (
                <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                  <option value="">
                    {projectDefaultProvider
                      ? `Project default (${projectDefaultProvider.name})`
                      : 'Default provider'}
                  </option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.model})
                    </option>
                  ))}
                </select>
              )}
              <button
                className="icon-btn"
                title="Settings"
                onClick={() => setView({ type: 'settings' })}
              >
                <Icon name="settings" size={17} />
              </button>
            </div>
          </header>
        )}

        <div className="content">
          {view.type === 'home' && (
            <HomeView
              onNewProject={openNewProject}
              onNavigate={setView}
              onOpenProject={(id) => selectProject(id)}
              onOpenSession={openSessionFromLanding}
              onOpenFile={(f) => setLandingFile(f)}
              onStartChat={startProjectChat}
            />
          )}
          {view.type === 'help' && <HelpView />}
          {view.type === 'runs' && (
            <RunsView projects={projects} onOpenSession={openSessionFromLanding} />
          )}
          {view.type === 'new-project' && (
            <NewProjectView
              onCancel={() => setView({ type: 'home' })}
              onCreated={(p) => {
                projectsReq.reload()
                selectProject(p.id)
              }}
            />
          )}
          {view.type === 'search' && (
            <SearchView
              onOpenMemory={(pid) => openProjectView(pid, 'memory')}
              onOpenSession={openSessionFromLanding}
              onOpenFile={(f) => setLandingFile(f)}
            />
          )}
          {view.type === 'reminders' && <RemindersView projects={projects} />}
          {view.type === 'watches' && <WatchesView projects={projects} />}
          {!project &&
            !projectsReq.loading &&
            !['home', 'help', 'settings', 'skills'].includes(view.type) && (
              <div className="empty">
                No projects yet. Click + next to Projects to add one.
              </div>
            )}
          {project && view.type === 'welcome' && (
            <ProjectOverviewView
              project={project}
              since={prevOpenedAt}
              onStart={startChatWith}
              onNavigate={setView}
              onOpenSession={(sid) => openSessionFromLanding(project.id, sid)}
              onOpenSettings={(tab) => {
                setSettingsTab(tab || 'providers')
                setView({ type: 'settings' })
              }}
            />
          )}
          {project && view.type === 'chat' && (
            <ChatView
              key={`${project.id}:${chatKey}`}
              projectId={project.id}
              sessionId={chatSessionId}
              agentId={agentId}
              providerId={providerId}
              onSessionCreated={onSessionCreated}
              initialMessage={initialMessage}
              action={view.action}
            />
          )}
          {project && view.type === 'goals' && (
            <GoalsView
              projectId={project.id}
              onDiscuss={openGoalDiscussion}
              onOpenTasks={() => setView({ type: 'tasks' })}
              onOpenFile={(f) => setLandingFile(f)}
            />
          )}
          {project && view.type === 'tasks' && (
            <TasksView
              projectId={project.id}
              onImplement={startChatWith}
              gitWrites={project.allow_git_writes}
            />
          )}
          {project && view.type === 'roadmap' && (
            <RoadmapView
              projectId={project.id}
              onOpenTasks={() => setView({ type: 'tasks' })}
            />
          )}
          {project && view.type === 'github' && (
            <GithubView
              projectId={project.id}
              onSummarize={startChatWith}
              onOpenTasks={() => setView({ type: 'tasks' })}
            />
          )}
          {project && view.type === 'activity' && (
            <ActivityView
              projectId={project.id}
              onOpenSession={(sid) => openChat(sid)}
              onOpenFile={(item) =>
                setLandingFile({ project_id: project.id, path: item.path })
              }
            />
          )}
          {project && view.type === 'automations' && (
            <AutomationsView projectId={project.id} />
          )}
          {project && view.type === 'files' && <FilesView projectId={project.id} />}
          {project && view.type === 'repos' && <ReposView projectId={project.id} />}
          {project && view.type === 'memory' && (
            <MemoryView projectId={project.id} providerId={providerId} onStart={startChatWith} />
          )}
          {project && view.type === 'background' && (
            <BackgroundView projectId={project.id} />
          )}
          {project && view.type === 'capture' && <CaptureView projectId={project.id} />}
          {project && view.type === 'about' && (
            <AboutView
              projectId={project.id}
              onDeleted={() => {
                projectsReq.reload()
                setProjectId(null)
                setView({ type: 'home' })
              }}
            />
          )}
          {view.type === 'agents' && (
            <AgentsPage onOpenSettings={() => setView({ type: 'settings' })} />
          )}
          {view.type === 'skills' && <SkillsView />}
          {view.type === 'gallery' && <GalleryView />}
          {view.type === 'settings' && (
            <SettingsView
              tab={settingsTab}
              setTab={setSettingsTab}
              theme={theme}
              setTheme={setTheme}
            />
          )}
        </div>
      </div>

      {landingFile && (
        <Modal
          title={landingFile.path}
          onClose={() => setLandingFile(null)}
        >
          <FileReaderPane
            projectId={landingFile.project_id}
            path={landingFile.path}
            onClose={() => setLandingFile(null)}
          />
        </Modal>
      )}

    </div>
  )
}
