# Brotto Browser Automation Platform

This is the project working directory for Brotto, a server-hosted browser
automation agent that drives a user's real Chrome from a side-panel extension.

## Architecture Overview

Two components, one protocol:

- **Orchestrator (server)** — Python (FastAPI + pydantic-ai + Playwright). Runs
  the agent loop, owns the AX-tree extraction, plans actions, and ships them
  back over a WebSocket relay.
- **Extension (client)** — Chrome/Edge Manifest V3 extension (TypeScript +
  esbuild). Attaches to a user-selected tab via `chrome.debugger`, streams
  filtered AX-tree observations to the orchestrator, executes the CDP actions
  it receives, and surfaces a side-panel UI.

The orchestrator has two run modes that share the same agent loop:

- **Dev mode** — Playwright drives a local Chromium. Used for tests and
  headless task runs (`POST /run`).
- **Extension mode** — The browser extension drives the user's real browser.
  Connected over authenticated WSS on `/ws/ext/{session_id}`.

A desktop-connector / thin-client loop runs on `/ws/{user_id}` for Playwright
WebSocket clients (used by integration tests).

## Key Security Principles

- Extension is the only thing that holds `chrome.debugger`. The orchestrator
  never speaks CDP directly to the user's browser.
- Server never exposes CDP ports publicly. Extension connects outbound over WSS.
- Page DOM text is never sent verbatim to the model. The agent only sees the
  filtered AX tree + URL + title + screenshots.
- High-impact actions (purchase, send, delete) require explicit human approval
  via the side panel before the orchestrator will execute them.
- `chrome.debugger` is attached only to a tab the user explicitly selected.
- No cookie, authorization-header, or credential transmission. The extension
  inherits the user's existing logged-in state via CDP without ever reading
  cookies or storage.
- No CAPTCHA bypass or stealth functionality.

## Repository Structure

```
/clients/brotto-extension/   Manifest V3 Chrome/Edge extension (TypeScript)
/services/brotto-orchestrator/   Python orchestrator (FastAPI + pydantic-ai)
/docs/                      Project README, threat model, project-memory
PLAN.md                     Build plan (phases, critical success factors)
decisions.md                Locked architectural decisions (D1–D10)
Dockerfile                  Container image for the orchestrator
requirements*.txt           Python dependency pins (runtime + dev)
```

## Locked Decisions

The full log lives in `decisions.md`. The high-impact ones, all locked:

1. **D1** — Semantic target extraction via CDP Accessibility tree (not JS DOM).
2. **D2** — Actions reference semantic `target_id`s, not (x, y) coordinates.
3. **D3** — Synchronous single-threaded agent loop per session.
4. **D4** — Structured observation (URL + filtered AX + screenshot), not raw vision embeddings.
5. **D5** — Action failures surface to the agent immediately, not silently retried.
6. **D6** — pydantic-ai for the agent layer; model-agnostic (Anthropic Claude default).
7. **D7** — Single agent code path; dev vs. extension is just a pluggable browser interface.
8. **D8** — Playwright is the dev harness.
9. **D9** — Extension ↔ server uses WebSocket with sequence tracking.
10. **D10** — Evals are real-world tasks on real sites, never synthetic mocks.

Other project-level locked decisions:

- Apache-2.0 license (see `NOTICE` and `THIRD_PARTY_NOTICES`).
- Chrome and Edge are the supported browser targets.
- Screenshot retention is off by default.
- Server-only agent harness and policy enforcement — the extension is a thin relay.

## Commands

```bash
# Install orchestrator dependencies
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium --with-deps

# Run orchestrator (dev mode + extension mode in one server)
python services/brotto-orchestrator/start_server.py
# or for server-only:
python services/brotto-orchestrator/start_server.py --server

# Build the extension
cd clients/brotto-extension
npm install
npm run build
# Load clients/brotto-extension/dist/ as an unpacked extension in Chrome

# Container
docker build -t brotto-orchestrator .
docker run --rm -p 8000:8000 brotto-orchestrator
```

## Relevant Skills

This project uses GSD-style planning workflow:

- `superpowers:execute-plan` — for implementation planning and tracking.
- `superpowers:brainstorming` — when exploring new designs or major changes.