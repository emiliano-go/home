"""Agent actions (roles) and global per-action default resolution.

An action is a use-case the app runs an LLM for: the main chat, or a delegated
subagent role such as exploring the repo. The app-wide default agent profile
for each action is stored in ActionDefault and resolved here so normal setups
can use a single agent for everything while advanced setups specialise.
"""

from sqlmodel import Session, select

from hestia.providers.base import resolve_model
from hestia.registry.models import ActionDefault, AgentConfig

ACTIONS: list[dict] = [
    {
        "key": "chat",
        "label": "Main chat",
        "description": (
            "The conversation in the Chat tab: answers questions, inspects the "
            "repo and GitHub, recalls and writes Totem memory, and can delegate."
        ),
        "tools": "repo,files,github,memory,workspace,tasks,agents,background,automations",
    },
    {
        "key": "explore",
        "label": "Explore repository",
        "description": "Investigate structure, files, and git history, and return findings.",
        "tools": "repo,files",
    },
    {
        "key": "github-scan",
        "label": "Scan GitHub",
        "description": "Inspect commits, pull requests, issues, and CI runs for the repo.",
        "tools": "github,repo",
    },
    {
        "key": "memory-keeper",
        "label": "Curate memory",
        "description": "Review Totem memory, find gaps or stale entries, and write new memories.",
        "tools": "memory",
    },
    {
        "key": "writer",
        "label": "Write documents",
        "description": "Produce plans, specs, and docs in the project workspace.",
        "tools": "workspace,repo,files",
    },
    {
        "key": "code-reviewer",
        "label": "Review code",
        "description": "Read code and diffs and return findings ordered by severity.",
        "tools": "repo,files,github",
    },
    {
        "key": "goal",
        "label": "Goal planning",
        "description": (
            "Discuss a goal, keep a living spec in the workspace, and plan it "
            "into a milestone with dependency-aware tasks."
        ),
        "tools": "repo,files,github,memory,workspace,tasks,agents,background,automations",
    },
    {
        "key": "image",
        "label": "Generate images",
        "description": "Turn text prompts into images saved in the project workspace.",
        "tools": "images,workspace",
    },
    {
        "key": "browser",
        "label": "Browse the web",
        "description": (
            "Drive a real browser: autonomous web tasks and UI debugging with "
            "browser-use."
        ),
        "tools": "browser",
    },
    {
        "key": "memory-writer",
        "label": "Write memories",
        "description": (
            "Curate a finished turn into durable Totem memories with a cheap "
            "model, so the main agent never waits."
        ),
        "tools": "memory",
    },
    {
        "key": "image-reader",
        "label": "Read images",
        "description": (
            "Describe screenshots and images for the main agent, so expensive "
            "models do not pay vision tokens."
        ),
        "tools": "browser",
    },
    {
        "key": "docs",
        "label": "Generate documentation",
        "description": (
            "Write an architecture, onboarding, or ADR document into the project "
            "workspace from Totem memory and the repository."
        ),
        "tools": "workspace,memory,repo,files",
    },
    {
        "key": "implement",
        "label": "Implement a task",
        "description": (
            "Implement a board task on a new branch, commit, push, and open a "
            "pull request, then move the task to review."
        ),
        "tools": "repo,files,github,workspace,tasks",
    },
    {
        "key": "bulk-edit",
        "label": "Bulk code edits",
        "description": (
            "Delegate large mechanical changes (doc sweeps, renames, typo "
            "fixes) to a cheap write agent: it edits files in the clone, the "
            "principal commits and opens the pull request."
        ),
        "tools": "repo,files,writes,workspace",
    },
    {
        "key": "capture",
        "label": "Capture notes",
        "description": (
            "Turn pasted notes, an email, or a thread into tasks, reminders, "
            "decisions, and client facts on the board and in memory."
        ),
        "tools": "tasks,memory,workspace,reminders,watches,automations",
    },
    {
        "key": "triage",
        "label": "Triage GitHub item",
        "description": (
            "Turn a GitHub issue or PR into a written plan and a set of tasks on the board."
        ),
        "tools": "github,workspace,tasks,files,repo",
    },
    {
        "key": "memory-fix",
        "label": "Repair memory",
        "description": "Apply a natural-language repair instruction to the Totem memory store.",
        "tools": "memory",
    },
]

ACTIONS_BY_KEY: dict[str, dict] = {a["key"]: a for a in ACTIONS}


def action_defaults(db: Session) -> dict[str, int | None]:
    """Mapping of action key -> configured default agent id (or None)."""
    rows = {r.action: r.agent_id for r in db.exec(select(ActionDefault)).all()}
    return {a["key"]: rows.get(a["key"]) for a in ACTIONS}


def resolve_action(db: Session, key: str) -> AgentConfig | None:
    """Best agent profile for an action, or None to fall back to a raw provider.

    Resolution order:
      1. the agent explicitly assigned to this action;
      2. the "chat" agent (the single agent used for everything);
      3. a profile whose name matches the action (e.g. one made from a preset).
    """
    row = db.get(ActionDefault, key)
    if row and row.agent_id:
        agent = db.get(AgentConfig, row.agent_id)
        if agent:
            return agent
    if key != "chat":
        fallback = db.get(ActionDefault, "chat")
        if fallback and fallback.agent_id:
            agent = db.get(AgentConfig, fallback.agent_id)
            if agent:
                return agent
    return db.exec(select(AgentConfig).where(AgentConfig.name == key)).first()


def effective_provider(agent, provider):
    """The provider with its model and reasoning effort from the agent.

    Lets every downstream ``provider.model`` use the right model without
    threading it through each call site; the effort rides along as an extra
    attribute on the returned copy (not a Provider column).
    """
    if provider is None:
        return None
    model = resolve_model(agent, provider)
    effort = getattr(agent, "reasoning_effort", None) or getattr(
        provider, "reasoning_effort", None
    )
    if (model and model != provider.model) or effort:
        return provider.model_copy(update={"model": model, "reasoning_effort": effort})
    return provider
