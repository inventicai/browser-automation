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
from .guardrails import check_login_page, check_critical_action, check_sensitive_action
from ..policy.gate import GateDecision, check_domain_policy, check_first_time_seen
from ..policy.domains import etld1
from .prompt import SYSTEM_PROMPT, secure_mode_preamble
from .run_logger import RunLogger

_HISTORY_WINDOW = 12  # keep first 3 + last 9 steps in prompt

# Per-action approval prompt reasons, surfaced to the user via WS
# `reasoning` and to policy.log for audit.
_REASON_FIRST_TIME = "First time on {domain}: agent wants to {action}. Continue?"
_REASON_CRITICAL = "Critical action: {action}. Continue?"

# ponytail: every user-facing prompt in the harness routes through these
# helpers so the "deny → abort task" contract is enforced exactly once.
# Without this, every prompt site would need its own bookkeeping for
# setting deps.result + log + audit + return — easy to forget one and
# ship a partial fix.

# Actions that don't fire a UI bubble. Scratchpad mutations and recall are
# metadata — the user sees the thought, not the write/recall itself.
_INTERNAL_ACTIONS = {
    "write_scratchpad", "append_scratchpad", "read_scratchpad",
    "recall_memory",
}
# Actions that short-circuit the rest of the multi-action list.
_TERMINAL_ACTIONS = {"task_complete", "cannot_complete"}
# ponytail: ask_human is metadata too — it pauses for user input but the
# user is not "approving" an agent action, they're answering a question.
# Card UI is different (no Approve/Deny buttons).
_QUESTION_ACTIONS = {"ask_human"}
# Combined set: actions that should NEVER appear inside an approval card
# (terminal + internal + question). Reused by sensitive-action,
# first-time-seen, and the sidepanel card filter.
_NEVER_APPROVE = _TERMINAL_ACTIONS | _INTERNAL_ACTIONS | _QUESTION_ACTIONS

# ponytail: after the user clicks Approve on a policy/approval card, they
# have REVOKE_WINDOW_SECS to change their mind by sending human_reply
# "revoke". Subsequent steps on the same domain/action will re-prompt.
REVOKE_WINDOW_SECS = 5.0

log = logging.getLogger("brotto.harness")

# Component-timing buckets. Each step records how long each phase took.
# Reported at task end so we can see where wall time actually goes.
# `human_pause` (aggregate of all queue waits) is reported but EXCLUDED
# from `wall` — wall is "agent thinking" time only. Operators who want
# total elapsed time can read `total_elapsed` separately.
TIMING_BUCKETS = (
    "observe",          # CDP observation round-trip (get_targets/url/title)
    "filter",           # AX filter + diff computation
    "login_pause",      # ws_send(login_required) + queue wait for resume
    "stagnation",       # stagnation check
    "model_plan",       # agent.run — the LLM call
    "approval_pause",   # CRITICAL_PATTERNS approval + queue wait
    "execute",          # _execute_actions (CDP actions + post-obs)
    "ws_send_progress", # step_progress notifications
)
# Subset of TIMING_BUCKETS that are pure human-wait — excluded from `wall`.
_HUMAN_PAUSE_BUCKETS = frozenset({"login_pause", "approval_pause"})

_MODEL = os.getenv("AGENT_MODEL", "no-model")
# Context window size (tokens) used for the side panel's CONTEXT cell
# (% of context used). Override per model in .env. Defaults to 400k.
_CONTEXT_WINDOW_TOKENS = int(os.getenv("CONTEXT_WINDOW_TOKENS", "400000"))

# User replies that approve a pending action (login, approval, policy gate).
APPROVE_SET = frozenset({"yes", "y", "approve", "ok", "confirm"})

