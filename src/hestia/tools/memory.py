"""Totem memory tools: these embed the Totem memory system into the agent."""

import json

from hestia import totem_store
from hestia.tools.registry import Registry, Tool, schema

# Durable engineering classes are accepted straight into Totem; everything
# else becomes a candidate for the owner to approve.
AUTO_ACCEPT_TYPES = {
    "decision",
    "gotcha",
    "invariant",
    "contract",
    "constraint",
    "bug",
    "architecture",
    "rejected_idea",
}
AUTO_ACCEPT_CONFIDENCE = 0.7


def register(registry: Registry) -> None:
    registry.register(Tool(
        name="memory_search",
        description="Search project memory (Totem) by full-text query.",
        parameters=schema({
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        }, ["query"]),
        handler=lambda ctx, a: totem_store.search(ctx.memory_path, a["query"], a.get("limit", 20)),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_get",
        description="Fetch a single memory item by id.",
        parameters=schema({"id": {"type": "string"}}, ["id"]),
        handler=lambda ctx, a: totem_store.get(ctx.memory_path, a["id"]),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_list",
        description="List recent project memories.",
        parameters=schema({"limit": {"type": "integer"}}, []),
        handler=lambda ctx, a: totem_store.list_all(ctx.memory_path, a.get("limit", 50)),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_create",
        description=(
            "Write a durable project memory. Types: decision, gotcha, observation, "
            "architecture, implementation, open_question, assumption, bug, contract, "
            "constraint, hypothesis, invariant, rejected_idea. Use for decisions made, "
            "facts learned, and anything future sessions should know. Tag a rule the "
            "agent must always follow with 'preference'; tag facts about a client or "
            "person with 'client' and 'client:<name>' so they stay in context."
        ),
        parameters=schema({
            "type": {"type": "string"},
            "title": {"type": "string"},
            "statement": {"type": "string", "description": "the durable fact/decision, one paragraph"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "details": {"type": "string"},
            "confidence": {"type": "number"},
            "importance": {"type": "number"},
            "asserted_by": {
                "type": "string",
                "description": (
                    "provenance: user, test, source, git, doc, runtime, agent "
                    "(default agent); sets a default confidence when omitted"
                ),
            },
            "applicability": {
                "type": "string",
                "description": "current, legacy, deprecated, planned",
            },
            "scope": {
                "type": "string",
                "description": "user, project, path, task, or JSON {kind, value}",
            },
            "supersedes_id": {
                "type": "string",
                "description": "id of a memory this one replaces (marks it superseded)",
            },
            "related_memory_ids": {"type": "array", "items": {"type": "string"}},
            "evidence": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "evidence objects: path, startLine, endLine, contentHash, "
                    "symbol, blobHash"
                ),
            },
            "metadata": {
                "type": "object",
                "description": (
                    "type-specific fields required by some types: observation "
                    "(observation), decision (rationale), invariant "
                    "(verificationMethod), assumption (claimCategory, basis), "
                    "open_question (question, impact, blocking), ambiguity "
                    "(question, interpretations, impact), rejected_idea "
                    "(proposal, reasonRejected), implementation (subject, kind, path), "
                    "architecture (component)"
                ),
            },
        }, ["type", "title", "statement", "tags"]),
        handler=lambda ctx, a: totem_store.create(
            ctx.memory_path,
            type=a["type"],
            title=a["title"],
            statement=a["statement"],
            tags=a["tags"],
            details=a.get("details"),
            confidence=a.get("confidence"),
            importance=a.get("importance", 0.5),
            asserted_by=a.get("asserted_by") or "agent",
            applicability=a.get("applicability"),
            scope=a.get("scope"),
            supersedes_id=a.get("supersedes_id"),
            related_memory_ids=a.get("related_memory_ids"),
            evidence=a.get("evidence"),
            metadata=a.get("metadata"),
        ),
        group="memory",
        effect="write",
    ))
    registry.register(Tool(
        name="memory_update",
        description=(
            "Update an existing memory item (statement, details, title, tags, "
            "confidence, importance, status, scope, applicability, evidence, "
            "metadata). Illegal lifecycle transitions are rejected."
        ),
        parameters=schema({
            "id": {"type": "string"},
            "title": {"type": "string"},
            "statement": {"type": "string"},
            "details": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
            "importance": {"type": "number"},
            "status": {
                "type": "string",
                "description": "active, potentially_stale, invalidated, resolved, superseded",
            },
            "scope": {"type": "string"},
            "applicability": {
                "type": "string",
                "description": "current, legacy, deprecated, planned",
            },
            "evidence": {"type": "array", "items": {"type": "object"}},
            "metadata": {"type": "object"},
            "reason": {"type": "string", "description": "why this update"},
        }, ["id"]),
        handler=lambda ctx, a: totem_store.update(
            ctx.memory_path, a["id"],
            reason=a.get("reason"),
            title=a.get("title"),
            statement=a.get("statement"),
            details=a.get("details"),
            tags=a.get("tags"),
            confidence=a.get("confidence"),
            importance=a.get("importance"),
            status=a.get("status"),
            scope=a.get("scope"),
            applicability=a.get("applicability"),
            evidence=a.get("evidence"),
            metadata=a.get("metadata"),
        ),
        group="memory",
        effect="write",
    ))
    registry.register(Tool(
        name="memory_delete",
        description="Soft-delete a memory item with a reason.",
        parameters=schema({
            "id": {"type": "string"},
            "reason": {"type": "string"},
        }, ["id", "reason"]),
        handler=lambda ctx, a: totem_store.delete(ctx.memory_path, a["id"], a["reason"]),
        group="memory",
        effect="write",
    ))
    registry.register(Tool(
        name="memory_relate",
        description=(
            "Create a typed relation between two project memories: supersedes, "
            "contradicts, invalidates, derived_from, verified_by, refines, "
            "depends_on. supersedes/invalidates update the target's status."
        ),
        parameters=schema({
            "from_id": {"type": "string"},
            "to_id": {"type": "string"},
            "kind": {"type": "string"},
        }, ["from_id", "to_id", "kind"]),
        handler=lambda ctx, a: totem_store.relate(
            ctx.memory_path, a["from_id"], a["to_id"], a["kind"]
        ),
        group="memory",
        effect="write",
    ))
    registry.register(Tool(
        name="memory_relations",
        description="List the typed relations involving a memory.",
        parameters=schema({"id": {"type": "string"}}, ["id"]),
        handler=lambda ctx, a: totem_store.relations(ctx.memory_path, a["id"]),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_history",
        description=(
            "The immutable audit timeline of a memory (who changed what, when), "
            "for explaining why the agent believed something."
        ),
        parameters=schema({"id": {"type": "string"}}, ["id"]),
        handler=lambda ctx, a: totem_store.history(ctx.memory_path, a["id"]),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_export",
        description="Export all project memories, conflicts, and relations as a portable JSON archive.",
        parameters=schema({}, []),
        handler=lambda ctx, a: totem_store.export_all(ctx.memory_path),
        group="memory",
    ))
    registry.register(Tool(
        name="memory_import",
        description=(
            "Import a memory archive produced by memory_export. mode: normal (skip "
            "invalid), strict (abort on any error), or replace (clear first)."
        ),
        parameters=schema({
            "data": {"type": "object"},
            "mode": {"type": "string", "enum": ["normal", "strict", "replace"]},
            "dry_run": {"type": "boolean"},
        }, ["data"]),
        handler=lambda ctx, a: totem_store.import_all(
            ctx.memory_path, a["data"], mode=a.get("mode", "normal"), dry_run=bool(a.get("dry_run"))
        ),
        group="memory",
        effect="write",
    ))


