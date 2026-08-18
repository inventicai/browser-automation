"""Smoke tests for the benchmark CI workflow YAML.

Pure string-content checks: we don't parse the YAML, we grep it.
Failures here mean the workflow drifted from the contract below.
"""

from __future__ import annotations

import re
from pathlib import Path

# tests/bench/test_ci_workflow.py lives at services/brotto-orchestrator/tests/bench/
# so the repo root is 4 parents up: bench -> tests -> brotto-orchestrator -> services -> repo
REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "bench.yml"


def test_workflow_exists() -> None:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW}"


def _text() -> str:
    return WORKFLOW.read_text()


def test_triggers_include_cron_and_push() -> None:
    text = _text()
    # nightly at 04:00 UTC
    assert re.search(r"cron:\s*['\"]?0 4 \* \* \*['\"]?", text), "expected nightly cron at 04:00 UTC"
    # push to main
    assert re.search(r"branches:\s*\n\s*-\s*main", text) or "'main'" in text, "expected push to main"
    # push to experimental/**
    assert "experimental/**" in text, "expected push to experimental/**"


def test_matrix_has_three_models() -> None:
    text = _text()
    for m in ("haiku-4-5", "sonnet-4-6", "opus-4-7"):
        assert m in text, f"model {m!r} missing from matrix"


def test_uses_orchestrator_venv() -> None:
    text = _text()
    assert "services/brotto-orchestrator/.venv/bin/python" in text, (
        "must invoke the orchestrator venv python directly"
    )


def test_uses_anthropic_api_key_secret() -> None:
    text = _text()
    assert "ANTHROPIC_API_KEY" in text
    assert "secrets.ANTHROPIC_API_KEY" in text or "secrets:" in text


def test_sets_agent_model_per_matrix() -> None:
    text = _text()
    assert "AGENT_MODEL" in text, "AGENT_MODEL must be exported per matrix run"


def test_uploads_jsonl_artifact() -> None:
    text = _text()
    assert "actions/upload-artifact" in text
    assert "jsonl" in text.lower()


def test_regression_check_present() -> None:
    text = _text()
    # 5pp drop is the contract
    assert "5" in text and ("percentage" in text.lower() or "pp" in text or "0.05" in text), (
        "regression threshold (5pp) must be present"
    )
    # baseline pull from prior workflow run
    assert "actions/download-artifact" in text, "must download prior run's artifact for baseline"


def test_writes_markdown_summary() -> None:
    text = _text()
    assert "github-actions" in text or "summary" in text.lower(), (
        "must emit a job summary (markdown table of pass/fail by task x model)"
    )