# ponytail: _turn_to_prompt needs access to deps (for the secure-mode
# preamble). The harness loop sets `_CURRENT_DEPS` before each agent call;
# tests set `_TEST_DEPS` for the same purpose. Module globals are the
# smallest change that avoids changing the prompt's call signature.
_CURRENT_DEPS: AgentDeps | None = None
_TEST_DEPS: AgentDeps | None = None


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

    # ponytail: secure-mode preamble is injected here, not at Agent
    # construction, so we don't need to rebuild the Agent per-task. The
    # test-helper reads `_TEST_DEPS` (a module global); the harness loop
    # sets `_CURRENT_DEPS` before each call.
    deps = _CURRENT_DEPS or _TEST_DEPS
    secure_prefix = ""
    if deps is not None and getattr(deps.policy, "mode", None) == "secure":
        secure_prefix = secure_mode_preamble(deps.policy) + "\n\n"

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

    return f"""{secure_prefix}## Task
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
<page_content untrusted url="{turn.current_url}">
{turn.ax_tree}
</page_content>

## What is your next action(s)?
"""


# ── Task-abort helpers ──────────────────────────────────────────────────────
# Every user-prompt site routes through `_prompt_user_for_approval`
# below. On deny, the task is set up to terminate on the next loop
# boundary via `deps.result = TaskResult(...)`. The `run()` loop checks
# `deps.result` at the top of every iteration. This keeps the
# "deny → abort" contract in one place.


def _policy_mode(deps: AgentDeps | None) -> str | None:
    """Read the policy mode off deps, defensively. Used to tag TaskResult
    with the mode that was in force at the time of failure/completion."""
    if deps is None:
        return None
    return getattr(getattr(deps, "policy", None), "mode", None)


def _make_user_denied_result(step: int, domain: str | None, kind: str, deps: AgentDeps | None = None) -> TaskResult:
    return TaskResult(
        status="failed",
        summary=f"User denied {kind} approval" + (f" on {domain}" if domain else ""),
        failure_reason="user_denied",
        steps_taken=step + 1,
        policy_mode=_policy_mode(deps),
    )


def _make_policy_blocked_result(step: int, domain: str, deps: AgentDeps | None = None) -> TaskResult:
    return TaskResult(
        status="failed",
        summary=f"Blocked by policy: {domain}",
        failure_reason="policy_blocked",
        steps_taken=step + 1,
        policy_mode=_policy_mode(deps),
    )


def _looks_like_blacklist_hit(domain_pattern: str, free_text: str) -> bool:
    """Light heuristic for whether the agent's free-text reason mentions
    a blacklisted domain. Used to decide whether a `cannot_complete` in
    secure mode is a POLICY PREFLIGHT (agent declined upfront) vs a
    generic failure. Matches by substring — case-insensitive — so
    "mail.google.com" / "Mail.Google.com" / "gmail" all hit. The pattern
    is the raw blacklist entry (which the user typed); the text is the
    agent's reason. False positives are tolerable here (just makes the
    enterprise bubble render instead of the generic one).
    """
    if not domain_pattern or not free_text:
        return False
    pat = domain_pattern.strip().lower()
    txt = free_text.lower()
    # ponytail: also strip URL artefacts so the heuristic matches the
    # user's intended domain even if the agent quoted the full URL.
    # `https://mail.google.com/` → take the part AFTER `://`, then strip
    # path/query/port. Order matters: stripping `://` first would lose
    # the hostname.
    if "://" in pat:
        pat = pat.split("://", 1)[1]
    for sep in ("/", "?", "#", ":"):
        if sep in pat:
            pat = pat.split(sep, 1)[0]
    if not pat:
        return False
    return pat in txt or txt in pat


