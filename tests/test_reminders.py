"""Synthetic per-turn reminders."""

from hestia.agent import reminders


def _messages():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "and this"},
    ]


def test_no_notes_is_a_noop():
    messages = _messages()
    assert reminders.apply(messages) == messages


def test_plan_reminder_lands_on_last_user_message():
    messages = reminders.apply(_messages(), plan_mode=True)
    assert reminders.MARKER in messages[-1]["content"]
    assert "Plan mode" in messages[-1]["content"]
    assert reminders.MARKER not in messages[1]["content"]


def test_decision_reminder():
    messages = reminders.apply(_messages(), decision=True)
    assert "decision engine" in messages[-1]["content"]


def test_idempotent():
    once = reminders.apply(_messages(), plan_mode=True, decision=True)
    twice = reminders.apply(once, plan_mode=True, decision=True)
    assert once[-1]["content"].count(reminders.MARKER) == 1
    assert twice[-1]["content"] == once[-1]["content"]
