# Brotto

Server-hosted browser automation. Python orchestrator + a Chrome extension that drives the user's real browser.

## Layout

```
services/brotto-orchestrator/   Python server (FastAPI + pydantic-ai + Playwright)
clients/brotto-extension/       Chrome extension (TypeScript, manifest v3)
docs/                           this folder
```

## Run locally

```bash
pip install -r requirements.txt
playwright install chromium
python services/brotto-orchestrator/start_server.py
```

Build the extension: `cd clients/brotto-extension && npm install && npm run build`, then load `dist/` as an unpacked extension in Chrome.

## Distribution channels

The extension ships through two internal channels (no public Chrome Web Store).

| Channel | Audience | Friction |
|---|---|---|
| Self-hosted CRX on Cloudflare Pages | Chrome engineers | Drag-drop a `.crx` once; auto-updates after |
| Unlisted Edge Add-ons | Chrome + Edge non-engineers | Click a link, install, done |

See `docs/packaging/README.md` for the hub, or jump straight to `docs/packaging/edge-unlisted.md` to publish an Edge listing.

## How it works

1. Extension attaches to a user-selected tab via `chrome.debugger`.
2. Extension streams accessibility tree + screenshot to the orchestrator over WebSocket.
3. Orchestrator (pydantic-ai + Anthropic) plans one action per step.
4. Extension executes the action in the user's real browser and returns the next observation.
5. Loop until the model calls `done`.

Dev mode (no extension needed) uses Playwright directly inside the orchestrator.

See `THREAT_MODEL.md` for security boundaries.
