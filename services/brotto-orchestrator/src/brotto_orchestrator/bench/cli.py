"""Benchmark CLI entry point.

Usage:
    python -m brotto_orchestrator.bench.cli --task=login_form --model=haiku-4-5
    python -m brotto_orchestrator.bench.cli --task=all --model=sonnet-4-6
    python -m brotto_orchestrator.bench.cli --task=login_form --model=haiku-4-5 --write-card

`--task=all` runs every task registered in `bench.tasks`.
`--write-card` regenerates `benchmark/README.md` from the JSONL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from .runner import DEFAULT_RESULTS_PATH, run_task
from .tasks import (
    APPROVAL_HTML,
    DATA_HTML,
    FORM_HTML,
    LANDING_HTML,
    LOGIN_HTML,
    RECOVERY_HTML,
    make_approval_gate_task,
    make_data_extract_task,
    make_error_recovery_task,
    make_login_form_task,
    make_multi_step_task,
)


log = logging.getLogger("brotto.bench.cli")


# Each task is a (factory, sandbox_html) tuple. New tasks added here.
TASK_REGISTRY: dict[str, tuple] = {
    "login_form": (make_login_form_task, LOGIN_HTML),
    "data_extract": (make_data_extract_task, DATA_HTML),
    "multi_step": (make_multi_step_task, LANDING_HTML),
    "error_recovery": (make_error_recovery_task, RECOVERY_HTML),
    "approval_gate": (make_approval_gate_task, APPROVAL_HTML),
}


def _build_task_urls(names: list[str]) -> dict[str, str]:
    """Spin up a sandbox for each task and return {name: url}."""
    from .sandbox.server import sandbox as _base_sandbox

    urls: dict[str, str] = {}
    contexts = []
    for name in names:
        _factory, html = TASK_REGISTRY[name]
        ctx = _base_sandbox(html)
        contexts.append(ctx)
        url = ctx.__enter__()
        urls[name] = url
    # Stash the contexts so the caller can close them later.
    _build_task_urls._contexts = contexts  # type: ignore[attr-defined]
    return urls


def _teardown_task_urls() -> None:
    """Close all sandboxes that _build_task_urls opened."""
    contexts = getattr(_build_task_urls, "_contexts", [])
    for ctx in contexts:
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass
    _build_task_urls._contexts = []  # type: ignore[attr-defined]


async def _run_one(task_name: str, model: str, results_path: Path, url: str):
    """Run a single task with a pre-built URL."""
    factory, _html = TASK_REGISTRY[task_name]
    return await run_task(factory, model=model, results_path=results_path, start_url=url)


async def _run_suite(model: str, results_path: Path) -> list:
    """Run every registered task against the same model."""
    names = list(TASK_REGISTRY.keys())
    urls = _build_task_urls(names)
    try:
        out = []
        for name in names:
            log.info("running %s on %s", name, model)
            result = await _run_one(name, model, results_path, urls[name])
            out.append(result)
            log.info(
                "  %s  ok=%s  steps=%d  %dms",
                name, result.ok, result.steps, result.elapsed_ms,
            )
        return out
    finally:
        _teardown_task_urls()


def _write_card(results_path: Path, card_path: Path) -> None:
    """Generate the public benchmark card from JSONL results."""
    rows: list[dict] = []
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))

    by_run: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_run[r["timestamp"]].append(r)

    runs = sorted(by_run.items(), key=lambda kv: kv[0])[-3:]

    lines: list[str] = [
        "# Brotto Benchmark",
        "",
        "Last 3 runs. Tasks run on self-hosted sandboxes. ",
        "No LLM-as-judge — every pass/fail is a Python check.",
        "",
    ]

    all_tasks: list[str] = []
    for _ts, ts_rows in runs:
        for r in ts_rows:
            if r["task"] not in all_tasks:
                all_tasks.append(r["task"])

    if not all_tasks:
        lines.append(
            "_No benchmark runs yet. Run `python -m brotto_orchestrator.bench.cli "
            "--task=login_form --model=haiku-4-5 --write-card` to populate._"
        )
    else:
        header = "| Run | " + " | ".join(all_tasks) + " |"
        sep = "|-----|" + "|".join(["------"] * len(all_tasks)) + "|"
        lines += [header, sep]
        for ts, ts_rows in runs:
            by_name = {r["task"]: r for r in ts_rows}
            cells = [
                "✅" if by_name.get(task, {}).get("ok") else "❌"
                for task in all_tasks
            ]
            run_label = ts.split("T")[0] + " " + ts.split("T")[1].split(".")[0]
            lines.append(f"| {run_label} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Tasks: " + ", ".join(all_tasks) + "." if all_tasks else "",
        "Methodology: deterministic checks, no LLM-as-judge. "
        "Sandboxes are static HTML served on a free port.",
        "",
    ]

    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text("\n".join(lines))
    log.info("wrote %s", card_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Brotto benchmark task")
    parser.add_argument("--task", default="login_form", help="Task name or 'all'")
    parser.add_argument("--model", required=True, help="Anthropic model id")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--write-card", action="store_true")
    parser.add_argument("--card", type=Path, default=Path("benchmark/README.md"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.task == "all":
        results = asyncio.run(_run_suite(args.model, args.results))
    else:
        if args.task not in TASK_REGISTRY:
            raise SystemExit(f"unknown task {args.task!r}; available: {list(TASK_REGISTRY)}")
        urls = _build_task_urls([args.task])
        try:
            results = [asyncio.run(_run_one(args.task, args.model, args.results, urls[args.task]))]
        finally:
            _teardown_task_urls()

    failed = [r for r in results if not r.ok]
    if failed:
        log.warning("%d/%d failed", len(failed), len(results))

    if args.write_card:
        _write_card(args.results, args.card)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
