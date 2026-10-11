import { AssistantPanel } from './panels/AssistantPanel.jsx'
import { DecisionPanel } from './panels/DecisionPanel.jsx'
import { GithubPanel } from './panels/GithubPanel.jsx'
import { ProvidersPanel } from './panels/ProvidersPanel.jsx'
import { ThemePanel } from './panels/ThemePanel.jsx'

export const SETTINGS_TABS = [
  ['providers', 'Providers'],
  ['assistant', 'Assistant'],
  ['decision', 'Decision'],
  ['github', 'GitHub'],
  ['theme', 'Theme'],
]

export function SettingsView({ tab, setTab, theme, setTheme }) {
  return (
    <div className="center-col">
      <div className="page-head">
        <h2>Settings</h2>
        <div className="segmented">
          {SETTINGS_TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'providers' && <ProvidersPanel />}
      {tab === 'assistant' && <AssistantPanel />}
      {tab === 'decision' && <DecisionPanel />}
      {tab === 'github' && <GithubPanel />}
      {tab === 'theme' && <ThemePanel theme={theme} setTheme={setTheme} />}
    </div>
  )
}
