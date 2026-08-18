"""Benchmark task spec and result types.

A task is a single (goal, start_url, success_check) triple. The
runner drives the harness against the start_url, the agent works
toward the goal, and the success_check decides pass/fail.

Success checks are deterministic — no LLM-as-judge. If you can't
write a Python check for the task, the task isn't benchmark-suitable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass(frozen=True)
class TaskSpec:
    """A single benchmark task.

    `name` is the slug used in JSONL output and the public card.
    `goal` is the natural-language task given to the agent.
    `start_url` is where the harness navigates to.
    `success_check` is an async callable that takes the harness
    state and returns True for pass.
    `max_steps` caps the agent iteration count.
    """

    name: str
    goal: str
    start_url: str
    success_check: Callable[["RunState"], Awaitable[bool]]
    max_steps: int = 8
    requires_approval: bool = False


@dataclass
class RunState:
    """State available to the success check at the end of a run.

    `extracted_data` is whatever the agent's terminal action emitted
    (typically task_complete's action_args.extracted_data). The
    success check is free to inspect page text, the URL, the
    extracted payload, or any combination.
    """

    final_url: str = ""
    extracted_data: Any = None
    scratchpad: str = ""
    steps_taken: int = 0
    approval_was_requested: bool = False


@dataclass
class TaskResult:
    """JSONL row. One per (task, model) run."""

    timestamp: str
    task: str
    model: str
    ok: bool
    steps: int
    tokens: int
    elapsed_ms: int
    error: str | None = None
    extracted: Any = None


__all__ = ["TaskSpec", "RunState", "TaskResult"]
