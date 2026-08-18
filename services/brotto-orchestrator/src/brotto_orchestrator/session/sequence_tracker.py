"""D9 sequence tracking.

Extension assigns a monotonic `seq` to every observation message. The
server tracks the highest `seq` it has processed per session and
ignores duplicates. A gap (seq > last + 1) is logged but the
observation is still processed — the alternative is wedging the
session on a missing message that may never arrive.

State is serialised so a session can resume after a process restart
or a WebSocket reconnect.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class SequenceTracker:
    """Tracks the highest seq seen for a single session.

    `seen` counts accepted observations (duplicates and gaps are
    excluded). It is exposed for telemetry, not for correctness.
    """

    last_seq: int = 0
    seen: int = 0

    def observe(self, seq: int) -> str:
        """Record an observation with the given seq.

        Returns one of: "accepted", "duplicate", "gap".
        `seen` increments on accepted AND gap — only duplicates are
        excluded. Telemetry needs to count work actually done.
        """
        if seq <= self.last_seq:
            return "duplicate"
        status = "accepted" if seq == self.last_seq + 1 else "gap"
        self.last_seq = seq
        self.seen += 1
        return status

    @classmethod
    def resume_from(cls, last_seq: int = 0, seen: int = 0) -> "SequenceTracker":
        """Build a tracker from a previously-serialised snapshot."""
        return cls(last_seq=last_seq, seen=seen)

    def to_state(self) -> dict:
        """Serialise for persistence (scratchpad, registry, etc.)."""
        return {"last_seq": self.last_seq, "seen": self.seen}


class OutboundSequence:
    """Monotonic server-side seq for outbound messages to the extension.

    Thread-safe — the agent loop and the WS dispatch loop can race
    when both want to send. Using a lock keeps the seq strictly
    monotonic per session.
    """

    def __init__(self, start: int = 0) -> None:
        self._next = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._next += 1
            return self._next


__all__ = ["SequenceTracker", "OutboundSequence"]