def _should_prompt_cross_domain_click(
    pre_url: str | None, post_url: str | None, deps: AgentDeps,
) -> tuple[bool, str | None]:
    """Pure-function decision: did this click hop to a new eTLD+1 the
    user hasn't already approved in this task? Returns (needs_prompt,
    target_etld1) — caller handles the wire I/O.

    Reuses `deps.visited_domains` (same set `navigate()` populates). A
    domain in that set means the user has already approved visiting it
    this task — no re-prompt whether the hop came from navigate or
    click. New eTLD+1 not in the set → prompt, approve will add it.

    Safe-defaults for unknown inputs (None, unparseable URLs): no
    prompt. Better to under-prompt than to crash the harness on weird
    CDP results; the next iteration's observe-phase block catches
    anything we missed here.
    """
    if deps.policy is None or getattr(deps.policy, "mode", None) != "secure":
        return (False, None)
    if not pre_url or not post_url:
        return (False, None)
    try:
        pre_etld = etld1(pre_url)
        post_etld = etld1(post_url)
    except Exception:
        return (False, None)
    if not pre_etld or not post_etld or pre_etld == post_etld:
        return (False, None)
    if post_etld in (deps.visited_domains or ()):
        return (False, None)
    return (True, post_etld)


def _guard_first_time_seen_blacklist(
    deps: AgentDeps, current_url: str, run_log, step: int, action: str,
) -> bool:
    """Defense-in-depth: if the current URL is blacklisted, block immediately
    instead of letting the first-time-seen prompt fire.

    The observe-phase block at the top of the loop should already catch this,
    but if a future refactor breaks that ordering (or the blacklist is
    updated mid-task) we don't want to prompt the user to do something
    they're already blocked from doing.

    Returns True iff the page should be hard-blocked (caller sets
    `deps.result` + `break`s out of the actions loop).
    """
    if check_domain_policy(current_url, deps.policy) != GateDecision.BLOCK:
        return False
    domain = etld1(current_url) or current_url
    log.warning(
        "[%s] POLICY VIOLATION (defense-in-depth): first-time-seen suppressed  "
        "step=%d  url=%s  domain=%s  action=%s",
        deps.user_id, step, current_url, domain, action,
    )
    run_log.log_policy(
        step=step, kind="domain_blocked", domain=domain,
        action=action, decision="block",
    )
    deps.result = _make_policy_blocked_result(step, domain, deps=deps)
    return True


