"""Context compaction: tool-output pruning + tail budget."""

from hestia.agent import compaction


def _messages(n_tools=12, big=4000):
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "first"}]
    for i in range(n_tools):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "x" * big})
    return messages


def test_prune_keeps_recent_tool_outputs():
    messages = _messages(n_tools=12)
    changed = compaction.prune_tool_outputs(messages, keep_recent=3)
    assert changed is True
    tools = [m for m in messages if m["role"] == "tool"]
    assert sum(1 for m in tools if m["content"] == compaction.TOOL_PLACEHOLDER) == 9
    assert tools[-1]["content"] != compaction.TOOL_PLACEHOLDER


def test_prune_is_idempotent():
    messages = _messages(n_tools=12)
    compaction.prune_tool_outputs(messages, keep_recent=3)
    assert compaction.prune_tool_outputs(messages, keep_recent=3) is False


def test_compact_stays_within_budget():
    messages = _messages(n_tools=40, big=8000)
    compacted, changed = compaction.compact(messages, token_budget=6000, keep_recent_tools=4)
    assert changed is True
    assert compaction.estimate_tokens(compacted) <= 6000
    assert compacted[0]["role"] == "system"


def test_compact_never_starts_tail_with_tool_result():
    messages = _messages(n_tools=40, big=8000)
    compacted, _ = compaction.compact(messages, token_budget=3000, keep_recent_tools=2)
    assert compacted[1]["role"] == "user"
    for i, message in enumerate(compacted):
        if message["role"] == "tool":
            assert i > 0
            assert compacted[i - 1].get("role") == "assistant"
            assert compacted[i - 1].get("tool_calls")


def test_compact_noop_under_budget():
    messages = _messages(n_tools=2, big=100)
    compacted, changed = compaction.compact(messages, token_budget=100_000)
    assert changed is False
    assert compacted == messages
