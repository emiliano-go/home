"""Decision engine units: scoring, state normalization, verify lane."""

from hestia.decision import scoring, state, verify
from hestia.decision.config import Settings
from hestia.decision.questions import DEFAULT_QUESTIONS


def _answers(req=0.95, bug=0.0, conf=0.9):
    return {
        "requirements_met": {"type": "noul", "noul": req, "confidence": conf},
        "bug_risk": {"type": "score", "score": bug, "confidence": conf},
    }


def test_value_of_normalizes_score_questions():
    assert scoring.value_of("bug_risk", {"score": 0}) == 1.0
    assert scoring.value_of("bug_risk", {"score": 3}) == 0.0
    assert scoring.value_of("answer_quality", {"score": 3}) == 1.0
    assert scoring.value_of("requirements_met", {"noul": 0.8}) == 0.8


def test_decide_passes_good_turn():
    result = scoring.decide(_answers(), DEFAULT_QUESTIONS, Settings())
    assert result.verdict == "pass"
    assert result.composite > 0.9
    assert result.vetoes == []


def test_decide_vetoes_low_criterion():
    result = scoring.decide(_answers(bug=2), DEFAULT_QUESTIONS, Settings())
    assert result.verdict == "fail"
    assert "bug_risk" in result.vetoes


def test_decide_confidence_floor_marks_review():
    result = scoring.decide(_answers(conf=0.3), DEFAULT_QUESTIONS, Settings())
    assert result.verdict == "needs_review"


def test_decide_fails_below_threshold():
    result = scoring.decide(_answers(req=0.55), DEFAULT_QUESTIONS, Settings())
    assert result.verdict == "fail"
    assert result.composite < 0.8


def test_logodds_aggregation_differs_from_weighted():
    answers = {
        "requirements_met": {"type": "noul", "noul": 0.44},
        "bug_risk": {"type": "score", "score": 0.52},
    }
    weighted = scoring.decide(answers, DEFAULT_QUESTIONS, Settings(aggregation="weighted"))
    logodds = scoring.decide(answers, DEFAULT_QUESTIONS, Settings(aggregation="logodds"))
    assert abs((weighted.composite or 0) - (logodds.composite or 0)) > 0.01


def test_failures_list_low_criteria():
    result = scoring.decide(_answers(req=0.2), DEFAULT_QUESTIONS, Settings())
    keys = [failure.key for failure in result.failures]
    assert "requirements_met" in keys


def test_feedback_mentions_composite_and_failures():
    result = scoring.decide(_answers(req=0.2), DEFAULT_QUESTIONS, Settings())
    text = scoring.feedback(composite=result.composite, threshold=0.8, failures=result.failures)
    assert "failed" in text and "requirements_met" in text


def test_normalize_state_caps_task_memory_and_diffs():
    normalized = state.normalize_state(
        {
            "task": "x" * 5000,
            "memory": [{"id": str(i), "type": "invariant", "title": "t" * 200, "statement": "s" * 400} for i in range(5)],
            "changes": [{"tool": "edit", "input": "i", "output": "o", "diff": "d" * 5000} for _ in range(6)],
            "grounding": [],
        }
    )
    assert len(normalized["task"]) <= 620
    assert len(normalized["memory"]) == 2
    assert len(normalized["memory"][0]["statement"]) <= 200
    total = sum(len(change.get("diff", "")) for change in normalized["changes"])
    assert total <= state.MAX_DIFF_TOTAL


def test_verify_flags_secret_and_injection():
    findings, veto = verify.verify_changes(
        [
            {"tool": "write", "input": 'API_KEY = "sk-live-abcdefgh1234"', "output": ""},
            {"tool": "edit", "input": 'db.query("SELECT * FROM u WHERE id = \'" + user)', "output": ""},
        ]
    )
    rules = {finding["rule"] for finding in findings}
    assert "secret-hardcoded" in rules
    assert "sql-or-code-injection" in rules
    assert veto is True


def test_verify_execution_evidence_last_result_wins():
    findings, veto = verify.verify_changes(
        [
            {"tool": "bash", "input": "pytest", "output": "FAILED (failures=1)"},
            {"tool": "bash", "input": "pytest", "output": "12 passed"},
        ]
    )
    assert veto is False
    assert findings == []


def test_run_verify_command_nonzero_vetoes():
    findings, _ = verify.run_verify_command("exit 3", cwd=".")
    assert any(finding["severity"] == "high" for finding in findings)