async def _execute_action(call: ActionCall, deps: AgentDeps, run_log=None) -> str:
    """Execute a single action. Returns outcome string."""
    cdp = deps.cdp
    action = call.action
    args = call.action_args

    try:
        if action == "navigate":
            # Pre-flight domain policy check (secure mode only). Re-validates
            # the URL the agent wants to visit against the blacklist before
            # sending it to CDP — catches the case where the agent proposes
            # a navigate-to-blacklisted-site mid-flow even though the
            # observe-phase check used the page's current URL. In secure
            # mode, blacklist match is a hard block (no user override).
            if deps.policy is not None and getattr(deps.policy, "mode", None) == "secure":
                target = args.get("url", "")
                decision = check_domain_policy(target, deps.policy)
                if decision == GateDecision.BLOCK:
                    domain = etld1(target) or target
                    log.warning(
                        "[%s] POLICY VIOLATION: navigate BLOCKED  url=%s  domain=%s",
                        deps.user_id, target, domain,
                    )
                    run_log.log_policy(
                        step=deps.step_number, kind="navigate_blocked", domain=domain,
                        action="navigate", decision="block",
                    )
                    deps.result = _make_policy_blocked_result(deps.step_number, domain, deps=deps)
                    return f"[BLOCKED] policy: cannot navigate to {target}"
                # Confirm-before-navigate: first navigation to a new eTLD+1
                # this task prompts the user. Approve → add to set;
                # deny → abort task. Stops the agent from silently hopping
                # to sites the user hasn't vetted in this task.
                target_domain = etld1(target)
                if target_domain and target_domain not in deps.visited_domains:
                    log.warning(
                        "[%s] POLICY VIOLATION: first navigation to domain  step=%d  domain=%s  (prompting user)",
                        deps.user_id, deps.step_number, target_domain,
                    )
                    run_log.log_policy(
                        step=deps.step_number, kind="first_navigation",
                        domain=target_domain, action="navigate",
                        decision="require_approval",
                    )
                    await deps.ws_send({
                        "type": "approval_required",
                        "action": "_policy_navigation",
                        "args": {"url": target, "domain": target_domain},
                        "reasoning": (
                            f"First navigation to {target_domain} in this "
                            f"task. Continue?"
                        ),
                    })
                    reply = await deps.human_input_queue.get()
                    if str(reply).lower() not in APPROVE_SET:
                        log.warning(
                            "[%s] POLICY VIOLATION: user DENIED first navigation  step=%d  domain=%s",
                            deps.user_id, deps.step_number, target_domain,
                        )
                        run_log.log_policy(
                            step=deps.step_number, kind="first_navigation",
                            domain=target_domain, action="navigate",
                            decision="require_approval",
                            user_decision="denied",
                        )
                        deps.result = _make_user_denied_result(
                            deps.step_number, domain=target_domain,
                            kind="first navigation", deps=deps,
                        )
                        return f"[BLOCKED] policy: user denied navigation to {target}"
                    deps.visited_domains.add(target_domain)
                    run_log.log_policy(
                        step=deps.step_number, kind="first_navigation",
                        domain=target_domain, action="navigate",
                        decision="require_approval",
                        user_decision="approved",
                    )
            await cdp.navigate(args["url"])
            await cdp.wait_for_network_idle()
            await cdp.refresh_target_map()
            return f"Navigated to {args['url']}"

        elif action == "click":
            result = await cdp.click_ref(args["ref"])
            await asyncio.sleep(0.5)
            await cdp.refresh_target_map()
            # ponytail: post-click URL check. A click can navigate the
            # browser (e.g. clicking a Gmail link on google.com). The
            # observe-phase guard catches it on the NEXT iteration, but
            # that's one step too late — the user already approved the
            # click believing it was on the current domain. Re-check
            # synchronously here so a blacklisted redirect aborts in
            # the same step.
            if (deps.policy is not None
                    and getattr(deps.policy, "mode", None) == "secure"):
                post_url = await cdp.get_current_url()
                decision = check_domain_policy(post_url, deps.policy)
                if decision == GateDecision.BLOCK:
                    domain = etld1(post_url) or post_url
                    log.warning(
                        "[%s] POLICY VIOLATION: click navigated to blacklisted URL  url=%s  domain=%s",
                        deps.user_id, post_url, domain,
                    )
                    if run_log is not None:
                        run_log.log_policy(
                            step=deps.step_number, kind="click_blocked_post",
                            domain=domain, action="click", decision="block",
                        )
                    deps.result = _make_policy_blocked_result(deps.step_number, domain, deps=deps)
                    return f"[BLOCKED] policy: click navigated to {post_url}"
                # Cross-domain click gate (Change 3): a click that hopped
                # to a new eTLD+1 not yet visited this task needs user
                # approval. Reuses `visited_domains` — already populated
                # by navigate()'s first-time-nav prompt, so a click into
                # an already-approved domain doesn't re-prompt. Deny aborts
                # the task. Pure decision in `_should_prompt_cross_domain_click`
                # (unit-tested); this is the wire side.
                pre_url = getattr(deps, "step_url", None)
                needs_prompt, target_domain = _should_prompt_cross_domain_click(
                    pre_url, post_url, deps,
                )
                if needs_prompt and target_domain is not None:
                    log.warning(
                        "[%s] POLICY: cross-domain click  step=%d  pre=%s  post=%s  domain=%s",
                        deps.user_id, deps.step_number, pre_url, post_url, target_domain,
                    )
                    if run_log is not None:
                        run_log.log_policy(
                            step=deps.step_number, kind="click_cross_domain",
                            domain=target_domain, action="click",
                            decision="require_approval",
                        )
                    await deps.ws_send({
                        "type": "approval_required",
                        "action": "_policy_cross_domain_click",
                        "args": {"from_url": pre_url, "to_url": post_url, "target_domain": target_domain},
                        "reasoning": (
                            f"Click would navigate to {target_domain}, a different "
                            f"organisation than the current page. Continue?"
                        ),
                    })
                    reply = await deps.human_input_queue.get()
                    if str(reply).lower() not in APPROVE_SET:
                        log.warning(
                            "[%s] POLICY VIOLATION: user DENIED cross-domain click  step=%d  target=%s",
                            deps.user_id, deps.step_number, target_domain,
                        )
                        if run_log is not None:
                            run_log.log_policy(
                                step=deps.step_number, kind="click_cross_domain",
                                domain=target_domain, action="click",
                                decision="require_approval", user_decision="denied",
                            )
                        deps.result = _make_user_denied_result(
                            deps.step_number, domain=target_domain,
                            kind=f"cross-domain click to {target_domain}", deps=deps,
                        )
                        return f"[BLOCKED] policy: user denied cross-domain click to {target_domain}"
                    if run_log is not None:
                        run_log.log_policy(
                            step=deps.step_number, kind="click_cross_domain",
                            domain=target_domain, action="click",
                            decision="require_approval", user_decision="approved",
                        )
                    # Approve → cache so subsequent hops/clicks in this
                    # task to the same domain don't re-prompt.
                    deps.visited_domains.add(target_domain)
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
                policy_mode=_policy_mode(deps),
            )
            return "Task complete"

        elif action == "cannot_complete":
            reason = args.get("reason", "") or ""
            tried = args.get("tried", [])
            # ponytail: in secure mode, if the agent declines upfront
            # (the preamble told it to), surface it as a POLICY PREFLIGHT
            # failure rather than a generic "cannot_complete". The
            # sidepanel uses this code to render the enterprise bubble.
            # Otherwise (normal mode, or unrelated failure), preserve
            # the existing behaviour — the agent's reason becomes
            # both summary and failure_reason verbatim.
            preflight = (
                getattr(deps.policy, "mode", None) == "secure"
                and any(_looks_like_blacklist_hit(d, reason) for d in (deps.policy.blacklist or []))
            )
            deps.result = TaskResult(
                status="failed",
                summary=reason or "Task could not be completed",
                failure_reason="policy_preflight" if preflight else (reason or None),
                tried=tried,
                steps_taken=deps.step_number,
                policy_mode=_policy_mode(deps),
            )
            # Audit row so the compliance trail shows the agent declined
            # upfront because of the org's policy, not because of any
            # network or runtime failure.
            if preflight and run_log is not None:
                run_log.log_policy(
                    step=deps.step_number, kind="agent_declined_preflight",
                    domain=None, action="cannot_complete",
                    decision="block", user_decision=None,
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
        global _CURRENT_DEPS
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
                policy_mode=_policy_mode(deps),
            )

        if not deps.task_id:
            deps.task_id = str(uuid.uuid4())
        run_log = RunLogger(deps.task_id)

        # Seed the policy.log with the effective policy in force at task
        # start. One row per task, so grep can find "what was active".
        if deps.policy is not None:
            run_log.log_policy(
                step=-1, kind="policy_active", domain=None, action=None,
                decision=(
                    f"mode={deps.policy.mode}  "
                    f"blacklist={deps.policy.blacklist}  "
                    f"first_time_seen_prompt={deps.policy.first_time_seen_prompt}"
                ),
            )

        # Restore scratchpad if this task was previously interrupted.
        # load_scratchpad returns a structured Scratchpad (entries + notes).
        # Legacy plain-text files (no # MEMORY v2 header) parse as notes-only.
        loaded = run_log.load_scratchpad()
        if loaded.entries or loaded.notes:
            deps.scratchpad = loaded

        for step in range(self.MAX_STEPS):
            deps.step_number = step
            log.info("[%s] === step %d ===", deps.user_id, step)

            # Abort gate: if a previous iteration set deps.result (policy
            # block, user denial), exit cleanly before doing another round
            # of observe/plan/execute. Otherwise the loop would burn all
            # MAX_STEPS iterations re-entering the same `if deps.result is
            # not None: continue` short-circuits.
            if deps.result is not None:
                deps.result.timing = self._log_timings(
                    deps.user_id, timings, steps_run, time.perf_counter() - task_start, cumulative_snapshots,
                )
                return deps.result

            steps_run += 1
            cumulative_snapshots.append(dict(timings))

            # Observe
            t0 = time.perf_counter()
            targets = await deps.cdp.get_targets()
            current_url = await deps.cdp.get_current_url()
            page_title = await deps.cdp.get_page_title()
            # ponytail: stash for the click cross-domain gate (Change 3).
            # The click handler runs inside this same step and needs to
            # compare pre-click URL to post-click URL.
            deps.step_url = current_url
            t1 = time.perf_counter()
            timings["observe"] += t1 - t0

            filtered_ax = filter_ax_targets(targets)
            ax_diff = compute_ax_diff(deps.prev_targets, targets)
            timings["filter"] += time.perf_counter() - t1

            # Guardrail: domain policy (secure mode only). No-op in normal
            # mode. With the whitelist dropped, the only BLOCK path here is
            # "we landed on (or got redirected to) a blacklisted URL
            # mid-task". Hard block, no override.
            if deps.policy is not None and getattr(deps.policy, "mode", None) == "secure":
                decision = check_domain_policy(current_url, deps.policy)
                if decision == GateDecision.BLOCK:
                    domain = etld1(current_url) or current_url
                    log.warning(
                        "[%s] POLICY VIOLATION: domain BLOCKED  step=%d  url=%s  domain=%s",
                        deps.user_id, step, current_url, domain,
                    )
                    run_log.log_policy(
                        step=step, kind="domain_blocked", domain=domain,
                        action="observe", decision="block",
                    )
                    timing_report = self._log_timings(
                        deps.user_id, timings, steps_run,
                        time.perf_counter() - task_start, cumulative_snapshots,
                    )
                    return TaskResult(
                        status="failed",
                        summary=f"Blocked by policy: {domain}",
                        failure_reason="policy_blocked",
                        steps_taken=steps_run,
                        timing=timing_report,
                        policy_mode=_policy_mode(deps),
                    )

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
                        policy_mode=_policy_mode(deps),
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
            _CURRENT_DEPS = deps
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
            finally:
                # _turn_to_prompt reads _CURRENT_DEPS for the secure-mode
                # preamble; clear it after the call so it doesn't leak
                # across tasks (the loop is sequential but the value
                # outlives this iteration otherwise).
                _CURRENT_DEPS = None
            timings["model_plan"] += time.perf_counter() - t_plan
            actions_summary = ", ".join(f"{c.action}" for c in decision.actions) or "(none)"
            log.info("[%s] step %d  actions=[%s]", deps.user_id, step, actions_summary)

            # Secure-mode escalation: curated list of irreversible actions
            # that always require explicit approval in secure mode (even if
            # the regex CRITICAL_PATTERNS misses them). Fires before the
            # regex check so the bank-IT-curated list wins on overlap.
            t_ap = time.perf_counter()
            if deps.policy is not None and getattr(deps.policy, "mode", None) == "secure":
                for c in decision.actions:
                    if not check_sensitive_action(c.action, c.action_args, deps.policy):
                        continue
                    log.warning(
                        "[%s] POLICY VIOLATION: sensitive action  step=%d  action=%s  (prompting user)",
                        deps.user_id, step, c.action,
                    )
                    run_log.log_policy(
                        step=step, kind="sensitive_action", domain=None,
                        action=c.action, decision="require_approval",
                    )
                    await deps.ws_send({
                        "type": "approval_required",
                        "action": c.action,
                        "args": c.action_args,
                        "reasoning": (
                            f"Sensitive action (org policy): {c.action}. "
                            f"Continue?"
                        ),
                    })
                    reply = await deps.human_input_queue.get()
                    if str(reply).lower() not in APPROVE_SET:
                        log.warning(
                            "[%s] POLICY VIOLATION: user DENIED sensitive action  step=%d  action=%s",
                            deps.user_id, step, c.action,
                        )
                        run_log.log_policy(
                            step=step, kind="sensitive_action", domain=None,
                            action=c.action, decision="require_approval",
                            user_decision="denied",
                        )
                        deps.step_summaries.append(StepSummary(
                            step=step, url=current_url,
                            action_taken=f"[BLOCKED] {c.action} (sensitive)",
                            outcome="User denied approval",
                        ))
                        deps.result = _make_user_denied_result(
                            step, domain=None, kind=f"sensitive action {c.action}",
                            deps=deps,
                        )
                        break
                if deps.result is not None:
                    timings["approval_pause"] += time.perf_counter() - t_ap
                    continue

            # Guardrail: critical action approval (check ALL actions in the
            # batch — checking only the first was a bypass: `click(delete) +
            # append_scratchpad` would only see the first critical action,
            # and if the model put a non-critical action first, critical
            # actions later in the batch ran unchecked). Deny on ANY
            # critical action aborts the entire task — the user's plan was
            # wrong, the agent shouldn't try a different angle.
            critical_actions = [
                c for c in decision.actions
                if check_critical_action(c.action, c.action_args)
            ]
            for c in critical_actions:
                await deps.ws_send({
                    "type": "approval_required",
                    "action": c.action,
                    "args": c.action_args,
                    "reasoning": decision.reasoning,
                })
                reply = await deps.human_input_queue.get()
                if str(reply).lower() not in APPROVE_SET:
                    log.warning(
                        "[%s] POLICY VIOLATION: user DENIED critical action  step=%d  action=%s",
                        deps.user_id, step, c.action,
                    )
                    run_log.log_policy(
                        step=step, kind="critical_action", domain=None,
                        action=c.action, decision="require_approval",
                        user_decision="denied",
                    )
                    deps.step_summaries.append(StepSummary(
                        step=step, url=current_url,
                        action_taken=f"[BLOCKED] {c.action}",
                        outcome="User denied approval",
                    ))
                    deps.result = _make_user_denied_result(
                        step, domain=None, kind=f"critical action {c.action}",
                        deps=deps,
                    )
                    break
            if deps.result is not None:
                timings["approval_pause"] += time.perf_counter() - t_ap
                continue

            # Secure-mode add-on: first-time-seen on this domain for ANY
            # action (not just critical ones). Each (domain, action) pair
            # prompts once per session. The pair is added to seen_first_time
            # whether approved or denied — on deny the task aborts anyway,
            # but the cache entry prevents a retry-loop on a persistent
            # prompt-injection attempt.
            if deps.policy is not None and getattr(deps.policy, "mode", None) == "secure":
                for c in decision.actions:
                    # Skip terminal / internal / question actions — they
                    # are metadata, not things the user needs to approve.
                    if c.action in _NEVER_APPROVE:
                        continue
                    # Defense-in-depth: hard-block if current URL is blacklisted,
                    # even if the observe-phase block somehow let us through.
                    if _guard_first_time_seen_blacklist(
                        deps, current_url, run_log, step, c.action,
                    ):
                        break
                    domain = etld1(current_url)
                    if domain is None:
                        continue
                    key = (domain, c.action)
                    if not check_first_time_seen(key, deps.seen_first_time, deps.policy):
                        continue
                    log.warning(
                        "[%s] POLICY VIOLATION: first-time-seen on domain  step=%d  domain=%s  action=%s  (prompting user)",
                        deps.user_id, step, domain, c.action,
                    )
                    run_log.log_policy(
                        step=step, kind="first_time_seen", domain=domain,
                        action=c.action, decision="require_approval",
                    )
                    await deps.ws_send({
                        "type": "approval_required",
                        "action": c.action,
                        "args": c.action_args,
                        "reasoning": _REASON_FIRST_TIME.format(
                            domain=domain, action=c.action,
                        ),
                    })
                    reply2 = await deps.human_input_queue.get()
                    deps.seen_first_time.add(key)
                    if str(reply2).lower() not in APPROVE_SET:
                        log.warning(
                            "[%s] POLICY VIOLATION: user DENIED first-time-seen  step=%d  domain=%s  action=%s",
                            deps.user_id, step, domain, c.action,
                        )
                        run_log.log_policy(
                            step=step, kind="first_time_seen", domain=domain,
                            action=c.action, decision="require_approval",
                            user_decision="denied",
                        )
                        deps.step_summaries.append(StepSummary(
                            step=step, url=current_url,
                            action_taken=f"[BLOCKED] {c.action} (first-time)",
                            outcome="User denied approval",
                        ))
                        deps.result = _make_user_denied_result(
                            step, domain=domain, kind="first-time action",
                            deps=deps,
                        )
                        break
                    log.warning(
                        "[%s] POLICY: user APPROVED first-time-seen  step=%d  domain=%s  action=%s",
                        deps.user_id, step, domain, c.action,
                    )
                    run_log.log_policy(
                        step=step, kind="first_time_seen", domain=domain,
                        action=c.action, decision="require_approval",
                        user_decision="approved",
                    )
            timings["approval_pause"] += time.perf_counter() - t_ap
            if deps.result is not None:
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
                    # ponytail: tells the sidepanel to show the SECURE badge
                    # on this step's bubble. Cheap to compute; piggybacks
                    # on step_progress instead of a separate WS frame.
                    "secure_mode": _policy_mode(deps) == "secure",
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
                outcome = await _execute_action(call, deps, run_log=run_log)
                outcomes.append(outcome)
                # Short-circuit the rest of the batch on a terminal action
                # (task_complete/cannot_complete — sets deps.result) or on
                # ask_human (pauses for user input; any action after it in
                # the same batch would run before the user could see the
                # question, which is the wrong order). Also break if a
                # downstream _execute_action set deps.result on a hard
                # block (e.g. navigate to blacklisted URL).
                if call.action in _TERMINAL_ACTIONS or call.action == "ask_human":
                    break
                if deps.result is not None:
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
            policy_mode=_policy_mode(deps),
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

        Two wall figures are reported:
          - `wall_s`     — total elapsed time (raw).
          - `wall_agent_s` — wall minus human-in-the-loop waits
                            (`login_pause`, `approval_pause`). The metric
                            sidepanel cards care about: "how long was the
                            agent actually thinking vs sitting idle waiting
                            for me?". User-supplied data is in `human_pause_s`.

        Output line shape:
          [brotto.harness] TIMING  user=local  steps=3  wall=5.42s
            wall_agent=3.10s  human_pause=2.32s  observe=0.31 ...
        """
        human_pause_total = sum(timings.get(b, 0.0) for b in _HUMAN_PAUSE_BUCKETS)
        wall_agent = max(0.0, wall - human_pause_total)
        parts = "  ".join(f"{k}={timings[k]:.2f}" for k in TIMING_BUCKETS)
        log.info(
            "[%s] TIMING  steps=%d  wall=%.2fs  wall_agent=%.2fs  human_pause=%.2fs  %s",
            user_id, steps, wall, wall_agent, human_pause_total, parts,
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
            "wall_agent_s": round(wall_agent, 3),
            "human_pause_s": round(human_pause_total, 3),
            "components": {k: round(timings[k], 3) for k in TIMING_BUCKETS},
            "per_step": per_step,
        }
