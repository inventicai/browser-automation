"""E2E smoke for secure-mode + domain policy.

Drives the harness with a fake CDP and a monkey-patched pydantic-ai
agent (no real browser or model API key needed) to exercise each
checkpoint and print the resulting WS messages + final TaskResult.

Run from repo root:

    PYTHONPATH=services/brotto-orchestrator/src \
        .venv/bin/python services/brotto-orchestrator/scripts/smoke_secure_mode.py

Scenarios (enterprise redesign — whitelist removed, blacklist = hard block,
deny → abort task):

    1. Normal mode — no policy enforcement (regression check).
    2. Secure mode + landing on blacklisted URL → task fails with policy_blocked.
    3. Secure mode + agent navigates to blacklisted URL → task fails at execute.
    4. Secure mode + critical-pattern action denied → task aborts with user_denied.
    5. Secure mode + first-time-seen denied → task aborts with user_denied.
    6. Secure mode + first-time-seen approved → continues normally.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Make the package importable without `uv run`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brotto_orchestrator.agent.context import (
    ActionCall,
    AgentDecision,
    AgentDeps,
    TaskResult,
)
from brotto_orchestrator.policy import (
    Policy,
    check_domain_policy,
    etld1,
)


# ── Fake CDP ────────────────────────────────────────────────────────────────


class FakeCDP:
    """A minimal CDP that returns the configured URL and a small AX tree.

    Tracks every action the agent tried so the smoke script can verify
    post-conditions.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.clicked: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.navigated: list[str] = []
        self.refreshed = 0

    async def ping(self) -> bool:
        return True

    async def get_targets(self):
        return []

    async def get_current_url(self) -> str:
        return self.url

    async def get_page_title(self) -> str:
        return f"Page at {self.url}"

    async def click_ref(self, ref: str) -> str:
        self.clicked.append(ref)
        return f"clicked {ref}"

    async def focus_ref(self, ref: str) -> None:
        pass

    async def clear_ref(self, ref: str) -> None:
        pass

    async def type_text_to_ref(self, ref: str, text: str) -> str:
        self.typed.append((ref, text))
        return f"typed {text!r} into {ref}"

    async def scroll(self, direction: str, amount: int) -> None:
        pass

    async def read_page_text(self, *args, **kwargs) -> str:
        return ""

    async def navigate(self, url: str) -> None:
        self.navigated.append(url)

    async def wait_for_network_idle(self) -> None:
        pass

    async def refresh_target_map(self) -> None:
        self.refreshed += 1


# ── Canned agent (replaces pydantic-ai during the smoke) ────────────────────


class CannedAgent:
    """Plays back a fixed sequence of AgentDecisions, one per call."""

    def __init__(self, decisions: list[AgentDecision]) -> None:
        self._decisions = list(decisions)
        self.calls = 0

    async def run(self, prompt: str, deps):
        self.calls += 1
        if not self._decisions:
            return _decision_result(
                AgentDecision(
                    reasoning="no more canned decisions",
                    thought="exhausted",
                    actions=[ActionCall(action="task_complete", action_args={"summary": "done"})],
                )
            )
        return _decision_result(self._decisions.pop(0))


class _Usage:
    input_tokens = 1200


def _decision_result(decision: AgentDecision):
    """Shape that mimics what pydantic-ai's run() returns."""

    class _R:
        output = decision
        usage = _Usage()
    return _R()


# ── Human input queue ───────────────────────────────────────────────────────


class FakeHuman:
    """Pre-loaded reply queue. test scripts `put` replies in order."""

    def __init__(self, replies: list[str]) -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        for r in replies:
            self._q.put_nowait(r)

    async def get(self) -> str:
        return await asyncio.wait_for(self._q.get(), timeout=2.0)


# ── WS recorder ─────────────────────────────────────────────────────────────


