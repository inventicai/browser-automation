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

## Distribution

Tagged releases publish a signed `brotto.crx` (and the Edge ZIP) as a GitHub Release. Internal testers download from there and drag into `chrome://extensions/`. See `docs/packaging/README.md` for the release flow and the one-time secrets setup.

## How it works

1. Extension attaches to a user-selected tab via `chrome.debugger`.
2. Extension streams accessibility tree + screenshot to the orchestrator over WebSocket.
3. Orchestrator (pydantic-ai + Anthropic) plans one action per step.
4. Extension executes the action in the user's real browser and returns the next observation.
5. Loop until the model calls `done`.

Dev mode (no extension needed) uses Playwright directly inside the orchestrator.

See `THREAT_MODEL.md` for security boundaries.
