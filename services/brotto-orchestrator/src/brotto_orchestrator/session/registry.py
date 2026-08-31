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
    # ponytail: last user_policy the user submitted (via task_start or
    # policy_acknowledged). Used by `GET /v1/policy` to return the merged
    # view the user is actually subject to, not just their local cache.
    # Stored as a raw dict; we re-validate with UserPolicy when reading.
    last_user_policy: dict | None = None

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

    def set_user_policy(self, user_id: str, payload: dict | None) -> None:
        """Stash the most-recent user_policy for this session. None clears."""
        session = self.get_or_create(user_id)
        session.last_user_policy = payload

    def get_user_policy_payload(self, user_id: str) -> dict | None:
        session = self._sessions.get(user_id)
        if session is None:
            return None
        return session.last_user_policy

    def hydrate_user_policies(self, payload_by_key: dict) -> int:
        """Seed the in-memory cache from a persisted dump (e.g. JSON
        files written by `policy.persist`). Returns the count loaded so
        callers can log it on startup.

        ponytail: keys in the dump are the same opaque identifiers the
        sidepanel uses in its `user_id` query param. If the format
        diverges, this is the place to remap.
        """
        loaded = 0
        for key, payload in payload_by_key.items():
            self.set_user_policy(key, payload)
            loaded += 1
        return loaded

    def mark_disconnected(self, user_id: str) -> None:
        if session := self._sessions.get(user_id):
            session.connected = False
            session.cancel_current_task()
