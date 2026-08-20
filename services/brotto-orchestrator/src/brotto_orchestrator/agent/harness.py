"""Agent harness: observe → plan → act loop with guardrails and stagnation detection."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Callable, Coroutine, Any

import logging

from pydantic_ai import Agent
from pydantic_ai.exceptions import UserError

from .context import (
    AgentDeps, AgentDecision, AgentTurn, ActionCall,
    StepSummary, TaskResult, Scratchpad, MemoryEntry, DIGEST_LEN,
)
from .ax_filter import filter_ax_targets
from .ax_diff import compute_ax_diff
from .stagnation import check_stagnation
from .guardrails import check_login_page, check_critical_action
from .prompt import SYSTEM_PROMPT
from .run_logger import RunLogger

_HISTORY_WINDOW = 12  # keep first 3 + last 9 steps in prompt

# Actions that don't fire a UI bubble. Scratchpad mutations and recall are
# metadata — the user sees the thought, not the write/recall itself.
_INTERNAL_ACTIONS = {
    "write_scratchpad", "append_scratchpad", "read_scratchpad",
    "recall_memory",
}
# Actions that short-circuit the rest of the multi-action list.
_TERMINAL_ACTIONS = {"task_complete", "cannot_complete"}

log = logging.getLogger("brotto.harness")

# Component-timing buckets. Each step records how long each phase took.
# Reported at task end so we can see where wall time actually goes.
TIMING_BUCKETS = (
    "observe",          # CDP observation round-trip (get_targets/url/title)
    "filter",           # AX filter + diff computation
    "login_pause",      # ws_send(login_required) + queue wait for resume
    "stagnation",       # stagnation check
    "model_plan",       # agent.run — the LLM call
    "approval_pause",   # ws_send(approval_required) + queue wait
    "execute",          # _execute_actions (CDP actions + post-obs)
    "ws_send_progress", # step_progress notifications
)

_MODEL = os.getenv("AGENT_MODEL", "no-model")
# Context window size (tokens) used for the side panel's CONTEXT cell
# (% of context used). Override per model in .env. Defaults to 400k.
_CONTEXT_WINDOW_TOKENS = int(os.getenv("CONTEXT_WINDOW_TOKENS", "400000"))


def _build_context(tokens: int | None) -> dict:
    """Build the context payload the side panel renders.

    The cell shows `pct` (and tooltip `tokens` / `window`) — all math
    lives here so the frontend is a dumb display. `tokens` may be None
    when the model hasn't been called yet (e.g. before step 1); we
    return null pct so the cell shows "0%" via the frontend's
    null-tokens branch.
    """
    if tokens is None or tokens < 0:
        return {"tokens": None, "window": _CONTEXT_WINDOW_TOKENS, "pct": None}
    pct = round((tokens / _CONTEXT_WINDOW_TOKENS) * 100, 1) if _CONTEXT_WINDOW_TOKENS else 0
    return {"tokens": tokens, "window": _CONTEXT_WINDOW_TOKENS, "pct": pct}


def _build_agent() -> Agent[AgentDeps, AgentDecision]:
    # Pass the raw model id; pydantic-ai auto-detects the provider from the
    # model name. Operators who want explicit routing can set
    # AGENT_MODEL="<provider>:<model>" (e.g. "anthropic:claude-3-5-sonnet").
    # This file names no vendor.
    return Agent(
        _MODEL,
        output_type=AgentDecision,
        deps_type=AgentDeps,
        system_prompt=SYSTEM_PROMPT,
        retries=2,
        defer_model_check=True,
    )


agent = _build_agent()


def _turn_to_prompt(turn: AgentTurn) -> str:
    summaries = turn.step_summaries
    if len(summaries) > _HISTORY_WINDOW:
        shown = summaries[:3] + summaries[-(_HISTORY_WINDOW - 3):]
        skipped = len(summaries) - _HISTORY_WINDOW
    else:
        shown = summaries
        skipped = 0

    history_lines = [
        f"Step {s.step} | {s.url} | {s.action_taken} → {s.outcome}"
        + (f" [extracted: {s.extracted}]" if s.extracted else "")
        for s in shown
    ]
    if skipped:
        history_lines.insert(3, f"  ... {skipped} steps omitted ...")
    history = "\n".join(history_lines) or "(none yet)"

    diff_section = f"\n### What changed after last action\n{turn.ax_diff}\n" if turn.ax_diff else ""

    # Memory manifest: small per-entry digest. Full bodies are loaded on
    # demand via recall_memory(id). This is the "skills" pattern — the
    # agent sees the description (digest) for free, fetches full content
    # only when it actually needs it.
    manifest_lines = ["### Memory manifest (recall_memory(id) fetches full body)"]
    for e in turn.scratchpad_entries:
        around = f" around={e.around!r}" if e.around else ""
        trunc = " [truncated]" if e.was_truncated else ""
        manifest_lines.append(f"- `{e.id}` step={e.step} sel={e.selector}{around}{trunc}: {e.digest}")
    manifest_section = "\n".join(manifest_lines) + "\n"

    return f"""## Task
{turn.task}

