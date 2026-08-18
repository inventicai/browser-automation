"""Benchmark runner.

Drives `AgentHarness` against a `TaskSpec` and returns a `TaskResult`.
The runner is the only thing that knows about both the harness and
the spec — keep the seam tiny.

Per-run flow:
1. Build the TaskSpec with a known start_url (typically a sandbox).
2. Launch Playwright pointed at the start_url.
3. Build AgentDeps and run the harness.
4. Run the success check on the terminal state.
5. Capture JSONL row.

The harness is a black box from the runner's perspective. We inject
the model name via `os.environ` so the same code path picks up
haiku, sonnet, or opus without changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .spec import RunState, TaskResult, TaskSpec

log = logging.getLogger("brotto.bench")


DEFAULT_RESULTS_PATH = Path("benchmark/runs.jsonl")


# A factory takes a start_url and returns a TaskSpec. The runner
# builds the spec inside the sandbox so the URL is fresh per run.
TaskFactory = Callable[[str], TaskSpec]


async def run_task(
    spec_or_factory,
    *,
    model: str,
    results_path: Path = DEFAULT_RESULTS_PATH,
    timeout_s: float = 120.0,
    start_url: str | None = None,
) -> TaskResult:
    """Run a single task once against the given model. Returns the result.

    Persists the result to JSONL immediately so a crash mid-run still
    leaves a row.

    Args:
        spec_or_factory: Either a TaskSpec (use directly) or a
            TaskFactory(start_url) (build fresh per run).
        model: Anthropic model id (e.g. "haiku-4-5").
        start_url: URL to use if `spec_or_factory` is a TaskSpec.
            Factory-built specs get their URL from the factory.
    """
    os.environ["AGENT_MODEL"] = model
    start = time.monotonic()
    spec_name = getattr(spec_or_factory, "name", "unknown")
    result = TaskResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        task=spec_name,
        model=model,
        ok=False,
        steps=0,
        tokens=0,
        elapsed_ms=0,
    )

    if isinstance(spec_or_factory, TaskSpec):
        spec = spec_or_factory
    else:
        if start_url is None:
            raise ValueError("factory tasks need a start_url")
        spec = spec_or_factory(start_url)

    from ..dev.playwright_browser import PlaywrightBrowser
    from ..cdp.relay import CDPRelay
    from ..agent.context import AgentDeps
    from ..agent.harness import AgentHarness

    browser = PlaywrightBrowser()
    approval_requested = False

    async def ws_send(msg: dict) -> None:
        nonlocal approval_requested
        if msg.get("type") == "approval_required":
            approval_requested = True

    try:
        await asyncio.wait_for(browser.launch(headless=True, url=spec.start_url), timeout=30)
        cdp = CDPRelay(browser)
        deps = AgentDeps(
            user_id="bench",
            task=spec.goal,
            task_id=f"bench-{spec.name}-{int(time.time())}",
            cdp=cdp,
            ws_send=ws_send,
        )

        try:
            task_result = await asyncio.wait_for(
                AgentHarness().run(deps),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            result.error = "timeout"
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
            _append_jsonl(results_path, result)
            return result

        result.steps = task_result.steps_taken
        result.tokens = int((task_result.timing or {}).get("total_tokens", 0))
        result.extracted = task_result.extracted_data

        run_state = RunState(
            final_url=await cdp.get_current_url(),
            extracted_data=task_result.extracted_data,
            scratchpad=deps.scratchpad.content,
            steps_taken=task_result.steps_taken,
            approval_was_requested=approval_requested,
        )
        try:
            result.ok = await asyncio.wait_for(spec.success_check(run_state), timeout=5)
        except Exception as exc:
            log.warning("success check raised for %s: %s", spec.name, exc)
            result.ok = False
            result.error = f"check_error: {exc}"

    except Exception as exc:
        log.exception("task %s failed", spec.name)
        result.error = repr(exc)
    finally:
        try:
            await browser.close()
        except Exception:
            pass

    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    _append_jsonl(results_path, result)
    return result


def _append_jsonl(path: Path, result: TaskResult) -> None:
    """Append a JSONL row. Creates parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(result.__dict__, default=str) + "\n")


async def run_suite(
    factories: list[TaskFactory],
    *,
    model: str,
    results_path: Path = DEFAULT_RESULTS_PATH,
    start_urls: dict[str, str] | None = None,
) -> list[TaskResult]:
    """Run each factory against the same model. Optionally pre-supply URLs.

    `start_urls` is a name → URL map from the caller (typically the
    CLI, which manages the sandbox lifecycle out-of-band).
    """
    out: list[TaskResult] = []
    for factory in factories:
        # Build a stub spec to read the name without a URL.
        # Use a placeholder URL; the real one is supplied per-run.
        stub = factory("http://placeholder.invalid/")
        spec_name = stub.name
        url = (start_urls or {}).get(spec_name, "http://placeholder.invalid/")
        log.info("running %s on %s", spec_name, model)
        result = await run_task(factory, model=model, results_path=results_path, start_url=url)
        out.append(result)
        log.info(
            "  %s  ok=%s  steps=%d  %dms",
            spec_name, result.ok, result.steps, result.elapsed_ms,
        )
    return out


__all__ = ["run_task", "run_suite", "TaskFactory"]
