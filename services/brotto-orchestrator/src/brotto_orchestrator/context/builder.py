"""Prompt builder — composes the system prompt + per-turn context.

Pure functions. No PydanticAI / FastAPI imports.
Mirrors TS services/brotto-orchestrator/src/context/render.ts + the
harness's composeSystemPrompt + buildContext.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
You are a Brotto browser automation agent. Your job is to make the user's
goal happen on a real Chrome browser.

RULES:
- Observe the page carefully before acting.
- Use the available tools (left_click, type, navigate, etc.) one at a time.
- Each tool call represents one browser action.
- When the goal is achieved, call the `terminate` action with a final answer.
- When you cannot proceed, call `terminate` with a reason.
- Never invoke raw JavaScript, raw CDP, or any action outside the tool list.
- If a tool returns ok=false, look at the evidence and adapt your next move.
- Cite any data you put into memory with the snapshot_id where you saw it.
"""


def compose_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_context(
    *,
    observation: dict[str, Any],
    history: list[dict[str, Any]],
    memory: dict[str, Any],
    goal: str,
) -> str:
    parts: list[str] = [f"GOAL: {goal}", "", "OBSERVATION:"]
    parts.append(_fmt_obs(observation))
    parts.append("")
    parts.append("HISTORY:")
    for h in history[-10:]:
        step_str = f"step {h.get('index', '?')} {h.get('type', '?')} -> {h.get('result', '?')}"
        parts.append(f"  {step_str}")
    parts.append("")
    parts.append("MEMORY:")
    if memory:
        for k, v in memory.items():
            parts.append(f"  {k} = {v}")
    else:
        parts.append("  (empty)")
    return "\n".join(parts)


def _fmt_obs(obs: dict[str, Any]) -> str:
    """Format observation for agent context.

    Per Decision D4: Structured observation with targets + screenshot reference.
    """
    url = obs.get("url", "")
    title = obs.get("title", "")
    targets = obs.get("semantic_targets", [])

    lines = [f"  url: {url}", f"  title: {title}"]

    if targets:
        # Cap at 25 targets to keep context size manageable
        display_targets = targets[:25]
        lines.append(f"  interactive targets ({len(display_targets)}/{len(targets)}):")

        for t in display_targets:
            ref = t.get("ref_id", "?")
            tag = t.get("tag", "?")
            role = t.get("role", "")
            name = t.get("name", "")
            coords = t.get("coordinates", {})

            # Format target line: [ref_id] role "name" @ (x, y)
            coord_str = ""
            if coords and "x" in coords and "y" in coords:
                coord_str = f" @ ({coords['x']}, {coords['y']})"

            role_str = f" ({role})" if role else ""
            name_str = f' "{name}"' if name else ""

            lines.append(f"    [{ref}] {tag}{role_str}{name_str}{coord_str}")

    return "\n".join(lines)
