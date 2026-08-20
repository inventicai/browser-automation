from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel


class StepSummary(BaseModel):
    step: int
    url: str
    action_taken: str
    outcome: str
    extracted: str | None = None


class MemoryEntry(BaseModel):
    """One read_page_text result, captured automatically.

    Lives in Scratchpad.entries. The agent sees the manifest in every step
    (a small digest per entry) and recalls the full body via the
    recall_memory action. The body is the raw text returned by the CDP;
    the digest is the first ~200 chars — small enough to fit many entries
    in the prompt without bloating it.
    """
    id: str
    step: int
    selector: str
    around: str | None
    digest: str
    body: str
    was_truncated: bool


DIGEST_LEN = 200


class Scratchpad(BaseModel):
    """Long-term memory. Two parts:

    - entries: every read_page_text result, captured automatically by code.
      The agent sees the digest (small) in every step's prompt; the full body
      is loaded on demand via recall_memory.
    - notes: agent-synthesized free-form text. The agent writes high-level
      findings, decisions, sub-question answers. This is the "narrative" the
      agent curates on top of the raw reads.

    No hard cap on either — sized for complex multi-step tasks. The
    manifest is small; the bodies are loaded on demand.
    """
    entries: list[MemoryEntry] = field(default_factory=list)
    notes: str = ""

    def with_entry(self, entry: MemoryEntry) -> "Scratchpad":
        return Scratchpad(
            entries=self.entries + [entry],
            notes=self.notes,
        )

    def lookup(self, entry_id: str) -> MemoryEntry | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def append_note(self, line: str) -> "Scratchpad":
        if not line:
            return self
        if self.notes:
            return Scratchpad(entries=self.entries, notes=(self.notes + "\n" + line).strip())
        return Scratchpad(entries=self.entries, notes=line.strip())

    def write_notes(self, content: str) -> "Scratchpad":
        return Scratchpad(entries=self.entries, notes=content)


class AgentTurn(BaseModel):
    task: str
    step_number: int
    scratchpad_notes: str
    scratchpad_entries: list[MemoryEntry]
    current_url: str
    current_page_title: str
    ax_tree: str
    ax_diff: str
    step_summaries: list[StepSummary]


class ActionCall(BaseModel):
    """One action in a multi-action decision. The agent may emit several of
    these per step (e.g. click + append_scratchpad)."""
    action: Literal[
        "navigate", "click", "type_text", "scroll",
        "find_element", "read_page_text",
        "write_scratchpad", "append_scratchpad", "read_scratchpad", "recall_memory",
        "task_complete", "cannot_complete", "ask_human",
    ]
    action_args: dict


class AgentDecision(BaseModel):
    reasoning: str
    thought: str
    actions: list[ActionCall]


class TaskResult(BaseModel):
    status: Literal["completed", "failed", "awaiting_human", "stagnated"]
    summary: str
    extracted_data: dict | None = None
    steps_taken: int = 0
    failure_reason: str | None = None
    tried: list[str] = field(default_factory=list)
    timing: dict | None = None  # per-component seconds + wall clock, set by harness


@dataclass
class AgentDeps:
    user_id: str
    task: str
    cdp: object  # CDPRelay
    ws_send: object  # async callable: (dict) -> None
    task_id: str = ""  # set by harness for run logging
    human_input_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    scratchpad: Scratchpad = field(default_factory=Scratchpad)
    step_summaries: list[StepSummary] = field(default_factory=list)
    step_number: int = 0
    result: TaskResult | None = None
    prev_targets: list = field(default_factory=list)  # AX targets from previous step for diffing
