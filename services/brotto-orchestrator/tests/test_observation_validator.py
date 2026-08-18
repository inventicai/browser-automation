"""Tests for the inbound observation validator (D9 seam)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.session.observation_validator import validate_observation  # noqa: E402
from brotto_orchestrator.session.sequence_tracker import SequenceTracker  # noqa: E402


def test_control_frames_bypass_seq_check():
    """Ping, human_reply, evaluate_result do not carry seq."""
    tracker = SequenceTracker()
    for msg_type in ("ping", "human_reply", "evaluate_result", "observation_error"):
        decision = validate_observation({"type": msg_type}, tracker)
        assert decision.accept, f"{msg_type} should be accepted"
        assert decision.reason == "control_frame"


def test_observation_with_seq_is_accepted():
    tracker = SequenceTracker()
    decision = validate_observation(
        {"type": "observation", "seq": 1, "url": "http://x"},
        tracker,
    )
    assert decision.accept
    assert decision.reason == "accepted"
    assert tracker.last_seq == 1


def test_duplicate_observation_is_rejected():
    tracker = SequenceTracker()
    validate_observation({"type": "observation", "seq": 1}, tracker)
    decision = validate_observation({"type": "observation", "seq": 1}, tracker)
    assert not decision.accept
    assert decision.reason == "duplicate"


def test_out_of_order_observation_is_rejected():
    tracker = SequenceTracker()
    validate_observation({"type": "observation", "seq": 5}, tracker)
    decision = validate_observation({"type": "observation", "seq": 3}, tracker)
    assert not decision.accept
    assert decision.reason == "duplicate"


def test_gap_observation_is_accepted_with_warning():
    tracker = SequenceTracker()
    validate_observation({"type": "observation", "seq": 1}, tracker)
    decision = validate_observation({"type": "observation", "seq": 7}, tracker)
    assert decision.accept
    assert decision.reason == "gap"
    assert tracker.last_seq == 7


def test_legacy_observation_without_seq_is_accepted():
    tracker = SequenceTracker()
    decision = validate_observation(
        {"type": "observation", "url": "http://x"},
        tracker,
    )
    assert decision.accept
    assert decision.reason == "legacy_no_seq"


def test_invalid_seq_is_rejected():
    tracker = SequenceTracker()
    for bad in (-1, "string", 1.5, [1, 2]):
        decision = validate_observation(
            {"type": "observation", "seq": bad}, tracker,
        )
        assert not decision.accept
        assert decision.reason == "invalid_seq"


def test_sequence_round_trip_through_validator():
    """Send a stream — verify the tracker stays consistent."""
    tracker = SequenceTracker()
    seqs = [1, 2, 3, 5, 4, 5, 6]  # 4 is dup, 5 is gap-ok
    accepted = []
    for s in seqs:
        d = validate_observation({"type": "observation", "seq": s}, tracker)
        if d.accept:
            accepted.append(s)
    assert accepted == [1, 2, 3, 5, 6]
    assert tracker.last_seq == 6