def register_candidates(registry: Registry, db) -> None:
    """Candidate-memory tools (require a DB session)."""

    def candidate_handler(ctx, args):
        from hestia.registry.models import MemoryCandidate

        type_ = str(args.get("type") or "observation").strip().lower()
        title = (args.get("title") or "").strip()
        statement = (args.get("statement") or "").strip()
        tags = [str(t).strip() for t in (args.get("tags") or []) if str(t).strip()]
        if not title or not statement:
            raise ValueError("title and statement are required")
        confidence = float(args.get("confidence", 0.5))
        if type_ in AUTO_ACCEPT_TYPES and confidence >= AUTO_ACCEPT_CONFIDENCE:
            metadata = args.get("metadata")
            if type_ == "invariant" and not (metadata or {}).get("verificationMethod"):
                metadata = {**(metadata or {}), "verificationMethod": "owner review"}
            item = totem_store.create(
                ctx.memory_path,
                type=type_,
                title=title,
                statement=statement,
                tags=tags or ["memory"],
                confidence=confidence,
                metadata=metadata,
                asserted_by="agent",
            )
            return {
                "accepted": True,
                "type": type_,
                "memory_id": item.get("id") if isinstance(item, dict) else None,
            }
        row = MemoryCandidate(
            project_id=ctx.project_id,
            session_id=ctx.session_id,
            run_id=ctx.run_id,
            type=type_,
            title=title,
            statement=statement,
            tags=json.dumps(tags or ["memory"]),
            confidence=confidence,
            source=str(args.get("source") or "agent"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"accepted": False, "candidate_id": row.id, "status": "pending"}

    def none_handler(ctx, args):
        return {"acknowledged": True, "reason": (args.get("reason") or "").strip()[:300]}

    registry.register(Tool(
        name="memory_candidate",
        description=(
            "Propose a memory for approval instead of writing it directly. Durable "
            "engineering classes (decision, gotcha, invariant, contract, constraint, "
            "bug, architecture, rejected_idea) at confidence >= 0.7 are accepted "
            "immediately; everything else waits in the Memory view. Use this when "
            "unsure whether a fact is durable."
        ),
        parameters=schema({
            "type": {"type": "string"},
            "title": {"type": "string"},
            "statement": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "description": "0..1"},
            "metadata": {"type": "object"},
            "source": {"type": "string", "description": "writer | checkpoint | agent"},
        }, ["type", "title", "statement"]),
        handler=candidate_handler,
        group="memory",
        effect="write",
    ))
    registry.register(Tool(
        name="memory_none",
        description=(
            "Acknowledge a memory checkpoint when there is genuinely nothing "
            "durable to record from this turn. Give a one-line reason."
        ),
        parameters=schema({"reason": {"type": "string"}}, []),
        handler=none_handler,
        group="memory",
        effect="write",
    ))
