"""Tests for session-level state preservation across reconnects.

The registry is the only place that survives a WS disconnect. The
tracker, scratchpad, and reconnect window live here so a reconnect
within the same session_id picks up where the previous connection
left off.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.session.registry import SessionRegistry  # noqa: E402


def test_registry_returns_same_tracker_for_same_session():
    """Same session_id → same SequenceTracker across reconnects."""
    reg = SessionRegistry()
    t1 = reg.get_or_create_in_seq("alice")
    t1.observe(seq=5)
    t2 = reg.get_or_create_in_seq("alice")
    assert t2.last_seq == 5


def test_registry_returns_distinct_trackers_per_session():
    reg = SessionRegistry()
    tA = reg.get_or_create_in_seq("alice")
    tA.observe(seq=5)
    tB = reg.get_or_create_in_seq("bob")
    assert tB.last_seq == 0


def test_reconnect_preserves_in_seq():
    """Simulate a disconnect + reconnect: tracker state survives."""
    reg = SessionRegistry()

    # First connection
    t1 = reg.get_or_create_in_seq("alice")
    t1.observe(seq=1)
    t1.observe(seq=2)
    t1.observe(seq=3)

    # Disconnect (no-op for the registry — the tracker persists)

    # Reconnect
    t2 = reg.get_or_create_in_seq("alice")
    assert t2.last_seq == 3

    # A duplicate of the last observed seq is rejected
    from brotto_orchestrator.session.observation_validator import (
        validate_observation,
    )

    decision = validate_observation(
        {"type": "observation", "seq": 3}, t2,
    )
    assert not decision.accept
    assert decision.reason == "duplicate"

    # The next seq is accepted
    decision = validate_observation(
        {"type": "observation", "seq": 4}, t2,
    )
    assert decision.accept
    assert t2.last_seq == 4
