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


class ReadEntry(BaseModel):
    """One read_page_text result. Last MAX_RECENT_READS are kept in AgentDeps.recent_reads."""
    step: int
    selector: str
    text: str
    was_truncated: bool


class Scratchpad(BaseModel):
    """Long-term working memory. No hard cap — sized for complex multi-step tasks."""
    content: str = ""

    def update(self, new_content: str) -> "Scratchpad":
        return Scratchpad(content=new_content)

    def append(self, line: str) -> "Scratchpad":
        if not line:
            return self
        if self.content:
            return Scratchpad(content=(self.content + "\n" + line).strip())
        return Scratchpad(content=line.strip())


class AgentTurn(BaseModel):
    task: str
    step_number: int
    scratchpad: str
    current_url: str
    current_page_title: str
    ax_tree: str
    ax_diff: str
    recent_reads: list[ReadEntry]  # FIFO window of last MAX_RECENT_READS reads
    step_summaries: list[StepSummary]


class ActionCall(BaseModel):
    """One action in a multi-action decision. The agent may emit several of
    these per step (e.g. click + append_scratchpad)."""
    action: Literal[
        "navigate", "click", "type_text", "scroll",
        "find_element", "read_page_text",
        "write_scratchpad", "append_scratchpad", "read_scratchpad",
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


MAX_RECENT_READS = 5


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
    recent_reads: list[ReadEntry] = field(default_factory=list)  # FIFO window, last MAX_RECENT_READS
