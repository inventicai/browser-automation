"""Persistent run logging: steps.jsonl + scratchpad.txt per task.

The scratchpad file format is plain text with two sections:

    # MEMORY v2
    # MANIFEST
    [r1 step=0 sel=body around=None truncated=False]
    Top 5 repos for suryanshgupta...

    [r2 step=2 sel=article around=Install truncated=False]
    INSTALL: pip install brotto...

    # NOTES
    GOAL: find install command
    Top 5 repos ordered by stars

The manifest is human-readable for inspection. On load, both sections are
restored so the in-memory Scratchpad survives a restart.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .context import MemoryEntry, Scratchpad


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

    def save_scratchpad(self, scratchpad: Scratchpad) -> None:
        """Serialize the structured Scratchpad to plain text."""
        lines = ["# MEMORY v2", ""]
        lines.append("# MANIFEST")
        for e in scratchpad.entries:
            around = e.around if e.around is not None else "None"
            trunc = "True" if e.was_truncated else "False"
            lines.append(
                f"[{e.id} step={e.step} sel={e.selector} around={around} truncated={trunc}]"
            )
            lines.append(e.digest)
            lines.append("")
        lines.append("# NOTES")
        lines.append(scratchpad.notes)
        self._scratchpad_file.write_text("\n".join(lines))

    def load_scratchpad(self) -> Scratchpad:
        """Parse the structured file. Returns an empty Scratchpad on legacy
        plain-text files (no header) — the run continues without entries.
        """
        if not self._scratchpad_file.exists():
            return Scratchpad()
        content = self._scratchpad_file.read_text()
        if not content.startswith("# MEMORY v2"):
            # Legacy plain text — treat as notes only, no entries.
            return Scratchpad(notes=content.strip())
        entries: list[MemoryEntry] = []
        notes_lines: list[str] = []
        in_notes = False
        current_entry_lines: list[str] = []
        current_header: dict[str, str] | None = None

        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if in_notes:
                notes_lines.append(line)
                continue
            if line.startswith("# NOTES"):
                in_notes = True
                continue
            if line.startswith("# MANIFEST") or line == "# MEMORY v2" or line == "":
                continue
            m = re.match(r"^\[(r\d+)\s+step=(\d+)\s+sel=([^\s]+)\s+around=(\S+)\s+truncated=(True|False)\]\s*$", line)
            if m:
                # Flush previous entry
                if current_header is not None:
                    entries.append(MemoryEntry(
                        id=current_header["id"],
                        step=int(current_header["step"]),
                        selector=current_header["sel"],
                        around=None if current_header["around"] == "None" else current_header["around"],
                        digest="\n".join(current_entry_lines).strip(),
                        body="\n".join(current_entry_lines),  # body == digest on reload
                        was_truncated=(current_header["trunc"] == "True"),
                    ))
                current_header = {
                    "id": m.group(1),
                    "step": m.group(2),
                    "sel": m.group(3),
                    "around": m.group(4),
                    "trunc": m.group(5),
                }
                current_entry_lines = []
            else:
                if current_header is not None:
                    current_entry_lines.append(line)

        # Flush last entry
        if current_header is not None:
            entries.append(MemoryEntry(
                id=current_header["id"],
                step=int(current_header["step"]),
                selector=current_header["sel"],
                around=None if current_header["around"] == "None" else current_header["around"],
                digest="\n".join(current_entry_lines).strip(),
                body="\n".join(current_entry_lines),
                was_truncated=(current_header["trunc"] == "True"),
            ))

        return Scratchpad(entries=entries, notes="\n".join(notes_lines).strip())
