<p align="center">
  <strong style="font-size: 2.5em;">hestia</strong>
</p>

<p align="center">
  <strong>Self-hostable agentic project cockpit. FastAPI, React, Totem memory.</strong>
</p>

<p align="center">
  A central place to monitor software projects as persistent, agent-aware
  workspaces. Each project connects to its GitHub repository, documentation,
  and <code>AGENTS.md</code>, and ships with an integrated agent that reads
  from and writes to the <a href="https://github.com/emiliano-go/totem">Totem</a>
  memory system as part of its normal workflow. Sessions are just views;
  memory lives in Totem, so every new conversation starts with full context.
</p>

<p align="center">
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white&style=for-the-badge" alt="Python">
  </a>
  <a href="https://github.com/emiliano-go/hestia/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-10AC84?style=for-the-badge" alt="License">
  </a>
</p>

---

## What is hestia

`hestia` is a self-hosted project cockpit for managing software projects as
persistent, agent-aware workspaces. It is not an IDE and not a coding
environment; it is the central place to understand what changed, discuss
features with an agent that knows the project history and architecture, and
(eventually) let agents take actions across GitHub, repositories, CI, and
deployments.

The memory system, Totem, is embedded directly into the agent's tools: the
agent reads from and writes to persistent project memory as part of its
normal workflow, and any session can consult the memories of every other
session. The app is sessionless not because there are no sessions, but
because sessions only save memory, and agents bootstrap from Totem rather
than from chat transcripts.

Agents are read-only for now: they can clone, pull, fetch, read files, and
query GitHub, and write workspace files (plans, specs), but they do not modify the codebase.

## Features

- **Project workspaces**: a creation wizard builds a project from one or many
  Git repositories (each with a short alias) or from nothing at all; `hestia`
  clones them under the data volume and links the repositories, their
  documentation, and `AGENTS.md` into one workspace. The Repositories page
  shows per-repo status, and pull refreshes all clones or a single one.
