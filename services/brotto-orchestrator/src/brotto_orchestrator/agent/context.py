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


class Scratchpad(BaseModel):
    content: str = ""

    def update(self, new_content: str) -> "Scratchpad":
        return Scratchpad(content=new_content[:3200])


class AgentTurn(BaseModel):
    task: str
    step_number: int
    scratchpad: str
    current_url: str
    current_page_title: str
    ax_tree: str
    ax_diff: str
    last_read_text: str   # result of last read_page_text, empty if none
    last_read_selector: str
    step_summaries: list[StepSummary]


class AgentDecision(BaseModel):
    reasoning: str  # internal chain-of-thought — logged only, never shown to user
    thought: str    # one sentence shown live in the side panel — no internals, no jargon
    action: Literal[
        "navigate", "click", "type_text", "scroll",
        "find_element", "read_page_text", "write_scratchpad", "read_scratchpad",
        "task_complete", "cannot_complete", "ask_human",
    ]
    action_args: dict
    scratchpad_update: str | None = None


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
    last_read_text: str = ""          # last read_page_text result, shown in next turn
    last_read_selector: str = ""      # selector used for that read
