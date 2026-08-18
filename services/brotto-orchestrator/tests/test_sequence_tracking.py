"""Tests for D9 sequence tracking + reconnection state preservation.

The contract:
- Extension assigns a monotonic `seq` to every observation.
- Server tracks the highest `seq` it has processed per session.
- Observations with `seq <= last_seq` are duplicates and MUST be dropped.
- A gap (`seq > last_seq + 1`) is logged but the message is still processed.
- Session state (history, scratchpad, last_seq) survives a WS reconnect.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.session.sequence_tracker import SequenceTracker  # noqa: E402


# ---------------------------------------------------------------------------
# SequenceTracker — pure logic, no I/O
# ---------------------------------------------------------------------------


def test_tracker_starts_at_zero():
    t = SequenceTracker()
    assert t.last_seq == 0
    assert t.seen == 0


def test_tracker_accepts_first_observation():
    t = SequenceTracker()
    status = t.observe(seq=1)
    assert status == "accepted"
    assert t.last_seq == 1
    assert t.seen == 1


def test_tracker_rejects_duplicate():
    """A re-sent observation (seq == last_seq) must be dropped."""
    t = SequenceTracker()
    t.observe(seq=1)
    status = t.observe(seq=1)
    assert status == "duplicate"
    assert t.last_seq == 1
    assert t.seen == 1


def test_tracker_rejects_out_of_order():
    """An observation with seq behind the latest must be dropped."""
    t = SequenceTracker()
    t.observe(seq=5)
    status = t.observe(seq=3)
    assert status == "duplicate"
    assert t.last_seq == 5


def test_tracker_logs_gap_but_accepts():
    """A gap (seq > last + 1) is logged but the observation is still processed.

    Rationale: the extension may have skipped a sequence because of an
    in-flight drop. We don't want to wedge the session waiting for a
    missing message that will never come.
    """
    t = SequenceTracker()
    t.observe(seq=1)
    status = t.observe(seq=5)
    assert status == "gap"
    assert t.last_seq == 5
    assert t.seen == 2


def test_tracker_resume_preserves_state():
    """A new tracker seeded with last_seq continues correctly."""
    t = SequenceTracker.resume_from(last_seq=10)
    assert t.last_seq == 10
    assert t.observe(seq=11) == "accepted"
    assert t.observe(seq=11) == "duplicate"
    assert t.observe(seq=9) == "duplicate"


def test_tracker_to_state_roundtrips():
    """State must serialise so it can survive a process restart."""
    t = SequenceTracker()
    t.observe(seq=1)
    t.observe(seq=2)
    snapshot = t.to_state()
    assert snapshot == {"last_seq": 2, "seen": 2}

    t2 = SequenceTracker.resume_from(**snapshot)
    assert t2.last_seq == 2
    assert t2.observe(seq=3) == "accepted"
    assert t2.observe(seq=2) == "duplicate"


# ---------------------------------------------------------------------------
# Wire — the orchestrator assigns seq when sending actions to the extension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_sequence_is_monotonic():
    """Server-side seq for outbound actions must be monotonic per session."""
    from brotto_orchestrator.session.sequence_tracker import OutboundSequence

    out = OutboundSequence()
    seqs = [out.next() for _ in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_outbound_sequence_handles_concurrent_sends():
    """Concurrent callers must each get a unique seq."""
    from brotto_orchestrator.session.sequence_tracker import OutboundSequence

    out = OutboundSequence()
    seqs = await asyncio.gather(*(asyncio.to_thread(out.next) for _ in range(100)))
    assert len(set(seqs)) == 100
    assert max(seqs) == 100
