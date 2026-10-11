"""Decision service: engine call, veto lane, logging."""

import json

import pytest

from hestia.decision import config
from hestia.decision import service as service_mod
from hestia.decision.config import Settings, VerifySettings
from hestia.decision.service import DecisionService, EvaluateInput


def _answers():
    return {
        "requirements_met": {"type": "noul", "noul": 0.95, "confidence": 0.9},
        "bug_risk": {"type": "score", "score": 0, "confidence": 0.9},
    }


@pytest.mark.asyncio
async def test_evaluate_passes_and_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config, "load_settings", lambda section=None: Settings(enabled=True, base_url="http://laya", verify=VerifySettings(enabled=False))
    )

    async def fake_ask(base_url, state, questions, model=None, api_key=None):
        assert base_url == "http://laya"
        assert state["task"] == "fix it"
        assert state["changes"][0]["input"] == "diff"
        return {"answers": _answers(), "usage": {"input_tokens": 12, "output_tokens": 0}}

    monkeypatch.setattr(service_mod, "ask", fake_ask)
    monkeypatch.setattr(service_mod, "select_memory", lambda *a, **k: [])

    out = await DecisionService().evaluate(
        EvaluateInput(
            task="fix it",
            assistant_text="done",
            mutations=[{"tool": "edit", "input": "i", "output": "o", "diff": "diff", "paths": ["src/a.py"]}],
            project_dir=tmp_path,
            session_id="ses",
            message_id="msg",
        )
    )
    assert out is not None and out.verdict == "pass"
    log = tmp_path / ".encoder" / "decision-log.jsonl"
    assert log.exists()
    assert json.loads(log.read_text().splitlines()[0])["verdict"] == "pass"


@pytest.mark.asyncio
async def test_evaluate_disabled_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_settings", lambda section=None: Settings(enabled=False))
    out = await DecisionService().evaluate(EvaluateInput(task="x", project_dir=tmp_path))
    assert out is None


@pytest.mark.asyncio
async def test_evaluate_veto_skips_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config, "load_settings", lambda section=None: Settings(enabled=True, base_url="http://laya", verify=VerifySettings(enabled=True))
    )

    async def boom(*a, **k):
        raise AssertionError("engine must not be called when the verify lane vetoes")

    monkeypatch.setattr(service_mod, "ask", boom)
    monkeypatch.setattr(service_mod, "select_memory", lambda *a, **k: [])

    out = await DecisionService().evaluate(
        EvaluateInput(
            task="add admin api",
            mutations=[{"tool": "write", "input": 'API_KEY = "sk-live-abcdefgh1234"', "output": "", "paths": ["src/admin.py"]}],
            project_dir=tmp_path,
        )
    )
    assert out is not None and out.verdict == "fail"


def test_decision_ask_disabled(monkeypatch):
    from hestia.decision import config
    from hestia.tools import decision as decision_tool

    monkeypatch.setattr(config, "load_settings", lambda section=None: Settings(enabled=False))
    out = decision_tool._ask(None, {"state": {"task": "x"}})
    assert out["answered"] is False


def test_decision_ask_returns_verdict(monkeypatch):
    from hestia.decision import config
    from hestia.tools import decision as decision_tool

    monkeypatch.setattr(config, "load_settings", lambda section=None: Settings(enabled=True, base_url="http://laya"))
    monkeypatch.setattr(decision_tool, "ask_sync", lambda *a, **k: {"answers": _answers()})
    out = decision_tool._ask(None, {"state": {"task": "x"}})
    assert out["answered"] is True and out["verdict"] == "pass"
