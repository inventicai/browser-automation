"""Persistent run logging: steps.jsonl + scratchpad.txt per task."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_LOGS_DIR = Path(os.getenv("BROTTO_LOGS_DIR", "logs/runs"))


class RunLogger:
    def __init__(self, task_id: str) -> None:
        self.dir = _LOGS_DIR / task_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._steps_file = self.dir / "steps.jsonl"
        self._scratchpad_file = self.dir / "scratchpad.txt"

    def log_step(self, step: int, url: str, action: str, args: dict, reasoning: str, thought: str, outcome: str) -> None:
        entry = {"step": step, "url": url, "action": action, "args": args, "reasoning": reasoning, "thought": thought, "outcome": outcome}
        with self._steps_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def save_scratchpad(self, content: str) -> None:
        self._scratchpad_file.write_text(content)

    def load_scratchpad(self) -> str:
        if self._scratchpad_file.exists():
            return self._scratchpad_file.read_text()
        return ""
