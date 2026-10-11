"""Deterministic verify lane, ported from encoder's `session/verify.ts`.

High-precision built-in rules over a turn's tool calls/outputs; any high-severity
finding vetoes the turn. Optional external scanners (gitleaks/semgrep/bandit/
shellcheck) add precision when installed and are silently skipped otherwise.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

MAX_FINDINGS = 20
EXTERNAL_TIMEOUT_S = 10
MAX_EXTERNAL_FILES = 20

SECRET_PATTERNS = [
    re.compile(r"\bsk-(?:live|test|prod)-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[\"']?(?:api[_-]?key|secret|token|password)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_+/=-]{16,}[\"']", re.IGNORECASE),
]

INJECTION_PATTERNS = [
    re.compile(r"[\"'](?:SELECT|INSERT|UPDATE|DELETE)\b[^\"']*[\"']\s*[\"']?\s*\+\s*(?:email|user|name|input|id|query|req|val)", re.IGNORECASE),
    re.compile(r"f[\"'][^\"']*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^\"']*\{", re.IGNORECASE),
    re.compile(r"[\"'][^\"']*\b(?:SELECT|INSERT|UPDATE|DELETE)\b[^\"']*[\"']\s*%\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.system\(\s*f?[\"']"),
    re.compile(r"subprocess\.(?:run|Popen|call)\([^)]*shell\s*=\s*True"),
    re.compile(r"child_process\.(?:exec|execSync)\("),
    re.compile(r"\beval\(\s*(?:request|req|input|params|args)", re.IGNORECASE),
]

DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("high", re.compile(r"(?:^|[\s;&|])rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(?:\s|$|\*)"), "rm -rf /"),
    ("high", re.compile(r"(?:^|[\s;&|])rm\s+-[a-z]*f[a-z]*r[a-z]*\s+/(?:\s|$|\*)"), "rm -fr /"),
    ("high", re.compile(r"curl[^|;\n]*\|\s*(?:ba|z|da)?sh\b"), "curl | sh"),
    ("high", re.compile(r"wget[^|;\n]*\|\s*(?:ba|z)?sh\b"), "wget | sh"),
    ("high", re.compile(r"\bchmod\s+(?:-R\s+)?777\b"), "chmod 777"),
    ("high", re.compile(r"git\s+push[^\n]*--force[^\n]*\b(?:main|master)\b"), "force push to main"),
    ("medium", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "DROP TABLE"),
]

TEST_MARKERS = re.compile(r"ran \d+ tests?|test session starts|test suites?:|\d+ passing|\d+ failing|\d+ passed", re.IGNORECASE)
TEST_FAILURES = re.compile(r"\bFAILED\b|\bfailures?=[1-9]\b|\b[1-9]\d* failed\b|\b[1-9]\d* failing\b")
TYPE_ERRORS = re.compile(r"\berror TS\d+")
LSP_ERRORS = re.compile(r"LSP errors detected in")
LINT_MARKERS = re.compile(r"\d+ problems? \((\d+) errors?")


def _first_line(text: str, pattern: re.Pattern) -> str:
    for line in text.split("\n"):
        if pattern.search(line):
            return line.strip()[:160]
    return ""


def _redact(value: str) -> str:
    return re.sub(r"[A-Za-z0-9_+/=-]{12,}", lambda m: f"{m.group(0)[:4]}…", value)


def _scan(change: dict, patterns: list[re.Pattern], rule: str, severity: str, label: str | None = None) -> list[dict]:
    text = f"{change.get('input', '')}\n{change.get('output', '')}"
    findings = []
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        paths = change.get("paths") or []
        findings.append(
            {
                "rule": rule,
                "severity": severity,
                "detail": f"{label or rule}: {_redact(match.group(0))[:140]}",
                "tool": change.get("tool", ""),
                **({"path": paths[0]} if paths else {}),
            }
        )
    return findings


def execution_signals(output: str) -> list[dict]:
    signals: list[dict] = []
    if TEST_MARKERS.search(output):
        signals.append({"family": "tests", "failed": bool(TEST_FAILURES.search(output)), "detail": _first_line(output, TEST_FAILURES) or _first_line(output, TEST_MARKERS)})
    if TYPE_ERRORS.search(output):
        signals.append({"family": "typecheck", "failed": True, "detail": _first_line(output, TYPE_ERRORS)})
    if LSP_ERRORS.search(output):
        signals.append({"family": "lsp", "failed": True, "detail": _first_line(output, LSP_ERRORS)})
    lint = LINT_MARKERS.search(output)
    if lint:
        signals.append({"family": "lint", "failed": int(lint.group(1)) > 0, "detail": _first_line(output, LINT_MARKERS)})
    return signals


def execution_evidence(changes: list[dict]) -> list[dict]:
    last: dict[str, dict] = {}
    for change in changes:
        for signal in execution_signals(change.get("output", "")):
            paths = change.get("paths") or []
            last[signal["family"]] = {
                "kind": signal["family"],
                "status": "fail" if signal["failed"] else "pass",
                "summary": signal["detail"][:300],
                "tool": change.get("tool", ""),
                **({"path": paths[0]} if paths else {}),
            }
    return list(last.values())


def verify_changes(changes: list[dict], disable: tuple[str, ...] = ()) -> tuple[list[dict], bool]:
    disabled = set(disable)
    findings: list[dict] = []
    for change in changes:
        if "secret-hardcoded" not in disabled:
            findings += _scan(change, SECRET_PATTERNS, "secret-hardcoded", "high")
        if "sql-or-code-injection" not in disabled:
            findings += _scan(change, INJECTION_PATTERNS, "sql-or-code-injection", "high")
        if "destructive-command" not in disabled:
            for severity, pattern, label in DESTRUCTIVE_PATTERNS:
                findings += _scan(change, [pattern], "destructive-command", severity, label)
    for evidence in execution_evidence(changes):
        if evidence["status"] != "fail":
            continue
        rule = f"execution-{evidence['kind']}"
        if rule in disabled:
            continue
        findings.append(
            {
                "rule": rule,
                "severity": "high",
                "detail": f"{rule}: {evidence['summary'] or evidence['kind']}",
                "tool": evidence.get("tool") or "bash",
                **({"path": evidence["path"]} if evidence.get("path") else {}),
            }
        )
    capped = findings[:MAX_FINDINGS]
    return capped, any(finding["severity"] == "high" for finding in capped)


def run_verify_command(command: str, cwd: str, timeout_s: int = 60) -> tuple[list[dict], list[dict]]:
    try:
        proc = subprocess.run(["/bin/sh", "-c", command], cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
        code, output = proc.returncode, f"{proc.stdout}\n{proc.stderr}".strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        code, output = 1, str(error)
    evidence = execution_evidence([{"tool": "verify", "input": command, "output": output}])
    findings = [
        {"rule": f"execution-{entry['kind']}", "severity": "high", "detail": f"verify command: {entry['summary'] or entry['kind']}"[:200], "tool": "verify"}
        for entry in evidence
        if entry["status"] == "fail"
    ]
    if code != 0 and not findings:
        findings.append({"rule": "verify-command", "severity": "high", "detail": f"verify command exited {code}: {_first_line(output, re.compile('.'))}"[:200], "tool": "verify"})
    return findings, evidence


def _external_findings(adapter_id: str, file: str, parsed: Any) -> list[dict]:
    def push(severity: str, detail: str) -> list[dict]:
        return [{"rule": f"external-{adapter_id}", "severity": severity, "detail": f"{adapter_id}: {detail}"[:200], "tool": adapter_id, "path": file}]

    if adapter_id == "gitleaks":
        if not isinstance(parsed, list):
            return []
        return [
            finding
            for entry in parsed
            if isinstance(entry, dict)
            for finding in push("high", f"{entry.get('Description') or entry.get('RuleID') or 'secret'} in {file}:{entry.get('StartLine', '?')}")
        ]
    if adapter_id == "semgrep":
        results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(results, list):
            return []
        out = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
            severity = "high" if str(extra.get("severity", "WARNING")).upper() == "ERROR" else "medium"
            line = entry.get("start", {}).get("line", "?") if isinstance(entry.get("start"), dict) else "?"
            out += push(severity, f"{entry.get('check_id', 'rule')} at {file}:{line}")
        return out
    if adapter_id == "bandit":
        results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(results, list):
            return []
        return [
            finding
            for entry in results
            if isinstance(entry, dict)
            for finding in push("high" if str(entry.get("issue_severity", "")).upper() == "HIGH" else "medium", f"{entry.get('test_id', 'bandit')} {entry.get('issue_text', '')}".strip())
        ]
    if adapter_id == "shellcheck":
        if not isinstance(parsed, list):
            return []
        return [
            finding
            for entry in parsed
            if isinstance(entry, dict)
            for finding in push("high" if str(entry.get("level", "warning")).lower() == "error" else "medium", f"{entry.get('code', 'SC')} {entry.get('message', '')}".strip())
        ]
    return []


EXTERNAL_ADAPTERS = [
    ("gitleaks", "gitleaks", lambda f: True, lambda f: ["detect", "--no-git", "--source", f, "--report-format", "json", "--report-path", "/dev/stdout", "--no-banner", "--exit-code", "0"]),
    ("semgrep", "semgrep", lambda f: True, lambda f: ["scan", "--json", "--quiet", "--config", "auto", f]),
    ("bandit", "bandit", lambda f: f.endswith(".py"), lambda f: ["-f", "json", "-q", f]),
    ("shellcheck", "shellcheck", lambda f: bool(re.search(r"\.(sh|bash)$", f)), lambda f: ["-f", "json", "-S", "error", f]),
]


def verify_external_files(paths: list[str], cwd: str | None = None, mode: str = "auto", disable: tuple[str, ...] = ()) -> list[dict]:
    if mode == "off":
        return []
    files = list(dict.fromkeys(paths))[:MAX_EXTERNAL_FILES]
    if not files:
        return []
    disabled = set(disable)
    findings: list[dict] = []
    for adapter_id, binary, supports, args in EXTERNAL_ADAPTERS:
        if f"external-{adapter_id}" in disabled or shutil.which(binary) is None:
            continue
        for file in [candidate for candidate in files if supports(candidate)]:
            try:
                proc = subprocess.run([binary, *args(file)], cwd=cwd, capture_output=True, text=True, timeout=EXTERNAL_TIMEOUT_S)
                parsed = json.loads(proc.stdout)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                continue
            findings += _external_findings(adapter_id, file, parsed)
            if len(findings) >= MAX_FINDINGS:
                return findings[:MAX_FINDINGS]
    return findings[:MAX_FINDINGS]
