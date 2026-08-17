"""Agent harness: observe → plan → act loop with guardrails and stagnation detection."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Callable, Coroutine, Any

import logging

from pydantic_ai import Agent

from .context import AgentDeps, AgentDecision, AgentTurn, StepSummary, TaskResult, Scratchpad
from .ax_filter import filter_ax_targets
from .ax_diff import compute_ax_diff
from .stagnation import check_stagnation
from .guardrails import check_login_page, check_critical_action, wait_for_redirect
from .prompt import SYSTEM_PROMPT
from .run_logger import RunLogger

_HISTORY_WINDOW = 12  # keep first 3 + last 9 steps in prompt

log = logging.getLogger("brotto.harness")

_MODEL = os.getenv("AGENT_MODEL", "claude-haiku-4-5-20251001")


def _build_agent() -> Agent[AgentDeps, AgentDecision]:
    provider = "anthropic" if "claude" in _MODEL.lower() else "openai"
    model_str = f"{provider}:{_MODEL}"
    return Agent(
        model_str,
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
    read_section = (
        f"\n### Page text read last step (selector: {turn.last_read_selector!r})\n{turn.last_read_text}\n"
        if turn.last_read_text else ""
    )

    return f"""## Task
{turn.task}

## Your scratchpad
{turn.scratchpad or "(empty — write important things here)"}

## Steps completed
{history}

## Current page (step {turn.step_number})
URL: {turn.current_url}
Title: {turn.current_page_title}
{diff_section}{read_section}
### AX Tree (interactive elements only)
{turn.ax_tree}

## What is your next action?
"""


async def _execute_decision(decision: AgentDecision, deps: AgentDeps) -> str:
    """Execute the agent's decision on the browser. Returns outcome string."""
    cdp = deps.cdp
    action = decision.action
    args = decision.action_args

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
            text = await cdp.read_page_text(selector)
            deps.last_read_text = text
            deps.last_read_selector = selector
            preview = text[:120] if text else "(empty)"
            return f"read_page_text({selector!r}) → {len(text)} chars. Content shown in next step context."

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

        elif action == "write_scratchpad":
            deps.scratchpad = deps.scratchpad.update(args.get("content", ""))
            return "Scratchpad updated"

        elif action == "read_scratchpad":
            return deps.scratchpad.content or "(empty)"

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
        if not await deps.cdp.ping():
            return TaskResult(
                status="failed",
                summary="CDP not healthy at task start",
                failure_reason="cdp_preflight_failed",
            )

        if not deps.task_id:
            deps.task_id = str(uuid.uuid4())
        run_log = RunLogger(deps.task_id)

        # Restore scratchpad if this task was previously interrupted
        saved = run_log.load_scratchpad()
        if saved:
            deps.scratchpad = deps.scratchpad.update(saved)

        for step in range(self.MAX_STEPS):
            deps.step_number = step
            log.info("[%s] === step %d ===", deps.user_id, step)

            # Observe
            targets = await deps.cdp.get_targets()
            current_url = await deps.cdp.get_current_url()
            page_title = await deps.cdp.get_page_title()
            filtered_ax = filter_ax_targets(targets)
            ax_diff = compute_ax_diff(deps.prev_targets, targets)

            # Guardrail: login detection
            if check_login_page(page_title, filtered_ax, current_url):
                await deps.ws_send({
                    "type": "login_required",
                    "message": f"Please log in: {page_title}. Agent will continue after redirect.",
                })
                try:
                    new_url = await wait_for_redirect(deps.cdp.get_current_url, current_url)
                    await deps.ws_send({"type": "agent_continuing", "url": new_url})
                except TimeoutError:
                    await deps.ws_send({"type": "login_timeout"})
                continue

            # Stagnation check
            stagnated, reason = check_stagnation(deps.step_summaries, self.STAGNATION_WINDOW)
            if stagnated:
                log.warning("[%s] stagnation detected: %s", deps.user_id, reason)
                await deps.ws_send({"type": "stagnation_warning", "reason": reason})
            stagnation_note = (
                f"\n\n⚠ STAGNATION DETECTED: {reason}\nYou MUST either try a completely different approach or call cannot_complete now."
                if stagnated else ""
            )

            # Build turn
            turn = AgentTurn(
                task=deps.task,
                step_number=step,
                scratchpad=deps.scratchpad.content,
                current_url=current_url,
                current_page_title=page_title,
                ax_tree=filtered_ax + stagnation_note,
                ax_diff=ax_diff,
                last_read_text=deps.last_read_text,
                last_read_selector=deps.last_read_selector,
                step_summaries=deps.step_summaries,
            )
            # Clear after including — agent should write what it needs to scratchpad
            deps.last_read_text = ""
            deps.last_read_selector = ""

            log.info("[%s] step %d  url=%s  ax_elements=%d", deps.user_id, step, current_url[:80], len(targets))

            # Plan
            log.debug("[%s] calling model...", deps.user_id)
            result = await agent.run(_turn_to_prompt(turn), deps=deps)
            decision: AgentDecision = result.output
            log.info("[%s] step %d  decision=%s  args=%s", deps.user_id, step, decision.action, str(decision.action_args)[:120])

            # Update scratchpad if agent requested it via the field
            if decision.scratchpad_update:
                deps.scratchpad = deps.scratchpad.update(decision.scratchpad_update)

            # Guardrail: critical action approval
            if check_critical_action(decision.action, decision.action_args):
                await deps.ws_send({
                    "type": "approval_required",
                    "action": decision.action,
                    "args": decision.action_args,
                    "reasoning": decision.reasoning,
                })
                reply = await deps.human_input_queue.get()
                if str(reply).lower() not in ("yes", "y", "approve", "ok", "confirm"):
                    deps.step_summaries.append(StepSummary(
                        step=step, url=current_url,
                        action_taken=f"[BLOCKED] {decision.action}",
                        outcome="User denied approval",
                    ))
                    continue

            # Stream progress — send thought (user-facing), not reasoning (internal)
            action_target = decision.action_args.get("url") if decision.action == "navigate" else None
            await deps.ws_send({
                "type": "step_progress",
                "step": step,
                "action": decision.action,
                "thought": decision.thought,
                "url": current_url,
                "action_target": action_target,
            })

            # Execute
            outcome = await _execute_decision(decision, deps)

            # Save targets for next-step diff
            deps.prev_targets = targets

            # Persist scratchpad after any update
            if decision.scratchpad_update or decision.action in ("write_scratchpad",):
                run_log.save_scratchpad(deps.scratchpad.content)

            # Log step
            run_log.log_step(
                step=step,
                url=current_url,
                action=decision.action,
                args=decision.action_args,
                reasoning=decision.reasoning,
                thought=decision.thought,
                outcome=outcome,
            )

            # Record
            deps.step_summaries.append(StepSummary(
                step=step,
                url=current_url,
                action_taken=f"{decision.action}({decision.action_args})",
                outcome=outcome[:120],
            ))

            # Terminal?
            if deps.result is not None:
                return deps.result

        return TaskResult(
            status="failed",
            summary="Max steps reached",
            failure_reason="max_steps_exceeded",
            steps_taken=self.MAX_STEPS,
        )
