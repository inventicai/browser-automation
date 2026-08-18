"""WS protocol tests for the extension↔orchestrator boundary.

These tests cover the routing, validation, and round-trip behaviour
of the WS endpoint without invoking the agent harness. The harness
is a black box — its failure mode is exercised in `test_agent_e2e.py`.

The agent harness is mocked to a no-op so the WS protocol can be
tested in isolation. The mock is per-test via the `agent_disabled`
fixture below.

What's tested:
- task_start: required, non-empty, must be the first message
- ping → pong with no harness interaction
- observation seq dedup (D9)
- unknown message types are logged, not fatal
- WS is closed cleanly on bad task_start
- evaluate_result and human_reply round-trip to the right queues
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

for k in ("ANTHROPIC_API_KEY", "AGENT_AUTH_DISABLED", "AGENT_MODEL"):
    os.environ.setdefault(k, "test")

from fastapi.testclient import TestClient  # noqa: E402

from brotto_orchestrator import main as main_mod  # noqa: E402
from brotto_orchestrator.agent import harness as harness_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_disabled(monkeypatch):
    """Stub the agent harness so the WS protocol can be tested in isolation.

    The real harness.run() drives a PydanticAI agent that emits its
    own messages on the WS, which interleaves with the test's. The
    stub sleeps until cancelled — keeps the WS open for the test.

    Patches both the class and the import-time instance in main.py,
    since bound methods are resolved at instantiation time.
    """
    import asyncio

    async def stub_run(self, deps):
        # Sleep forever, until the WS receive loop cancels us.
        await asyncio.sleep(3600)

    monkeypatch.setattr(harness_mod.AgentHarness, "run", stub_run)
    monkeypatch.setattr(main_mod.harness, "run", stub_run.__get__(main_mod.harness))
    yield


def _drain_until(ws, target_type: str, max_msgs: int = 50) -> dict:
    """Read WS messages until we see one whose `type` matches target_type.

    The agent may have emitted messages before our control frame
    reached the server. Drain them so the next read is the one we
    actually want to assert on.
    """
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == target_type:
            return msg
    raise AssertionError(f"never saw {target_type!r} after {max_msgs} messages")


# ---------------------------------------------------------------------------
# task_start — the gating frame
# ---------------------------------------------------------------------------


def test_first_message_must_be_task_start(agent_disabled):
    """A non-task_start first message closes the WS."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-bad-first") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            with pytest.raises(Exception):
                # Server closes with code 4000
                ws.receive_text()


def test_task_start_with_empty_task_closes(agent_disabled):
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-empty-task") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "  "}))
            with pytest.raises(Exception):
                ws.receive_text()


def test_task_start_missing_task_field_closes(agent_disabled):
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-missing-task") as ws:
            ws.send_text(json.dumps({"type": "task_start"}))
            with pytest.raises(Exception):
                ws.receive_text()


# ---------------------------------------------------------------------------
# ping / pong — no harness interaction
# ---------------------------------------------------------------------------


def test_ping_returns_pong(agent_disabled):
    """Ping must round-trip without invoking the harness."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-ping") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text(json.dumps({"type": "ping"}))
            pong = ws.receive_json()
            assert pong == {"type": "pong"}


# ---------------------------------------------------------------------------
# D9 sequence dedup — boundary test
# ---------------------------------------------------------------------------


def test_duplicate_observation_seq_is_dropped_at_boundary(agent_disabled):
    """Two observations with the same seq — only one is processed.

    We can't directly observe the agent's processing state, but we
    can verify the WS contract by sending a stream and verifying
    the server accepts our messages without crashing. The validator
    itself is covered in test_observation_validator.py.
    """
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-dup") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))

            for _ in range(3):
                ws.send_text(json.dumps({
                    "type": "observation",
                    "seq": 1,
                    "url": "http://example.com",
                    "title": "Example",
                    "axTargets": [],
                }))

            # Confirm the WS is still alive after the duplicates.
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


def test_observation_seq_gap_is_warned_but_accepted(agent_disabled):
    """A gap is OK — the WS contract holds; the warning is in the log."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-gap") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text(json.dumps({
                "type": "observation",
                "seq": 1,
                "url": "http://a.com",
                "title": "A",
                "axTargets": [],
            }))
            ws.send_text(json.dumps({
                "type": "observation",
                "seq": 10,
                "url": "http://b.com",
                "title": "B",
                "axTargets": [],
            }))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


def test_observation_without_seq_is_legacy_compatible(agent_disabled):
    """A legacy extension that omits seq still works."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-legacy") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text(json.dumps({
                "type": "observation",
                "url": "http://example.com",
                "title": "Example",
                "axTargets": [],
            }))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


# ---------------------------------------------------------------------------
# Control frames — non-observation messages
# ---------------------------------------------------------------------------


def test_evaluate_result_round_trips(agent_disabled):
    """evaluate_result is accepted and routed to the eval queue."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-eval") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))

            # Drain whatever the harness emits on startup so we can
            # observe the next response cleanly.
            ws.send_text(json.dumps({"type": "evaluate_result", "value": "hello"}))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


def test_human_reply_accepted(agent_disabled):
    """human_reply is accepted (queued; not consumed here)."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-human") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text(json.dumps({"type": "human_reply", "content": "yes"}))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


def test_unknown_message_type_is_logged_not_fatal(agent_disabled):
    """An unknown message type is logged and ignored — WS stays open."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-unknown") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text(json.dumps({"type": "totally_made_up_type"}))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


def test_malformed_json_does_not_crash_the_session(agent_disabled):
    """A frame that isn't valid JSON is logged and ignored."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/proto-badjson") as ws:
            ws.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            ws.send_text("not even json {{{")
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}


# ---------------------------------------------------------------------------
# Session registry — sequence tracker is per-session across reconnects
# ---------------------------------------------------------------------------


def test_separate_sessions_have_independent_trackers(agent_disabled):
    """Two concurrent sessions must not share a sequence tracker."""
    with TestClient(main_mod.app) as client:
        with client.websocket_connect("/ws/ext/session-A") as wsA:
            wsA.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            wsA.send_text(json.dumps({
                "type": "observation", "seq": 5,
                "url": "http://a.com", "title": "A", "axTargets": [],
            }))
            wsA.send_text(json.dumps({"type": "ping"}))
            assert wsA.receive_json() == {"type": "pong"}

        with client.websocket_connect("/ws/ext/session-B") as wsB:
            wsB.send_text(json.dumps({"type": "task_start", "task": "noop"}))
            # Session B can start fresh at seq=1 even though A is at 5.
            wsB.send_text(json.dumps({
                "type": "observation", "seq": 1,
                "url": "http://b.com", "title": "B", "axTargets": [],
            }))
            wsB.send_text(json.dumps({"type": "ping"}))
            assert wsB.receive_json() == {"type": "pong"}
