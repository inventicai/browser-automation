from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .sequence_tracker import SequenceTracker


@dataclass
class SessionState:
    user_id: str
    connected: bool = True
    current_task: asyncio.Task | None = None
    in_seq: SequenceTracker = field(default_factory=SequenceTracker)

    def cancel_current_task(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, user_id: str) -> SessionState:
        if user_id not in self._sessions:
            self._sessions[user_id] = SessionState(user_id=user_id)
        return self._sessions[user_id]

    def get_or_create_in_seq(self, user_id: str) -> SequenceTracker:
        """Return the per-session inbound sequence tracker.

        The tracker is created lazily on first use and persists across
        reconnect attempts for the same session_id. This is what makes
        a reconnection re-attempt safe: the extension can replay
        buffered observations and the server will dedupe them by seq.
        """
        return self.get_or_create(user_id).in_seq

    def mark_disconnected(self, user_id: str) -> None:
        if session := self._sessions.get(user_id):
            session.connected = False
            session.cancel_current_task()