class WSRecorder:
    """Captures every ws_send call so the smoke can print them."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, msg: dict) -> None:
        self.messages.append(msg)
        kind = msg.get("type")
        if kind == "approval_required":
            print(
                f"    → approval_required  action={msg.get('action')!r}"
                f"  reason={msg.get('reasoning')!r}"
            )
        elif kind == "step_progress":
            print(
                f"    → step_progress  step={msg.get('step')}  "
                f"action={msg.get('action')!r}"
            )
        elif kind == "login_required":
            print(f"    → login_required  message={msg.get('message')!r}")
        elif kind == "task_result":
            print(f"    → task_result  status={msg['result'].get('status')}")
        elif kind == "context_update":
            print(f"    → context_update  pct={msg.get('context', {}).get('pct')}")
        else:
            print(f"    → {kind}")


# ── Scenarios ───────────────────────────────────────────────────────────────


async def run_scenario(name: str, *, policy: Policy, url: str, decisions: list[AgentDecision],
                       human_replies: list[str], expect_timeout: bool = False):
    print(f"\n── {name} ──")
    print(f"  policy.mode={policy.mode}  blacklist={policy.blacklist}")
    print(f"  starting url={url}")
    print(f"  human_replies (in order): {human_replies}")

    cdp = FakeCDP(url=url)
    ws = WSRecorder()
    human = FakeHuman(human_replies)

    deps = AgentDeps(
        user_id="smoke",
        task="smoke task",
        cdp=cdp,
        ws_send=ws,
        human_input_queue=human,
        policy=policy,
    )

    from brotto_orchestrator.agent import harness as h_mod

    real_agent = h_mod.agent
    h_mod.agent = CannedAgent(decisions)
    try:
        try:
            result = await h_mod.AgentHarness().run(deps)
        except asyncio.TimeoutError:
            if expect_timeout:
                print("  TimeoutError (expected — user keeps denying; agent blocks waiting for input)")
            else:
                print("  UNEXPECTED TimeoutError — check that you provided enough human_replies")
            return
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
            return
    finally:
        h_mod.agent = real_agent

    print(f"  result.status        = {result.status}")
    print(f"  result.failure_reason= {result.failure_reason}")
    print(f"  result.summary       = {result.summary!r}")
    print(f"  result.steps_taken   = {result.steps_taken}")
    print(f"  CDP navigated        = {cdp.navigated}")
    print(f"  CDP clicked          = {cdp.clicked}")
    print(f"  WS messages captured = {len(ws.messages)}")
    if result.timing:
        print(
            f"  TIMING  wall={result.timing['wall_s']:.2f}s"
            f"  wall_agent={result.timing['wall_agent_s']:.2f}s"
            f"  human_pause={result.timing['human_pause_s']:.2f}s"
        )


async def main() -> None:
    # Make agent construction succeed (it's never actually called in our patched flow).
    os.environ.setdefault("AGENT_MODEL", "test")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")

    # Sanity print of the gate logic for a few URLs.
    print("== Gate decision previews (no harness run) ==")
    secure = Policy(mode="secure", blacklist=["evil.com"])
    for u in ["https://app.bank.com/x", "https://evil.com/x", "https://other.com/x", "mailto:user@bank.com", "not a url"]:
        d = check_domain_policy(u, secure)
        print(f"  {u:<40}  eTLD+1={etld1(u)!r:<22}  → {d.value}")

    # 1. Normal mode = today's behaviour.
    await run_scenario(
        "1. Normal mode (regression check — no policy prompts expected)",
        policy=Policy(mode="normal"),
        url="https://example.com/home",
        decisions=[
            AgentDecision(
                reasoning="click the first button",
                thought="looks good",
                actions=[ActionCall(action="click", action_args={"ref": "btn1"})],
            ),
            AgentDecision(
                reasoning="all done",
                thought="finishing",
                actions=[ActionCall(action="task_complete", action_args={"summary": "clicked"})],
            ),
        ],
        human_replies=[],
    )

    # 2. Secure + landing on blacklisted URL → observe-phase hard block.
    await run_scenario(
        "2. Secure + landing on blacklisted URL → task fails policy_blocked at observe",
        policy=Policy(mode="secure", blacklist=["evil.com"]),
        url="https://evil.com/welcome",
        decisions=[
            AgentDecision(
                reasoning="would have clicked",
                thought="ok",
                actions=[ActionCall(action="click", action_args={"ref": "btn1"})],
            ),
        ],
        human_replies=[],
    )

    # 3. Secure + agent's navigate targets blacklisted URL → block at execute.
    await run_scenario(
        "3. Secure + agent navigates to blacklisted URL → task fails at execute",
        policy=Policy(mode="secure", blacklist=["evil.com"]),
        url="https://clean.com/start",
        decisions=[
            AgentDecision(
                reasoning="go to evil site",
                thought="as instructed",
                actions=[ActionCall(action="navigate", action_args={"url": "https://evil.com/landing"})],
            ),
            AgentDecision(
                reasoning="done",
                thought="finishing",
                actions=[ActionCall(action="task_complete", action_args={"summary": "ok"})],
            ),
        ],
        human_replies=[],
    )

    # 4. Secure + critical-pattern action → user denies → task aborts.
    await run_scenario(
        "4. Secure + critical-pattern action denied → task aborts with user_denied",
        policy=Policy(mode="secure"),
        url="https://example.com/admin",
        decisions=[
            AgentDecision(
                reasoning="delete the record",
                thought="destructive",
                actions=[ActionCall(action="click", action_args={"ref": "btn-del"})],
            ),
            # Should never run — task aborts on the previous deny.
            AgentDecision(
                reasoning="retry",
                thought="x",
                actions=[ActionCall(action="click", action_args={"ref": "btn2"})],
            ),
        ],
        human_replies=["no"],
    )

    # 5. Secure + first-time-seen denied → task aborts.
    await run_scenario(
        "5. Secure + first-time-seen denied → task aborts with user_denied",
        policy=Policy(mode="secure", first_time_seen_prompt=True),
        url="https://example.com/admin",
        decisions=[
            AgentDecision(
                reasoning="click something",
                thought="x",
                actions=[ActionCall(action="click", action_args={"ref": "btn1"})],
            ),
            AgentDecision(
                reasoning="retry",
                thought="x",
                actions=[ActionCall(action="click", action_args={"ref": "btn2"})],
            ),
        ],
        human_replies=["no"],  # deny the first-time-seen card
    )

    # 6. Secure + first-time-seen approved → continues normally.
    await run_scenario(
        "6. Secure + first-time-seen approved → task completes",
        policy=Policy(mode="secure", first_time_seen_prompt=True),
        url="https://example.com/admin",
        decisions=[
            AgentDecision(
                reasoning="click something",
                thought="x",
                actions=[ActionCall(action="click", action_args={"ref": "btn1"})],
            ),
            AgentDecision(
                reasoning="all done",
                thought="finishing",
                actions=[ActionCall(action="task_complete", action_args={"summary": "ok"})],
            ),
        ],
        human_replies=["yes"],
    )


if __name__ == "__main__":
    asyncio.run(main())