- **Totem memory in the agent's tools**: the agent's MCP-style toolset
  includes `memory_search`, `memory_get`, `memory_list`, `memory_create`,
  `memory_update`, and `memory_delete`, backed by a per-project
  `.totem/totem.db` that stays file-compatible with the
  [totem](https://github.com/emiliano-go/totem) CLI. Memory is not a chat
  log; it is a curated store of decisions, gotchas, architecture facts, and
  open questions.
- **Sessionless conversations**: chat sessions are lightweight views kept
  for UI replay. Durable knowledge is distilled into Totem at the end of
  every turn, so a brand-new session bootstraps from ranked memory (matched
  against your question) instead of from an ever-growing transcript. Any
  session can consult the memories written by every other session.
- **Contextual chat with any OpenAI-compatible provider**: Kimi, DeepSeek,
  GPT, OpenRouter, or a self-hosted model behind an OpenAI-compatible
  endpoint (Ollama, vLLM, llama.cpp). Providers are configured in the UI
  with per-provider model and endpoint; API keys stay in environment
  variables and are referenced by name.
- **Read-only repository tools**: `git_pull`, `git_log`, `git_diff`,
  `git_show`, `git_status`, `git_branches` (mutating subcommands are
  rejected by a whitelist), plus `list_files`, `read_file`, `grep`,
  `read_agents_md`, and `list_docs`, all sandboxed to the project clone.
- **GitHub tools**: `gh_commits`, `gh_prs`, `gh_issues`, and `gh_ci_runs`
  against the linked repository via the REST API, with an optional token
  for higher rate limits and private repos.
- **Visible agent work**: tool calls and results stream over SSE and render
  as animated rows in the chat (running → done/failed), next to a memory
  browser for inspecting and searching what the agent has learned.
- **Project insight**: each project has a status board (branch, last commit,
  ahead/behind, open PRs, issues, CI), a "since your last visit" digest, a
  GitHub tab for browsing and summarizing PRs/issues/runs, and an activity
  timeline merging sessions, memory, files, commits, and GitHub events.
- **Kanban task board**: tasks are first-class objects, independent of chat
  sessions. Drag cards across columns (backlog/doing/review/done), and let the
  agent manage the board through the `task_list`, `task_create`, `task_update`,
  and `task_delete` tools.
- **Goal mode**: a Goals tab per project. Discuss a goal with the agent (which
  keeps a spec in the workspace), then "Generate board" turns it into a
  milestone with dependency-ordered tasks. "Converge" appends work the spec
  still requires. Goals link their discussion, spec, milestone, and progress.
- **Dependencies and review gates**: tasks can depend on other tasks (blocked
  until they are done), carry acceptance criteria, and cannot move to done
  until the review is confirmed. Comments on a card carry context between
  sessions, and "Implement with agent" seeds a chat from the task brief.
- **Inbox actions**: triage a new PR/issue straight from the dashboard inbox,
  or diagnose a CI failure in a seeded chat.
- **PR review**: one click runs the `code-reviewer` agent over a PR or issue
  and writes `reviews/<kind>-<n>.md` to the workspace.
- **Token budgets**: set a monthly token budget per project; the Overview warns
  at 80%, and scheduled runs can pause when it is spent.
- **GitHub issue sync**: push board tasks to GitHub issues (requires git writes
  and `GITHUB_TOKEN`); synced tasks link back and are never duplicated.
- **Push notifications**: ntfy and/or Telegram. The agent gets a `notify` tool,
  new inbox items and finished/failed scheduled runs push automatically, and a
  budget skip alerts you. Configure with `NTFY_TOPIC` (plus optional
  `NTFY_URL`/`NTFY_TOKEN`) or `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; test
  from About. Email is deliberately not implemented (SMTP setup for little gain
  over the other two).
- **GitHub account connection**: paste a personal access token (repo scope), or
  import the token from the `gh` CLI (`gh auth login`). Stored at
  `<DATA_DIR>/github_token` (0600); `GITHUB_TOKEN` env takes precedence. Enables
  private clones, higher rate limits, and issue/PR writes.
- **Agent questions**: the agent can ask you a blocking question with `ask_user`
  (optionally with choices). The question is stored on the chat session, pushes
  a notification, and survives page reloads; your next message is the answer.
- **Manual steps**: when the work is blocked on something only you can do (run a
  sudo command, sign a commit with GPG, log into a service), `user_required` ends
  the turn with a card showing the exact command to copy, and continues once you
  confirm.
- **Time aware assistant settings**: the system prompt carries the current time,
  your timezone, name, and standing instructions (Settings, Assistant tab).
- **Reminders**: ask the agent ("remind me tomorrow at 9") or add one in the
  Reminders view. Fired as notifications; one-shot, daily, or weekly; snooze
  and done in the UI.
- **Daily briefing**: a deterministic digest (reminders, ready tasks, unread
  inbox) sent at your chosen local time, with optional agent commentary.
- **Watches**: page diff, RSS/Atom new items, and LLM condition checks ("tell
  me when tickets go on sale"). Notifications only fire when something happens;
  condition watches complete when met. The Watches view has pause, run now, and
  the last result.
- **Web fetch**: the agent can read static pages (SSRF guarded, no JavaScript
  rendering), gated by a setting.
- **Browser (optional)**: with the `browser` extra (`uv sync --extra browser`
  plus `browser-use install`; included in the Docker image) the agent runs
  autonomous multi-step web tasks and debugs UIs on a persistent session
  (open, screenshot, content, click, type, eval). Attach to your own Chrome
  over CDP to reuse logins; localhost requires the per-project "local browser"
  toggle. An optional cheap **image-reader** agent describes screenshots so the
  main model never pays vision tokens.
- **Approval gates**: opt-in per project; `git_push` and `gh_open_pr` require an
  approved request from chat when enabled.
- **Suggested work**: "Suggest next work" on the board proposes 2 to 5 backlog
  tasks tagged suggested, for you to keep or delete.
- **Roadmap / milestones**: group tasks into goals with a target date and a
  progress bar, and link Totem memories (decisions, constraints) to the
  milestone's outcome. `milestone_list` / `milestone_create` / `milestone_update`
  let the agent manage them too.
- **Triage**: turn a GitHub issue or PR into a written plan and a set of board
  tasks in one click, run by the configured `triage` action.
- **Cross-project search**: one box searches Totem memory, workspace file names
  and contents, and conversation titles across every project.
- **Inbox**: a background poller watches open PRs/issues and failing CI runs
  and surfaces new ones on the dashboard, with mark-read.
- **Scheduled agents**: per-project automations (nightly repo digest, daily PR
  review, weekly memory curation, or any action + instruction) run by a
  background worker, with the last report shown on the Automations tab. Set
  `HESTIA_DISABLE_SCHEDULER=1` to turn the worker off and
  `HESTIA_INBOX_POLL_SECONDS` (default 600) to tune inbox polling.
- **Generated docs**: write `ARCHITECTURE.md`, `ONBOARDING.md`, or an ADR into
  the workspace from Totem memory in one click (`docs` action).
- **Token usage**: every agent run (chat, docs, triage, memory fix, scheduled
  jobs) records prompt/completion tokens; totals show on the Overview tab and a
  per-action/per-session breakdown lives in About. No pricing tables.
- **Passkey login (opt-in)**: set `HESTIA_SETUP_TOKEN` and Hestia gates every API
  call behind a WebAuthn passkey. Register the first passkey from the login
  screen with that token; the token also recovers access if a device is lost.
  Set `HESTIA_RP_ID` and `HESTIA_ORIGIN` when serving behind a reverse proxy.
- **Gated git writes (opt-in)**: a per-project switch in About gives the agent
  `write_file`, `git_create_branch`, `git_commit`, `git_push`, and `gh_open_pr`.
  Off by default, so code stays read-only; pushes use `GITHUB_TOKEN` on GitHub
  remotes.
- **Persistent workspace**: agent-generated files (plans, specs, research
  notes) go to a per-project workspace directory in the data volume,
  outside the repository, via the `workspace_write` / `workspace_read` /
  `workspace_list` tools (sandboxed the same way as repo file tools).
- **Multiple agents, multiple models**: named agent profiles (Agents page)
  each bind a provider (any OpenAI-compatible model), a system prompt, a
  tool subset, and a turn budget. Pick a profile for the main chat, and let
  the main agent delegate to subagents via `run_subagent`: it runs the
  profile's model against its tool subset and returns a summary. Presets
  include `explore` (repo + files), `github-scan`, `memory-keeper`, and
  `code-reviewer`, so cheap models can do the legwork while a stronger one
  reasons. Subagents cannot spawn further subagents.
- **MCP server included**: the same toolset is exposed over MCP on stdio
  (`hestia-mcp`, with `HESTIA_PROJECT_DIR` set), so external agents get the
  exact same read-only project tools and Totem memory.
- **Single-container self-hosting**: one Docker image, one volume
  (`/data`) holding the registry database, the clones, and the totem
  databases.

## How it works

1. **Register a project** (Projects page): give it a name and a Git URL.
   `hestia` clones the repository into the data volume, snapshots its
   `AGENTS.md`, and initializes the Totem database on first use.
2. **Configure a provider** (Providers page): pick a preset (Kimi,
   DeepSeek, OpenAI, OpenRouter, Ollama, custom) or enter a base URL and
   model by hand. The key is read from the environment variable you name;
   use Test to verify the connection before chatting.
3. **Chat** (project Chat tab): every turn starts by assembling a system
   prompt from the project instructions, the repository layout, and the
   Totem memories ranked most relevant to your question. The agent then
   runs its tool-calling loop: recalling memories, inspecting files and git
   history, and checking GitHub as needed, with each step visible in the
   UI.
4. **Memory grows by itself**: when a turn finishes, its essence is written
   into Totem as a memory, and the agent is instructed to record decisions,
   facts, and architecture explanations as it goes. Nothing durable lives
   only in the transcript.
5. **Come back later, anywhere**: start a new session and the agent already
   knows the project: the memory digest replaces the chat history. Use the
   Memory tab to search, review, and audit what has been learned.

## Agents and subagents

The main chat agent can be any configured agent profile, and it can delegate
to subagents mid-conversation. A profile is a name, a provider (hence a
model), a system prompt, a comma-separated tool subset (`repo`, `files`,
`github`, `memory`), and a `max_turns` budget.

- Create profiles on the Agents page, starting from a preset (`explore`,
  `github-scan`, `memory-keeper`, `code-reviewer`) or from scratch.
- In the chat, pick a profile in the Agent dropdown to run the whole
  conversation with that model and prompt.
- The main agent also gets `run_subagent` and `agent_list` tools: it can hand
  a self-contained read-only task to a profile (for example, "explore" on a
  cheap model) and continue with the summary.

## Quick start

With Docker Compose:

```sh
export KIMI_API_KEY=sk-...   # or any provider you plan to use
docker compose up -d --build
```

Or plain Docker:

```sh
docker build -t hestia .
docker run -p 8080:8080 -v hestia-data:/data \
  -e KIMI_API_KEY=sk-... \
  hestia
```

Open http://localhost:8080, register a project by Git URL, configure a
provider, and chat.

Local development:

```sh
uv sync
uv run uvicorn hestia.main:app --reload --port 8080
```

## Development

```sh
uv run pytest            # tests (run from repo root)
```

## License

MIT
