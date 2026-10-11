"""Default tool registry for a project context.

``writes=True`` adds the opt-in mutating git tools; only pass it when the
project has ``allow_git_writes`` set.
"""

from hestia.tools import files, github, memory, notify, plan, repo, webfetch, workspace
from hestia.tools import decision, editing, gitwrites, preferences, skills
from hestia.tools.registry import Registry


def build_registry(writes: bool = False, db=None) -> Registry:
    registry = Registry()
    repo.register(registry, db)
    files.register(registry)
    github.register(registry)
    memory.register(registry)
    workspace.register(registry)
    plan.register(registry)
    notify.register(registry)
    webfetch.register(registry)
    skills.register(registry)
    decision.register(registry)
    if writes:
        editing.register(registry, db)
        gitwrites.register(registry, db)
    if db is not None:
        from hestia.tools import jobs as job_tools
        from hestia.tools import schedules as schedule_tools

        memory.register_candidates(registry, db)
        for tool in preferences.make_tools(db):
            registry.register(tool)
        for tool in job_tools.make_tools(db):
            registry.register(tool)
        for tool in schedule_tools.make_tools(db):
            registry.register(tool)
    return registry
