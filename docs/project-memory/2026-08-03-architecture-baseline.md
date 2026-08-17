# Architecture Baseline: Brotto Browser Automation MVP

**Recorded:** 2026-08-17 (post-pivot)
**Status:** Verified repository baseline reflecting current Brotto implementation

## Product intent

Brotto is a self-hosted browser automation agent that drives a user's real
Chrome from a side-panel extension. The orchestrator runs the agent loop
against an external LLM (Anthropic Claude default, model-agnostic via
pydantic-ai); the extension drives the browser via `chrome.debugger`.

The agent only ever sees:

- The current URL and page title.
- A filtered accessibility tree (interactive roles only, viewport-first).
- Screenshots taken via `Page.captureScreenshot`.
- Text it explicitly reads from a CSS-selected region (returned once).

The extension never transmits cookies, authorization headers, localStorage,
sessionStorage, credentials, password values, or raw browser-profile data.

## Architecture

```
                ┌──────────────────────────────────────┐
                │  Brotto extension (Manifest V3)     │
                │  - background service worker        │
                │  - chrome.debugger wrapper          │
                │  - AX-tree capture + diff           │
                │  - side-panel UI                    │
                └─────────────────┬────────────────────┘
                                  │  WSS (outbound, auth)
                                  ▼
                ┌──────────────────────────────────────┐
                │  Brotto orchestrator (FastAPI)       │
                │  - /ws/ext/{id}  extension relay     │
                │  - /ws/{user}    Playwright client   │
                │  - /run          headless task run   │
                │  - agent harness (observe→plan→act)  │
                │  - AX filter + diff + guardrails     │
                └─────────────────┬────────────────────┘
                                  │  pydantic-ai
                                  ▼
                          External LLM (Anthropic Claude)
```

## Locked architecture decisions

- Python owns the orchestrator and agent loop. TypeScript owns only the
  extension client.
- `chrome.debugger` is the only browser control surface. The orchestrator
  never speaks CDP directly to the user's browser — it sends typed actions
  over the WebSocket relay and the extension executes them.
- One in-flight action per session. Each action references the observation
  it was planned against.
- Security policy is enforced in code on both orchestrator and extension
  boundaries; irreversible actions require explicit human approval.
- The committed action/observation contracts in
  `services/brotto-orchestrator/src/brotto_orchestrator/contracts.py`
  are the only protocol surface; the agent loop and the extension both
  consume them.

## Verified current-state findings

The current runtime path is end-to-end:

- Extension (`clients/brotto-extension/src/background.ts`) attaches to a
  user-selected tab, captures filtered AX targets via `Accessibility.getFullAXTree`
  + `DOM.getBoxModel`, and ships them as `observation` messages over a
  WebSocket opened at `ws://{server}/ws/ext/{session_id}`.
- Orchestrator (`services/brotto-orchestrator/src/brotto_orchestrator/main.py`)
  accepts the WS, runs `AgentHarness`, and pushes typed `action` /
  `step_progress` / `ask_human` / `approval_required` messages back.
- Extension executes actions via an allowlisted CDP command set
  (`Page.navigate`, `Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`,
  `Runtime.evaluate` for text reads only — no arbitrary JS).
- Dev mode (`POST /run` + `start_server.py`) drives Playwright directly
  against a local Chromium and exercises the same `AgentHarness`.
- `AgentHarness` (`agent/harness.py`) uses pydantic-ai with `AgentDecision`
  as the structured output type and `SYSTEM_PROMPT` (`agent/prompt.py`)
  for tool surface and rules.
- `AXTreeExtractor` and CDP filtering live in
  `dev/ax_tree_extractor.py` and `agent/ax_filter.py` / `agent/ax_diff.py`.

## Existing components worth retaining

- `agent/harness.py` — agent loop with history windowing, AX diff, scratchpad.
- `cdp/relay.py`, `cdp/extension_relay.py`, `cdp/watchdog.py` — CDP transport.
- `agent/guardrails.py` — login-page detection, critical-action prompts,
  redirect waits.
- `agent/stagnation.py` — loop detection and forced terminate.
- `agent/run_logger.py` — per-run structured logging.
- `session/registry.py`, `session/auth.py` — token-gated session lifecycle.
- `contracts.py` — `ObservationV1` and `BrowserAction` Pydantic models.

## Components that do not exist yet

- Recipe recording / deterministic replay.
- Trajectory event log for audit + replay input.
- Multi-tab coordination beyond the opener-tab fallback already in
  `background.ts`.
- Visual regression / screenshot diffing.

## Security invariants

- No cookie export or cookie-reading protocol capability.
- No authorization-header, storage-value, credential, password, or
  browser-profile transmission.
- Screenshots and AX-tree metadata go only to the configured customer
  server.
- `Runtime.evaluate` is restricted to text reads and pre-allowed selectors.
- Only the user-selected tab is attached; immediate detach on socket close.
- High-impact actions require explicit human approval in the side panel.
- Sessions use random identifiers, short-lived tokens, message expiry,
  sequence validation, payload limits, and replay protection.

## Dirty-worktree warning

The local worktree may contain generated dependency directories (`.venv`,
`node_modules`, `dist`, `__pycache__`), `.env` files, and logs. These are
covered by `.gitignore` and must never be committed. Stage only deliberate
files; preserve unrelated in-progress work.