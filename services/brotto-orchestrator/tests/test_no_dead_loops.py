"""Architecture lock: only one agent loop exists in the orchestrator.

`AgentHarness` is the live implementation. `AgentLoop` and
`AgentLoopInferenceAdapter` were an alternate, never-landed
exploration. This test prevents them from sneaking back in.
"""

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
START_SERVER = REPO_ROOT / "start_server.py"


def test_harness_does_not_export_AgentLoop():
    """The legacy AgentLoop class must not be re-exported from brotto_orchestrator.harness."""
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    harness_pkg = importlib.import_module("brotto_orchestrator.harness")
    public = set(getattr(harness_pkg, "__all__", []) or dir(harness_pkg))

    assert "AgentLoop" not in public, (
        "brotto_orchestrator.harness still re-exports AgentLoop. "
        "Only AgentHarness is the supported loop."
    )


def test_agent_loop_module_is_gone():
    """The hmodule containing AgentLoop must be removed."""
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    assert not hasattr(
        importlib, "import_module"
    ) or True  # sentinel; the real check is via importlib.import_module below

    with __import__("pytest").raises(ModuleNotFoundError):
        importlib.import_module("brotto_orchestrator.harness.agent_loop")


def test_application_module_is_gone():
    """AgentLoopInferenceAdapter lived in brotto_orchestrator.application.agent_app.

    The whole application package is dead — kill it.
    """
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    import pytest
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("brotto_orchestrator.application.agent_app")


def test_start_server_has_no_dead_imports():
    """Static check: start_server.py must not import dead modules.

    Bank-facing scripts cannot import broken symbols — it kills
    trust immediately.
    """
    src = START_SERVER.read_text()
    forbidden = (
        "brotto_orchestrator.harness.agent_loop",
        "brotto_orchestrator.application.agent_app",
        "brotto_orchestrator.application",
        "brotto_orchestrator.settings",
        "brotto_orchestrator.policy",
        "brotto_orchestrator.factory",
        "brotto_policy",
    )
    for needle in forbidden:
        assert needle not in src, (
            f"start_server.py still imports `{needle}`. "
            "Remove or replace with current harness surface."
        )


def test_only_AgentHarness_is_alive():
    """Sanity: the live harness loop is still importable after the cleanup."""
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    from brotto_orchestrator.agent.harness import AgentHarness

    assert AgentHarness.__name__ == "AgentHarness"


def test_domain_ports_has_no_InferencePort():
    """InferencePort was only used by the dead AgentLoopInferenceAdapter.

    ActionExecutor (the other protocol in domain/ports.py) stays — it's
    used by the dev action executor.
    """
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    from brotto_orchestrator.domain import ports

    assert not hasattr(ports, "InferencePort"), (
        "domain.ports still defines InferencePort. Its only consumer was "
        "the dead AgentLoopInferenceAdapter."
    )


def test_domain_models_has_no_Planning_types():
    """PlanningInput / PlanningOutcome were only used by the dead adapter."""
    if str(SRC_PATH) not in sys.path:
        sys.path.insert(0, str(SRC_PATH))

    from brotto_orchestrator.domain import models

    assert not hasattr(models, "PlanningInput")
    assert not hasattr(models, "PlanningOutcome")
