"""Registry models: projects, sessions, messages, providers.

Sessions and messages are views for the UI; durable cross-session memory
lives in each project's Totem DB, not here.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    # Legacy single-repo mirror of the primary ProjectRepo; multi-repo code
    # reads ProjectRepo rows and only falls back here for pre-migration data.
    repo_url: str = ""
    local_path: str = ""
    agents_md: Optional[str] = None
    default_provider_id: Optional[int] = None
    last_opened_at: Optional[datetime] = None
    allow_git_writes: bool = False  # explicit opt-in: agent may modify the clone
    write_mode: str = ""  # read | ask | auto | yolo; "" derives from allow_git_writes
    require_write_approval: bool = False  # hard gate: push/PR need an approved request
    require_plan: bool = False  # hard gate: writes need a plan + per-step drift check
    allow_local_browser: bool = False  # explicit opt-in: browser may reach localhost
    token_budget: Optional[int] = None  # monthly token budget (None = unlimited)
    budget_enforced: bool = False  # skip scheduled runs once the budget is spent
    created_at: datetime = Field(default_factory=_now)


class ProjectRepo(SQLModel, table=True):
    """One Git repository belonging to a project.

    A project owns one or more repositories; exactly one is primary (the
    legacy ``Project.repo_url``/``local_path`` mirror). Alias is the short
    name the agent and UI use to reference the repo.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    alias: str
    repo_url: str
    local_path: str
    is_primary: bool = False
    created_at: datetime = Field(default_factory=_now)


