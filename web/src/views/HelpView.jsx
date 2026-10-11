import { api } from '../api.js'
import { TOOL_GROUPS } from '../agents/AgentsPage.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'

export function Doc(props) {
  return (
    <section className="help-section" id={props.id}>
      <h2>{props.title}</h2>
      {props.children}
    </section>
  )
}

export function HelpView() {
  const { data: actions } = useAsync(api.listActions, [])
  const actionList = actions || []

  return (
    <div className="help">
      <header className="help-hero">
        <div className="help-badge">
          <Icon name="help" size={22} />
        </div>
        <div>
          <h1>Help &amp; documentation</h1>
          <p>Everything Hestia does, and how to get the most out of it.</p>
        </div>
      </header>

      <nav className="help-toc">
        <a href="#overview">Overview</a>
        <a href="#quickstart">Quick start</a>
        <a href="#projects">Projects</a>
        <a href="#insight">Project insight</a>
        <a href="#tasks">Task board</a>
        <a href="#goals">Goals &amp; planning</a>
        <a href="#gitwrites">Git writes</a>
        <a href="#ghauth">GitHub account</a>
        <a href="#providers">Providers</a>
        <a href="#agents">Agents &amp; actions</a>
        <a href="#chat">Chat &amp; tools</a>
        <a href="#browser">Browser</a>
        <a href="#memory">Memory</a>
        <a href="#background">Background tasks</a>
        <a href="#capture">Capture notes</a>
        <a href="#files">Files &amp; gallery</a>
        <a href="#automation">Search, inbox &amp; automations</a>
        <a href="#assistant">Reminders, watches &amp; briefing</a>
        <a href="#auth">Passkeys &amp; access</a>
        <a href="#settings">Settings &amp; theme</a>
        <a href="#tips">Tips &amp; troubleshooting</a>
      </nav>

      <Doc id="overview" title="Overview">
        <p>
          <strong>Hestia</strong> is a self-hosted cockpit for software projects. Each project is a
          persistent, agent-aware workspace linked to a Git repository. An agent reads the repo,
          answers questions, and writes what it learns into <strong>Totem</strong>, a durable
          project memory that every future conversation starts from.
        </p>
        <p>
          The <strong>Dashboard</strong> (the page you land on) shows your most recently opened
          projects, the latest conversations across all projects, and the newest files agents have
          generated.
        </p>
        <p>
          A project's overview shows its branch, last commit (the local clone and the remote tip,
          with how far behind it is), sync state, tasks, token usage, and GitHub activity. Git
          values come from your local clone while GitHub values are fetched live, so they can differ
          until you pull.
        </p>
      </Doc>

      <Doc id="quickstart" title="Quick start">
        <ol className="help-steps">
          <li>
            <strong>Add a project.</strong> Give it a name and a Git URL. Hestia clones it into the
            data volume and reads its <code>AGENTS.md</code>.
          </li>
          <li>
            <strong>Configure a provider.</strong> Open <em>Settings</em> from the sidebar and pick a
            preset or enter a base URL, model, and the environment variable holding your API key.
            Use <em>Test</em> to verify it works.
          </li>
          <li>
            <strong>Set up an agent.</strong> On the <em>Agents</em> page, stay in <em>Simple</em>{' '}
            mode and pick a provider. One agent now handles everything. Advanced users can
            specialise per action.
          </li>
          <li>
            <strong>Chat.</strong> Open a project and describe a task. Watch each tool call run in
            the chat, then review what the agent learned in the <em>Memory</em> tab.
          </li>
        </ol>
      </Doc>

      <Doc id="projects" title="Projects">
        <p>
          A project is a workspace plus one or more Git repositories. Hestia never modifies your
          code unless you explicitly enable <em>Git writes</em> for the project: the agent can
          read files and git history, and write files to a separate workspace, but not change the
          repositories.
        </p>
        <ul>
          <li>
            <strong>Create</strong> a project with the <code>+</code> next to <em>Projects</em> or
            the <em>New project</em> button on the dashboard. The wizard asks for a name, a
            description, one or more Git URLs with short aliases (one is the primary), and
            optional provider, git-writes, and local-browser settings. A project can start with
            no repositories at all.
          </li>
          <li>
            <strong>Repositories</strong> tab: per-repo branch, last commit, sync state, and
            GitHub counts, with pull, add, and remove actions. The agent can also clone a new
            repository with <code>repo_add</code>; removal stays a human action.
          </li>
          <li>
            <strong>Aliases</strong> are how the agent targets a repo: git, file, and GitHub
            tools take an optional <code>repo</code> argument (for example <code>api</code> or
            <code>web</code>); the primary is the default. Totem memory stays with the primary
            repo (or the workspace for repo-less projects).
          </li>
          <li>
            <strong>Open</strong> a project from the sidebar or the dashboard. Opening updates
            its place in <em>Recent projects</em>.
          </li>
          <li>
            <strong>Pull</strong> latest changes and refresh <code>AGENTS.md</code> from the
            <em>About</em> tab or the Repositories page (all repos, or one).
          </li>
          <li>
            <strong>Delete</strong> a project from the <em>About</em> tab. This removes its registry
            entry and all clones.
          </li>
        </ul>
      </Doc>

      <Doc id="insight" title="Project insight">
        <p>
          Opening a project shows an <strong>Overview</strong> status board, and each project has
          dedicated <strong>GitHub</strong> and <strong>Activity</strong> tabs.
        </p>
        <ul>
          <li>
            <strong>Overview</strong>: branch, last commit, ahead/behind sync, open task count, and
            (for GitHub remotes) open PRs, open issues, failing CI runs, and the latest run.
          </li>
          <li>
            <strong>Since your last visit</strong>: a digest of commits, memories, generated files,
            and GitHub changes since you last opened the project. Hestia tracks each project’s last
            opened time, so this resets when you leave and come back.
          </li>
          <li>
            <strong>GitHub</strong>: browse pull requests, issues, and CI runs with filters, open
            them on GitHub, hit <em>Summarize</em> to hand one to the agent, <em>Triage</em> to
            turn it into a plan plus tasks, or <em>Review</em> to run the code-reviewer and write a
            review to the workspace.
          </li>
          <li>
            <strong>Inbox</strong>: new open PRs/issues and failing CI runs appear on the Hestia
            dashboard. PR/issue items can be triaged in place; CI failures open a diagnose chat.
          </li>
          <li>
            <strong>Token budget</strong>: set a monthly budget in About; the Overview shows usage
            and warns past 80%, and scheduled runs pause when the budget is spent (if enforcement
            is on).
          </li>
          <li>
            <strong>Activity</strong>: a chronological timeline of conversations, memory writes,
            generated files, commits, and GitHub events for the project.
          </li>
          <li>
            <strong>Token usage</strong>: the Overview board shows total tokens consumed by the
            agent; the <em>About</em> tab breaks it down by action and conversation. Tokens are
            read from provider responses, so endpoints that omit usage report nothing.
          </li>
        </ul>
      </Doc>

      <Doc id="tasks" title="Task board">
        <p>
          Every project has a <strong>Kanban board</strong> of tasks, kept separate from chat
          sessions, so the board outlives any conversation. Columns are{' '}
          <em>Backlog</em>, <em>To do</em>, <em>In progress</em>, <em>Review</em>, and{' '}
          <em>Done</em>.
        </p>
        <ul>
          <li>
            <strong>Drag and drop</strong> a card between columns to change its status, or drop it
            on another card to reorder.
          </li>
          <li>
            <strong>Click a card</strong> to edit its title, description, column, priority,
            milestone, and due date, or delete it. Cards can <strong>depend on other tasks</strong>{' '}
            (a blocked badge appears until every dependency is done), carry{' '}
            <strong>acceptance criteria</strong> (moving to done asks for review confirmation), and
            hold <strong>comments</strong> that carry context into the next session. A due date
            shows as a chip, red when overdue, soon when within two days.
          </li>
          <li>
            <strong>Implement with agent</strong> in the task editor opens a chat seeded with the
            task's brief, acceptance criteria, dependencies, and comments, and moves the card to
            in-progress.
          </li>
          <li>
            <strong>Run in background</strong> (with git writes on) hands the task to the agent as
            a detached job: it works on a branch, opens a pull request, records the PR link, and
            moves the card to <em>Review</em>. <strong>Run next</strong> on the board does the same
            for the highest-priority unblocked task. Review the PR on GitHub, then mark the task
            done or send it back.
          </li>
          <li>
            <strong>Push to GitHub</strong> creates an issue for a task when git writes are on; the
            card then shows its issue number and re-syncs never duplicate it.
          </li>
          <li>
            <strong>Suggest next work</strong> runs the agent over the board and memory and
            proposes 2 to 5 backlog tasks tagged <em>suggested</em>; keep the useful ones and
            delete the rest.
          </li>
          <li>
            <strong>Milestones</strong> (the <em>Roadmap</em> tab) group tasks into a goal with a
            target date and a progress bar. Link Totem memories to a milestone to tie decisions
            and constraints to the outcome.
          </li>
          <li>
            <strong>The agent manages the board too.</strong> With the <em>Task board</em> tool
            group enabled, the agent can list, create, move, and delete tasks, and create
            milestones. Ask it to “break this into tasks” and they appear on the board.
          </li>
          <li>
            <strong>Triage.</strong> On the <em>GitHub</em> tab, hit <em>Triage</em> on an issue or
            PR. The agent writes a plan to the workspace and creates tasks for it, tracked under a
            parent task.
          </li>
        </ul>
      </Doc>

      <Doc id="goals" title="Goals &amp; planning">
        <p>
          The <strong>Goals</strong> tab turns an intent into an executable board. A goal owns a
          discussion thread, a spec in the workspace, and (once planned) a milestone.
        </p>
        <ul>
          <li>
            <strong>Create a goal</strong> with a title, description, and success criteria.
          </li>
          <li>
            <strong>Discuss</strong> opens a chat in goal mode: the agent interviews you and keeps
            the draft spec updated at <code>goals/&lt;slug&gt;/spec.md</code>.
          </li>
          <li>
            <strong>Generate board</strong> runs the planner: it writes spec + plan, creates the
            milestone, and adds 3–8 tasks with priorities, acceptance criteria, and dependency
            order.
          </li>
          <li>
            <strong>Converge</strong> re-reads the spec and appends tasks the board is still
            missing. It never edits code or existing tasks.
          </li>
          <li>
            Goal cards show status and milestone progress; the spec opens in the file reader and
            the board jumps to the Tasks tab.
          </li>
        </ul>
      </Doc>

      <Doc id="gitwrites" title="Git writes">
        <p>
          By default the agent is strictly read-only: it can inspect the clone and GitHub but
          never change your code. <strong>Git writes</strong> is a per-project, explicit opt-in,
          toggled from the <em>About</em> tab (with a confirmation step). A red{' '}
          <em>writes on</em> badge shows in the project header while it is enabled.
        </p>
        <ul>
          <li>
            When enabled the agent gains <code>write_file</code> (sandboxed to the clone, never{' '}
            <code>.git</code> or <code>.totem</code>), <code>git_create_branch</code>,{' '}
            <code>git_commit</code>, <code>git_push</code>, and <code>gh_open_pr</code>.
          </li>
          <li>
            The system prompt switches to a write policy: prefer a new branch, focused commits,
            never force-push, and report the branch and PR created.
          </li>
          <li>
            Pushing to GitHub needs <code>GITHUB_TOKEN</code> with write scope; without it the
            agent can still branch and commit locally. Subagents and scheduled jobs stay
            read-only. With <em>Require your approval before push or PR</em> enabled (About),
            the agent must call <code>ask_approval</code> and get an approve answer before
            pushing or opening a PR.
          </li>
        </ul>
      </Doc>

      <Doc id="ghauth" title="GitHub account">
        <p>
          Public repositories work without an account. Connecting GitHub enables private
          repositories, higher rate limits, and issue and pull request writes.
        </p>
        <ul>
          <li>
            <strong>Settings, GitHub</strong>: paste a personal access token (repo scope),
            or import the token from the <code>gh</code> CLI (<code>gh auth login</code> first).
          </li>
          <li>
            <code>GITHUB_TOKEN</code> in the environment takes precedence over the stored
            token; disconnect is disabled while it is set.
          </li>
          <li>
            The token is stored at <code>&lt;DATA_DIR&gt;/github_token</code> with 0600
            permissions, and is used for clones, pulls, GitHub reads, PRs, issues, and
            reviews.
          </li>
        </ul>
      </Doc>

      <Doc id="providers" title="Providers">
        <p>
          A provider is any OpenAI-compatible endpoint. Hestia ships presets for popular services and
          supports fully custom ones.
        </p>
        <ul>
          <li>
            <strong>API keys are never stored.</strong> You name an environment variable (for
            example <code>KIMI_API_KEY</code>); Hestia reads the key from the process environment at
            request time.
          </li>
          <li>
            <strong>Base URL</strong> is the OpenAI-compatible root, e.g.{' '}
            <code>https://api.deepseek.com/v1</code>.
          </li>
          <li>
            <strong>Model</strong> is the model id sent to the endpoint, e.g.{' '}
            <code>deepseek-chat</code>.
          </li>
          <li>
            Use <strong>Test</strong> on a provider card to confirm the key and endpoint connect.
          </li>
        </ul>
      </Doc>

      <Doc id="agents" title="Agents &amp; actions">
        <p>
          An <strong>agent</strong> is a model plus a system prompt plus the tools it may use. There
          are two ways to configure them:
        </p>
        <div className="help-cols">
          <div className="help-card">
            <h3>Simple</h3>
            <p>
              One agent for everything. Pick a provider and (optionally) a prompt; it handles chat,
              exploration, review, writing, and memory. This is the recommended default.
            </p>
          </div>
          <div className="help-card">
            <h3>Advanced</h3>
            <p>
              Create multiple agent profiles and assign a default to each <em>action</em>. Give
              exploration a cheap model and code review a stronger one, for example.
            </p>
          </div>
        </div>
        <h3 className="help-sub">Actions</h3>
        <p>An action is a job the app runs an agent for. Anything left on “Default agent” uses the main agent.</p>
        <div className="help-table">
          {actionList.length === 0 && <p className="note">Loading actions…</p>}
          {actionList.map((a) => (
            <div key={a.key} className="help-table-row">
              <div className="help-table-label">{a.label}</div>
              <div className="help-table-desc">{a.description}</div>
            </div>
          ))}
        </div>
        <h3 className="help-sub">Resolution order</h3>
        <p>
          When an action runs, Hestia uses: the agent assigned to that action → the main chat agent →
          a profile whose name matches the action. So a single agent truly covers everything.
        </p>
      </Doc>

      <Doc id="chat" title="Chat &amp; tools">
        <p>
          Every message starts a turn. Hestia builds a system prompt from the project instructions,
          the repository layout, and the most relevant Totem memories, then runs a tool-calling
          loop. Each tool call appears as a live row you can expand:
        </p>
        <ul>
          <li>
            <strong>Running</strong> shows a spinner while the tool executes.
          </li>
          <li>
            <strong>Done</strong> (green check) or <strong>Failed</strong> (red) replaces it with
            the result preview once it finishes. Expand to see arguments and full output.
          </li>
        </ul>
        <h3 className="help-sub">Tool groups</h3>
        <div className="help-table">
          {TOOL_GROUPS.map((g) => (
            <div key={g.key} className="help-table-row">
              <div className="help-table-label">{g.label}</div>
              <div className="help-table-desc">{g.desc}</div>
            </div>
          ))}
        </div>
        <p className="help-note">
          When an agent uses <strong>Delegation</strong>, it hands a subtask to the agent
          configured for an action and continues with the summary. Read mode explores and reports
          (no writes); write mode may also write workspace files, curate memory, and edit files in
          the clone when git writes are on, but never commits or pushes: the main agent reviews
          the diff and does that. Subagents cannot delegate further.
        </p>
        <p>
          The agent can also <strong>ask you a question</strong> with <code>ask_user</code> when a
          decision blocks the work. The turn ends, a notification is pushed (when configured), and
          the question appears as a card in the chat with any suggested choices. It is stored on
          the session, so it survives reloads; your next message answers it and the agent
          continues. <em>Skip</em> dismisses it without an answer.
        </p>
        <p>
          When the work is blocked on something only you can do, the agent uses
          <code>user_required</code> instead: the turn ends with an <strong>Action
          needed</strong> card showing the exact command (for example a <code>sudo</code>
          step or a GPG-signed commit) to copy and run, and continues once you confirm.
        </p>
      </Doc>

      <Doc id="browser" title="Browser &amp; UI debugging">
        <p>
          With the optional <code>browser</code> extra installed (<code>uv sync --extra
          browser</code> plus <code>browser-use install</code>; included in the Docker image), the
          agent gets a real browser.
        </p>
        <ul>
          <li>
            <strong><code>browser_task</code></strong>: autonomous multi-step web work (filling
            forms, extracting data). Returns the result and screenshots.
          </li>
          <li>
            <strong>Debugging tools</strong>: <code>browser_open</code>,{' '}
            <code>browser_screenshot</code>, <code>browser_get_content</code>,{' '}
            <code>browser_click</code>, <code>browser_type</code>, <code>browser_eval</code>, and
            <code>browser_close</code> operate on a persistent session per chat, so cookies and
            page state survive between calls.
          </li>
          <li>
            <strong>Local dev servers</strong>: localhost and private addresses are blocked by
            default. Enable <em>Browser &rarr; Allow the browser to reach localhost</em> in the
            project's About tab, then the agent can debug <code>http://localhost:5173</code> and
            friends.
          </li>
          <li>
            <strong>Your own Chrome</strong>: set a Browser CDP URL in Assistant settings (or
            <code>HESTIA_BROWSER_CDP_URL</code>) to attach to a Chrome started with{' '}
            <code>--remote-debugging-port=9222</code> and reuse your logins. Hestia disconnects
            without closing it.
          </li>
          <li>
            <strong>Image reader</strong>: assign a cheap vision model to the{' '}
            <em>Read images</em> action and screenshots are automatically described in text for
            the main agent, which then never pays vision tokens. The reader can look at the page
            itself (read-only) and sees a compacted version of the conversation.
          </li>
        </ul>
        <p>
          Browsing is principal-only and can be disabled globally in Assistant settings or with
          <code>HESTIA_BROWSER=0</code>.
        </p>
      </Doc>

      <Doc id="memory" title="Memory">
        <p>
          Totem is durable project memory: decisions, gotchas, architecture facts, and open
          questions. It is not a chat log. After each turn the agent records what mattered, and a
          new session bootstraps from ranked memory instead of the old transcript.
        </p>
        <ul>
          <li>
            <strong>Browse &amp; search</strong> memory in the <em>Memory</em> tab.
          </li>
          <li>
            <strong>Repair</strong> memory by describing the fix in plain language and pressing{' '}
            <em>Fix with agent</em>. A memory-only agent applies the changes and reports back.
          </li>
          <li>
            <strong>Preferences and client facts</strong>: memories tagged{' '}
            <code>preference</code> or <code>client:&lt;name&gt;</code> are always injected into
            the agent's context, not just retrieved by relevance. Tag them when writing memory.
          </li>
          <li>
            <strong>About you</strong>: tell the agent "call me Sam" or "remember: reply in short
            bullets" and it saves a global name and standing preferences that are injected into
            every future prompt. Manage them under Settings, Assistant. A{' '}
            <em>Remember this</em> button under each reply saves it as a preference.
          </li>
        </ul>
      </Doc>

      <Doc id="background" title="Background tasks">
        <p>
          Long work runs detached. When the agent calls <code>start_background_task</code> (or
          delegates a subagent with <code>run_in_background</code>), it gets a task id back
          immediately and keeps working or stops, and a notification arrives when the task
          finishes. The <em>Background</em> project tab lists every run with status, wall time,
          output, and a <em>Stop</em> button.
        </p>
        <ul>
          <li>
            On completion Hestia appends a notification to the originating chat and, if that chat is
            idle, runs a continuation turn that reacts to the result.
          </li>
          <li>
            Up to three tasks run at once; the rest queue. Statuses are{' '}
            <code>completed</code>, <code>failed</code>, <code>timed_out</code>,{' '}
            <code>stopped</code>, and <code>lost</code> (interrupted by a restart).
          </li>
        </ul>
      </Doc>

      <Doc id="capture" title="Capture notes">
        <p>
          Paste raw notes, an email, or a thread into the <em>Capture</em> project tab. The agent
          turns them into structure on your board: concrete items become tasks (with due dates
          when a deadline is stated), time-based nudges become reminders, client and people facts
          become memory tagged <code>client:&lt;name&gt;</code>, decisions become memories, and an
          implied ongoing signal can become a watch. It reports exactly what it created.
        </p>
      </Doc>

      <Doc id="files" title="Files &amp; gallery">
        <p>
          Agents write plans, specs, and research notes to a per-project <strong>workspace</strong>,
          kept outside the repository so your code stays clean.
        </p>
        <ul>
          <li>
            <strong>Files</strong> tab: the workspace files for the current project. Click one to
            read it (markdown is rendered).
          </li>
          <li>
            <strong>Gallery</strong>: generated files across every project, with a filter.
          </li>
          <li>
            The dashboard lists the newest generated files across all projects.
          </li>
        </ul>
      </Doc>

      <Doc id="automation" title="Search, inbox &amp; automations">
        <ul>
          <li>
            <strong>Search</strong> (Global section): search Totem memory, workspace file names and
            contents, and conversation titles across every project. Results jump straight to the
            memory browser, the file reader, or the conversation.
          </li>
          <li>
            <strong>Inbox</strong> (dashboard): new open pull requests and issues and failing
            CI runs appear here as they are discovered. The first poll of a project is a silent
            baseline; after that, new items arrive unread. <em>Check now</em> polls immediately,
            <em>Mark all read</em> clears the badge.
          </li>
          <li>
            <strong>Notifications</strong>: configure ntfy (<code>NTFY_TOPIC</code>, optional{' '}
            <code>NTFY_URL</code>/<code>NTFY_TOKEN</code>) or Telegram (
            <code>TELEGRAM_BOT_TOKEN</code> + <code>TELEGRAM_CHAT_ID</code>). The agent can push
            with the <code>notify</code> tool, new inbox items and scheduled run results push
            automatically, and a budget skip alerts you. Test from the <em>About</em> tab.
          </li>
          <li>
            <strong>Generated docs</strong> (Overview tab): one click writes an{' '}
            <code>ARCHITECTURE.md</code>, <code>ONBOARDING.md</code>, or an ADR from the project’s
            Totem memory and repository into the workspace.
          </li>
          <li>
            <strong>Automations</strong> (project tab): recurring agent runs. Pick an action
            (GitHub scan, code review, memory curation, docs, …), an interval, and an instruction;
            the background worker runs it and records the last report. Presets cover the nightly
            repo digest, daily PR review, and weekly memory curation. <em>Run now</em> executes one
            immediately. <code>{'{date}'}</code> in the instruction expands to the run date.
          </li>
          <li>
            <strong>Event triggers</strong>: set an automation's trigger to "When an event happens"
            and the agent reacts as things occur instead of on a schedule. Events are CI failures,
            pull requests and issues opened, watch matches, and tasks entering review or done. The
            instruction can use <code>{'{event}'}</code>, <code>{'{event_title}'}</code>, and{' '}
            <code>{'{event_url}'}</code>, with an optional filter substring. The agent can create
            these too via <code>schedule_create</code>.
          </li>
        </ul>
      </Doc>

      <Doc id="assistant" title="Reminders, watches &amp; briefing">
        <ul>
          <li>
            <strong>Reminders</strong> (Global section): one-shot, daily, or weekly nudges
            that fire a push notification. Add them in the view, or ask the agent
            ("remind me tomorrow at 9"). Snooze 10 minutes or 1 day, mark done, delete.
            Overdue items show in red and on the dashboard.
          </li>
          <li>
            <strong>Watches</strong> (Global section): monitor without noise. A
            <em>page</em> watch notifies when the page text changes, or when a phrase
            appears (then it completes). A <em>feed</em> watch notifies only on new
            RSS/Atom items. A <em>condition</em> watch runs a small agent check each
            interval and notifies when the condition is met. Pause, run now, and read
            the last result from the view; the agent can manage them with
            <code>watch_add</code>.
          </li>
          <li>
            <strong>Daily briefing</strong>: enable it under Settings, Assistant and pick
            a local time. Hestia sends one deterministic digest (due reminders, ready
            tasks, unread inbox); optionally the agent adds commentary and writes
            <code>briefings/&lt;date&gt;.md</code>.
          </li>
          <li>
            <strong>Daily plan and weekly review</strong>: enable each under Settings,
            Assistant with a local time (and a weekday for the review). The daily plan
            ranks ready work by priority and due date; the weekly review reports what
            moved, what is blocked or stale, and velocity. With a provider the agent
            writes <code>plans/&lt;date&gt;.md</code> or <code>reviews/&lt;date&gt;.md</code>{' '}
            to the workspace.
          </li>
          <li>
            <strong>Standing preferences</strong> (Settings, Assistant): your name,
            timezone, instructions, and a list of always-on preferences are injected
            into every system prompt and are applied without being asked. The clock in
            that context is what lets the agent resolve "tomorrow at 9".
          </li>
        </ul>
      </Doc>

      <Doc id="auth" title="Passkeys &amp; access">
        <p>
          Authentication is opt-in. With no <code>HESTIA_SETUP_TOKEN</code> set, Hestia behaves as
          before: anyone who can reach the port can use it. Set the variable to gate every API
          call behind a WebAuthn passkey.
        </p>
        <ul>
          <li>
            <strong>First passkey</strong>: open Hestia, enter the setup token on the login screen,
            and register a passkey (Touch ID, Windows Hello, security key, or a phone).
          </li>
          <li>
            <strong>Recovery</strong>: if you lose the device, register another passkey from the
            same screen with the setup token. Keep that token somewhere safe.
          </li>
          <li>
            <strong>Behind a proxy</strong>: set <code>HESTIA_RP_ID</code> to the domain (e.g.{' '}
            <code>home.example.com</code>) and <code>HESTIA_ORIGIN</code> to the full origin (e.g.{' '}
            <code>https://home.example.com</code>); set <code>HESTIA_COOKIE_SECURE=1</code> if TLS
            terminates upstream.
          </li>
          <li>
            <strong>Log out</strong> from the sidebar. Sessions last 30 days.
          </li>
        </ul>
      </Doc>

      <Doc id="settings" title="Settings &amp; theme">
        <p>
          Open <em>Settings</em> from the sidebar.
        </p>
        <ul>
          <li>
            <strong>Providers</strong>: add, test, and delete model endpoints.
          </li>
          <li>
            <strong>Assistant</strong>: name, timezone, standing instructions, daily
            briefing, and the web fetch toggle.
          </li>
          <li>
            <strong>Theme</strong>: pick a preset (Hestia Light, Hestia Dark, Atom One).
            A preset also switches the appearance to its light or dark mode;{' '}
            <em>Reset all</em> restores the defaults.
          </li>
        </ul>
      </Doc>

      <Doc id="tips" title="Tips &amp; troubleshooting">
        <ul>
          <li>
            <strong>“No provider configured”</strong>: add one in Settings and make sure the named
            environment variable is set where Hestia runs.
          </li>
          <li>
            <strong>Test fails</strong>: check the base URL (include the <code>/v1</code>) and that
            the model id is valid for that endpoint.
          </li>
          <li>
            <strong>Agent ignores your request</strong>: project code is read-only by default.
            Ask it to explain a change instead, have it write a plan to the workspace, or enable
            <em>Git writes</em> in About to let it branch and commit.
          </li>
          <li>
            <strong>Pick a role model</strong>: advanced mode lets a cheap model explore and a
            stronger one reason, which saves cost on large repositories.
          </li>
        </ul>
      </Doc>
    </div>
  )
}