## Your memory (notes)
{turn.scratchpad_notes or "(empty — append_scratchpad(line) to add your own findings here)"}

## Memory manifest (auto-captured reads)
{manifest_section}

## Steps completed
{history}

## Current page (step {turn.step_number})
URL: {turn.current_url}
Title: {turn.current_page_title}
{diff_section}
### AX Tree (interactive elements only)
{turn.ax_tree}

## What is your next action(s)?
"""


async def _execute_action(call: ActionCall, deps: AgentDeps) -> str:
    """Execute a single action. Returns outcome string."""
    cdp = deps.cdp
    action = call.action
    args = call.action_args

    try:
        if action == "navigate":
            await cdp.navigate(args["url"])
            await cdp.wait_for_network_idle()
            await cdp.refresh_target_map()
            return f"Navigated to {args['url']}"

        elif action == "click":
            result = await cdp.click_ref(args["ref"])
            await asyncio.sleep(0.5)
            await cdp.refresh_target_map()
            return f"Clicked [{args['ref']}]: {result}"

        elif action == "type_text":
            await cdp.focus_ref(args["ref"])
            await cdp.clear_ref(args["ref"])
            result = await cdp.type_text_to_ref(args["ref"], args["text"])
            return f"Typed into [{args['ref']}]: {result}"

        elif action == "scroll":
            direction = args.get("direction", "down")
            amount = args.get("amount_px", 300)
            await cdp.scroll(direction, amount)
            await cdp.refresh_target_map()
            return f"Scrolled {direction}"

        elif action == "read_page_text":
            selector = args.get("selector", "body")
            max_chars = args.get("max_chars", 2000)
            around = args.get("around")
            text = await cdp.read_page_text(selector, max_chars=max_chars, around=around)
            # Heuristic: if the returned text is near the cap, the page was
            # bigger than we saw. The agent can use this to decide whether
            # to read again with `around` set.
            was_truncated = len(text) >= max_chars - 16
            # Auto-capture: every read lands in memory. Zero tokens. The
            # agent sees the manifest in the next step's prompt and can
            # recall this entry's full body via recall_memory(id).
            entry_id = f"r{len(deps.scratchpad.entries) + 1}"
            digest_body = text[:DIGEST_LEN]
            digest = digest_body + ("…" if len(text) > DIGEST_LEN else "")
            deps.scratchpad = deps.scratchpad.with_entry(MemoryEntry(
                id=entry_id,
                step=deps.step_number,
                selector=selector,
                around=around,
                digest=digest,
                body=text,
                was_truncated=was_truncated,
            ))
            around_note = f" around={around!r}" if around else ""
            return (
                f"read_page_text({selector!r}{around_note}, max_chars={max_chars}) "
                f"→ {len(text)} chars. Auto-captured as {entry_id} in memory. "
                f"Use recall_memory('{entry_id}') for full body."
            )

        elif action == "find_element":
            targets = await cdp.get_targets()
            desc = args.get("description", "").lower()
            # Search all targets including generic-role elements (e.g. score spans, badges)
            scored: list[tuple[int, object]] = []
            for t in targets:
                name_text = (t.name or "").lower()
                value_text = str(t.value or "").lower()
                combined = f"{t.role} {name_text} {value_text}"
                # Prioritise: all words present > any word present
                words = desc.split()
                all_match = all(w in combined for w in words)
                any_match = any(w in combined for w in words)
                if all_match:
                    scored.append((2, t))
                elif any_match:
                    scored.append((1, t))
            if scored:
                scored.sort(key=lambda x: -x[0])
                t = scored[0][1]
                return f"Found: [{t.ref_id}] {t.role} '{t.name}' value='{t.value}'"
            return f"Element matching '{desc}' not found in {len(targets)} targets"

        elif action == "append_scratchpad":
            deps.scratchpad = deps.scratchpad.append_note(args.get("line", ""))
            return "Memory note appended"

        elif action == "write_scratchpad":
            deps.scratchpad = deps.scratchpad.write_notes(args.get("content", ""))
            return "Memory notes rewritten"

        elif action == "read_scratchpad":
            # Returns the manifest + notes as a single blob so the agent
            # can see everything in one call. (recall_memory is the
            # token-efficient path — call this only when you need a
            # full dump.)
            lines = []
            if deps.scratchpad.entries:
                lines.append("### Memory manifest")
                for e in deps.scratchpad.entries:
                    lines.append(f"- `{e.id}` step={e.step}: {e.digest}")
            if deps.scratchpad.notes:
                lines.append("### Notes")
                lines.append(deps.scratchpad.notes)
            return "\n".join(lines) or "(empty)"

        elif action == "recall_memory":
            entry_id = args.get("entry_id", "")
            entry = deps.scratchpad.lookup(entry_id)
            if entry is None:
                available = [e.id for e in deps.scratchpad.entries]
                return f"Memory entry {entry_id!r} not found. Available: {available}"
            return entry.body

        elif action == "task_complete":
            deps.result = TaskResult(
                status="completed",
                summary=args.get("summary", ""),
                extracted_data=args.get("extracted_data"),
                steps_taken=deps.step_number,
            )
            return "Task complete"

        elif action == "cannot_complete":
            deps.result = TaskResult(
                status="failed",
                summary=args.get("reason", ""),
                failure_reason=args.get("reason"),
                tried=args.get("tried", []),
                steps_taken=deps.step_number,
            )
            return "Marked as cannot complete"

        elif action == "ask_human":
            question = args.get("question", "")
            await deps.ws_send({"type": "ask_human", "question": question})
            reply = await deps.human_input_queue.get()
            return f"User replied: {reply}"

        else:
            return f"Unknown action: {action}"

    except Exception as e:
        return f"Error executing {action}: {e}"


class AgentHarness:
    MAX_STEPS = 30
    STAGNATION_WINDOW = 3

    async def run(self, deps: AgentDeps) -> TaskResult:
        timings: dict[str, float] = {b: 0.0 for b in TIMING_BUCKETS}
        # Snapshot of `timings` taken at the start of each step iteration —
        # lets us report a per-step breakdown without instrumenting every
        # early-exit (continue) site in the loop.
        cumulative_snapshots: list[dict[str, float]] = []
        steps_run = 0
        task_start = time.perf_counter()

        if not await deps.cdp.ping():
            return TaskResult(
                status="failed",
                summary="CDP not healthy at task start",
                failure_reason="cdp_preflight_failed",
            )

        if not deps.task_id:
            deps.task_id = str(uuid.uuid4())
        run_log = RunLogger(deps.task_id)

        # Restore scratchpad if this task was previously interrupted.
        # load_scratchpad returns a structured Scratchpad (entries + notes).
        # Legacy plain-text files (no # MEMORY v2 header) parse as notes-only.
        loaded = run_log.load_scratchpad()
        if loaded.entries or loaded.notes:
            deps.scratchpad = loaded

        for step in range(self.MAX_STEPS):
            deps.step_number = step
            log.info("[%s] === step %d ===", deps.user_id, step)
            steps_run += 1
            cumulative_snapshots.append(dict(timings))

            # Observe
            t0 = time.perf_counter()
            targets = await deps.cdp.get_targets()
            current_url = await deps.cdp.get_current_url()
            page_title = await deps.cdp.get_page_title()
            t1 = time.perf_counter()
            timings["observe"] += t1 - t0

            filtered_ax = filter_ax_targets(targets)
            ax_diff = compute_ax_diff(deps.prev_targets, targets)
            timings["filter"] += time.perf_counter() - t1

            # Guardrail: login detection
            if check_login_page(page_title, filtered_ax, current_url):
                t_lp = time.perf_counter()
                await deps.ws_send({
                    "type": "login_required",
                    "message": f"Please log in: {page_title}. Agent will continue when ready.",
                })
                try:
                    reply = await asyncio.wait_for(
                        deps.human_input_queue.get(), timeout=300,
                    )
                except asyncio.TimeoutError:
                    await deps.ws_send({"type": "login_timeout"})
                    timings["login_pause"] += time.perf_counter() - t_lp
                    continue
                if str(reply).lower() == "skip":
                    timings["login_pause"] += time.perf_counter() - t_lp
                    timing_report = self._log_timings(deps.user_id, timings, steps_run, time.perf_counter() - task_start, cumulative_snapshots)
                    return TaskResult(
                        status="failed",
                        summary="User skipped login",
                        failure_reason="user_skipped_login",
                        timing=timing_report,
                    )
                # reply == "resume" (or anything else): loop continues,
                # next step re-runs check_login_page to confirm we're out.
                timings["login_pause"] += time.perf_counter() - t_lp
                continue

            # Stagnation check
            t_sg = time.perf_counter()
            stagnated, reason = check_stagnation(deps.step_summaries, self.STAGNATION_WINDOW)
            if stagnated:
                log.warning("[%s] stagnation detected: %s", deps.user_id, reason)
                await deps.ws_send({"type": "stagnation_warning", "reason": reason})
            timings["stagnation"] += time.perf_counter() - t_sg
            stagnation_note = (
                f"\n\n⚠ STAGNATION DETECTED: {reason}\nYou MUST either try a completely different approach or call cannot_complete now."
                if stagnated else ""
            )

            # Build turn
            turn = AgentTurn(
                task=deps.task,
                step_number=step,
                scratchpad_notes=deps.scratchpad.notes,
                scratchpad_entries=list(deps.scratchpad.entries),  # manifest snapshot
                current_url=current_url,
                current_page_title=page_title,
                ax_tree=filtered_ax + stagnation_note,
                ax_diff=ax_diff,
                step_summaries=deps.step_summaries,
            )

            log.info("[%s] step %d  url=%s  ax_elements=%d  memory_entries=%d",
                     deps.user_id, step, current_url[:80], len(targets), len(turn.scratchpad_entries))

            # Plan
            t_plan = time.perf_counter()
            log.debug("[%s] calling model...", deps.user_id)
            try:
                result = await agent.run(_turn_to_prompt(turn), deps=deps)
                decision: AgentDecision = result.output
            except UserError as e:
                # pydantic-ai auto-detect fails on bare model names that don't
                # match its known patterns. With defer_model_check=True the
                # check fires here, not at Agent construction. Re-raise with
                # a hint that names the fix without hard-coding a model id.
                if "Unknown model" in str(e):
                    raise UserError(
                        f"{e}. Set AGENT_MODEL to '<provider>:<model>' "
                        f"to route to the correct provider."
                    ) from e
                raise
            timings["model_plan"] += time.perf_counter() - t_plan
            actions_summary = ", ".join(f"{c.action}" for c in decision.actions) or "(none)"
            log.info("[%s] step %d  actions=[%s]", deps.user_id, step, actions_summary)

            # Guardrail: critical action approval (check ALL actions in the
            # batch — checking only the first was a bypass: `click(delete) +
            # append_scratchpad` would only see the first critical action,
            # and if the model put a non-critical action first, critical
            # actions later in the batch ran unchecked). One approval per
            # critical action; deny aborts the entire batch.
            t_ap = time.perf_counter()
            critical_actions = [
                c for c in decision.actions
                if check_critical_action(c.action, c.action_args)
            ]
            blocked = False
            for c in critical_actions:
                await deps.ws_send({
                    "type": "approval_required",
                    "action": c.action,
                    "args": c.action_args,
                    "reasoning": decision.reasoning,
                })
                reply = await deps.human_input_queue.get()
                if str(reply).lower() not in ("yes", "y", "approve", "ok", "confirm"):
                    deps.step_summaries.append(StepSummary(
                        step=step, url=current_url,
                        action_taken=f"[BLOCKED] {c.action}",
                        outcome="User denied approval",
                    ))
                    blocked = True
                    break
            timings["approval_pause"] += time.perf_counter() - t_ap
            if blocked:
                continue

            # Stream progress — one bubble per decision. The full action list
            # ships in the `actions` array so the side panel can render all
            # tool calls under the "details" toggle. The lead action is also
            # echoed at the top level for the icon + chip. Internal actions
            # (scratchpad) are still silent — they're metadata, not tool calls
            # the user sees.
            #
            # ponytail: actual `result.usage` from pydantic-ai (the model
            # provider's reported token count, not a `len(prompt) // 4`
            # approximation). The backend computes the percentage so the
            # frontend is a dumb display. `usage` is a property, not a method.
            t_ws = time.perf_counter()
            try:
                usage = result.usage
                tokens_used = usage.input_tokens if usage else None
            except Exception:
                tokens_used = None
            context = _build_context(tokens_used)
            external = [c for c in decision.actions if c.action not in _INTERNAL_ACTIONS]
            if external:
                actions_payload = [
                    {
                        "action": c.action,
                        "action_target": c.action_args.get("url") if c.action == "navigate" else None,
                        "args": c.action_args,
                    }
                    for c in external
                ]
                lead = external[0]
                await deps.ws_send({
                    "type": "step_progress",
                    "step": step,
                    "action": lead.action,
                    "action_target": lead.action_args.get("url") if lead.action == "navigate" else None,
                    "actions": actions_payload,
                    "thought": decision.thought,
                    "url": current_url,
                    "context": context,
                })
            else:
                # ponytail: no external actions this step (e.g. a
                # scratchpad-only step). Still emit context so the sidepanel
                # utilization % updates on every step.
                await deps.ws_send({
                    "type": "context_update",
                    "context": context,
                })
            timings["ws_send_progress"] += time.perf_counter() - t_ws

            # Execute
            t_ex = time.perf_counter()
            outcomes: list[str] = []
            action_trace: list[str] = []
            for call in decision.actions:
                action_trace.append(f"{call.action}({call.action_args})")
                outcome = await _execute_action(call, deps)
                outcomes.append(outcome)
                # Short-circuit the rest of the batch on a terminal action
                # (task_complete/cannot_complete — sets deps.result) or on
                # ask_human (pauses for user input; any action after it in
                # the same batch would run before the user could see the
                # question, which is the wrong order).
                if call.action in _TERMINAL_ACTIONS or call.action == "ask_human":
                    break
            timings["execute"] += time.perf_counter() - t_ex
            combined_outcome = "; ".join(outcomes) if outcomes else "no action"

            # Save targets for next-step diff
            deps.prev_targets = targets

            # Persist the full structured memory whenever any step touched
            # it: read_page_text (auto-capture), append_scratchpad /
            # write_scratchpad (synthesized notes). The file is the
            # source of truth — operators can inspect
            # logs/runs/<task_id>/scratchpad.txt to see what memory was
            # built. Auto-append writes the digest; the full body lives
            # only in-memory and is lost on restart.
            memory_actions = {
                "read_page_text", "write_scratchpad", "append_scratchpad",
            }
            if any(c.action in memory_actions for c in decision.actions):
                run_log.save_scratchpad(deps.scratchpad)

            # Log step
            run_log.log_step(
                step=step,
                url=current_url,
                action=action_trace[0] if action_trace else "no-op",
                args=decision.actions[0].action_args if decision.actions else {},
                reasoning=decision.reasoning,
                thought=decision.thought,
                outcome=combined_outcome,
            )

            # Record
            deps.step_summaries.append(StepSummary(
                step=step,
                url=current_url,
                action_taken="; ".join(action_trace) if action_trace else "no action",
                outcome=combined_outcome[:120],
            ))

            # Terminal? Gate on deps.result, not on the action name. A
            # terminal action that raises an exception before setting
            # deps.result should not try to read .timing off a None.
            if deps.result is not None:
                deps.result.timing = self._log_timings(
                    deps.user_id, timings, steps_run, time.perf_counter() - task_start, cumulative_snapshots,
                )
                return deps.result

        timing_report = self._log_timings(
            deps.user_id, timings, steps_run, time.perf_counter() - task_start, cumulative_snapshots,
        )
        return TaskResult(
            status="failed",
            summary="Max steps reached",
            failure_reason="max_steps_exceeded",
            steps_taken=self.MAX_STEPS,
            timing=timing_report,
        )

    @staticmethod
    def _log_timings(
        user_id: str,
        timings: dict[str, float],
        steps: int,
        wall: float,
        snapshots: list[dict[str, float]] | None = None,
    ) -> dict:
        """Emit a per-component timing summary at task end.

        Returns the dict so the caller can attach it to TaskResult.timing
        (which flows to the side panel via WS task_result).

        Output line shape:
          [brotto.harness] TIMING  user=local  steps=3  wall=5.42s  observe=0.31 ...
        """
        parts = "  ".join(f"{k}={timings[k]:.2f}" for k in TIMING_BUCKETS)
        accounted = sum(timings.values())
        residual = wall - accounted
        log.info(
            "[%s] TIMING  steps=%d  wall=%.2fs  accounted=%.2fs  residual=%.2fs  %s",
            user_id, steps, wall, accounted, residual, parts,
        )

        # Per-step breakdown: diff consecutive snapshots taken at the top of
        # each step iteration. Step N's wall = timings[snap_N+1] - timings[snap_N].
        per_step: list[dict[str, float]] = []
        if snapshots:
            for i in range(len(snapshots) - 1):
                delta = {
                    k: round(snapshots[i + 1][k] - snapshots[i][k], 3)
                    for k in TIMING_BUCKETS
                }
                per_step.append(delta)
            # The final step may have in-flight increments not yet snapshotted
            # if the task ended mid-iteration (e.g. terminal task_complete).
            if len(snapshots) <= steps:
                delta = {
                    k: round(timings[k] - snapshots[-1][k], 3)
                    for k in TIMING_BUCKETS
                }
                per_step.append(delta)

        return {
            "steps": steps,
            "wall_s": round(wall, 3),
            "components": {k: round(timings[k], 3) for k in TIMING_BUCKETS},
            "residual_s": round(residual, 3),
            "per_step": per_step,
        }