class Session(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str = "New session"
    action: str = "chat"  # action key the session was started with
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    role: str
    content: str
    thinking: Optional[str] = None  # model reasoning shown in the UI only
    tool_calls: Optional[str] = None  # JSON: OpenAI tool-call list
    tool_call_id: Optional[str] = None  # for role=tool rows
    ok: Optional[bool] = None  # tool result success (role=tool)
    name: Optional[str] = None  # tool name for role=tool
    created_at: datetime = Field(default_factory=_now)


class Provider(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    base_url: str
    api_key_env: str = ""  # optional env var name holding the key
    api_key: Optional[str] = Field(default=None)  # key stored from the UI (optional)
    keys: str = "[]"  # JSON list of extra API keys (rotation pool)
    key_state: str = "{}"  # JSON rotation state: {suspended: {hash: until}, revoked: [hash]}
    model: str = ""  # default model
    small_model: str = ""  # cheap model for titles/summaries/distillation (falls back to model)
    models: str = "[]"  # JSON list of model ids configured for this provider
    created_at: datetime = Field(default_factory=_now)


class AgentConfig(SQLModel, table=True):
    """A named agent profile: its own model, prompt, and tool subset.

    Used for the main agent selection and for subagents spawned via the
    run_subagent tool (e.g. a cheap explore agent).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    system_prompt: str = ""
    provider_id: int = Field(foreign_key="provider.id")
    model: Optional[str] = Field(default=None)  # overrides the provider's model when set
    reasoning_effort: Optional[str] = Field(default=None)  # none|low|medium|high|max
    tools: str = "repo,files"  # comma-separated tool groups: repo, files, github, memory
    mode: str = "read"  # delegation mode: read (no writes) | write (workspace + memory)
    max_turns: int = 6
    created_at: datetime = Field(default_factory=_now)


class Milestone(SQLModel, table=True):
    """A goal that groups tasks and tracks progress.

    ``memories`` is a JSON list of ``{"id", "title"}`` snapshots linking Totem
    memories (decisions, constraints) to the milestone's outcome.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    description: str = ""
    target_date: Optional[str] = None  # ISO date (YYYY-MM-DD), optional
    status: str = "open"  # open | done
    memories: str = "[]"  # JSON: [{"id": ..., "title": ...}]
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Task(SQLModel, table=True):
    """A project task on the kanban board.

    Tasks are their own first-class objects, independent of chat sessions; the
    agent manages them through the task_* tools and the UI as a board.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    milestone_id: Optional[int] = Field(default=None, foreign_key="milestone.id", index=True)
    title: str
    description: str = ""
    status: str = "backlog"  # backlog | todo | doing | review | done
    priority: str = "medium"  # low | medium | high
    position: float = 0.0  # ordering within a column (float to allow inserts)
    depends_on: str = "[]"  # JSON: task ids that must be done first
    acceptance: str = ""  # definition of done; gates the done column
    github_issue: Optional[int] = None  # synced GitHub issue number
    repo: Optional[str] = None  # repo alias for implement/issue sync (None = primary)
    source: str = "user"  # user | suggested
    due_at: Optional[datetime] = None  # UTC deadline, surfaced as at-risk
    pr_url: Optional[str] = None  # pull request opened by the implement runner
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaskComment(SQLModel, table=True):
    """A note on a task card, written by the owner or an agent."""

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    author: str = "you"
    body: str
    created_at: datetime = Field(default_factory=_now)


class Question(SQLModel, table=True):
    """A question the agent asked in a chat session, awaiting the owner.

    The turn that asks ends; the owner's next message answers it, so the
    question survives page reloads and server restarts.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    question: str
    kind: str = "question"  # question | approval | user_required
    meta: str = "{}"  # JSON: action key for approvals; command/details for user_required
    options: str = "[]"  # JSON list of suggested answers
    status: str = "open"  # open | answered | dismissed
    answer: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    answered_at: Optional[datetime] = None


class Goal(SQLModel, table=True):
    """A discussed outcome with a spec, planned into a milestone and tasks.

    The discussion lives in a normal chat session (``session_id``); the spec
    and plan live in the workspace (``spec_path``).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    description: str = ""
    success_criteria: str = ""
    status: str = "drafting"  # drafting | active | done | dropped
    session_id: Optional[str] = Field(default=None, foreign_key="session.id")
    milestone_id: Optional[int] = Field(default=None, foreign_key="milestone.id")
    spec_path: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Watch(SQLModel, table=True):
    """A monitored page, feed, or condition, checked by the worker.

    kind page: snapshot of normalized text, notify on change or on the
    condition phrase appearing. kind feed: track seen item ids, notify only on
    new items. kind condition: a small agent check that notifies when met.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    kind: str = "page"  # page | feed | condition
    url: Optional[str] = None
    condition: str = ""
    interval_minutes: int = 60
    status: str = "active"  # active | paused | done
    notify_on: str = "change"  # change | appear (page watches)
    snapshot: str = ""
    last_result: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)


class Reminder(SQLModel, table=True):
    """A global reminder, optionally linked to a project. Fired by the worker."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    text: str
    due_at: datetime  # UTC
    recurrence: str = "none"  # none | daily | weekly
    status: str = "pending"  # pending | done
    created_at: datetime = Field(default_factory=_now)
    fired_at: Optional[datetime] = None


class Setting(SQLModel, table=True):
    """Global assistant settings (key/value): timezone, briefing, preferences."""

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=_now)


class Passkey(SQLModel, table=True):
    """A registered WebAuthn credential (single-user passkey login)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    credential_id: str = Field(index=True, unique=True)  # base64url
    public_key: str  # base64 CBOR-encoded COSE key
    aaguid: str = ""  # base64
    sign_count: int = 0
    transports: str = ""
    name: str = "Passkey"
    created_at: datetime = Field(default_factory=_now)


class MemoryCandidate(SQLModel, table=True):
    """A proposed memory awaiting approval (or auto-accepted at high confidence).

    Conversation turns become candidates; durable engineering classes are
    auto-accepted into Totem, the rest wait for the owner in the Memory view.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    session_id: Optional[str] = Field(default=None, foreign_key="session.id")
    run_id: Optional[str] = None
    type: str = "observation"
    title: str
    statement: str
    tags: str = "[]"  # JSON list
    confidence: float = 0.5
    source: str = "agent"  # agent | writer | checkpoint
    status: str = "pending"  # pending | accepted | rejected
    created_at: datetime = Field(default_factory=_now)
    decided_at: Optional[datetime] = None


class Usage(SQLModel, table=True):
    """Token usage for one agent run: a chat turn, subagent, or one-shot job."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    session_id: Optional[str] = Field(default=None, foreign_key="session.id", index=True)
    action: str = "chat"  # chat | docs | triage | memory-fix | schedule action
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: datetime = Field(default_factory=_now)


class Schedule(SQLModel, table=True):
    """An automation: a recurring agent run, or a reaction to an event.

    ``trigger`` is "interval" (run every ``interval_minutes``) or "event" (run
    when an Event of ``event`` kind arrives, optionally filtered by a substring
    in ``event_filter``). The worker records the outcome here for the UI.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    action: str = "chat"  # action key from hestia.actions.ACTIONS
    instruction: str = ""
    interval_minutes: int = 1440
    enabled: bool = True
    trigger: str = "interval"  # interval | event
    event: str = ""  # event kind to match when trigger=event
    event_filter: str = ""  # optional substring the event title/url must contain
    cooldown_minutes: int = 0
    last_event_key: str = ""
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None  # ok | error
    last_report: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class Event(SQLModel, table=True):
    """A sensed event that automations can react to (CI failure, watch hit...).

    Emitted by the inbox poller, watchers, and task transitions. The worker
    matches unhandled events against event-triggered schedules and runs them.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str  # ci_failure | pr_opened | issue_opened | watch_hit | task_review | task_done
    key: str = ""  # dedupe key within (project, kind)
    payload: str = "{}"  # JSON: title, url, ...
    status: str = "new"  # new | handled | ignored
    created_at: datetime = Field(default_factory=_now)
    handled_at: Optional[datetime] = None


class BackgroundTask(SQLModel, table=True):
    """A detached agent or subagent run, kimi-code style.

    Started from a chat turn via run_in_background. The manager runs it off
    the request; on completion the originating session gets a notification
    message and, when idle, a continuation turn reacts to the result.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    session_id: Optional[str] = Field(default=None, foreign_key="session.id", index=True)
    kind: str = "agent"  # agent | subagent | swarm
    description: str = ""
    instruction: str = ""
    payload: str = "{}"  # JSON extras for kind="swarm" (directive, tasks, scope)
    action: str = "chat"  # action key, or agent profile name for subagents
    status: str = "queued"  # queued | running | done | error | stopped | lost
    result: str = ""
    error: str = ""
    notified: bool = False
    created_at: datetime = Field(default_factory=_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class InboxItem(SQLModel, table=True):
    """A notification surfaced from GitHub polling (new PR/issue, CI failure)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str  # pr | issue | run
    external_id: str  # dedupe key within a project, e.g. "pr:12" or "api:pr:12"
    repo: str = ""  # repo alias the item came from ("" = primary)
    title: str
    subtitle: str = ""
    url: Optional[str] = None
    read: bool = False
    created_at: datetime = Field(default_factory=_now)


class ActionDefault(SQLModel, table=True):
    """App-wide default agent profile for one action (use-case/role).

    An action is a job the app runs an LLM for: the main chat, or a delegated
    subagent role such as exploring the repo or reviewing code. When an action
    has no agent assigned, the app falls back to the "chat" default (one agent
    for everything) and finally to a profile named like the action.
    """

    action: str = Field(primary_key=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="agentconfig.id")
