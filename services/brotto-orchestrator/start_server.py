#!/usr/bin/env python3
"""Start the Brotto orchestrator server.

Runs the FastAPI app on port 8000 with both dev-mode (Playwright) and
extension-mode (WebSocket) agents sharing the same `AgentHarness` loop.

Usage:
    python start_server.py
    # or
    python start_server.py --server
"""

from __future__ import annotations

import asyncio
import sys


def run_server() -> None:
    """Boot uvicorn with the FastAPI app."""
    import uvicorn

    from brotto_orchestrator.main import app

    print("=" * 60)
    print("BROTTO ORCHESTRATOR SERVER")
    print("=" * 60)
    print("Endpoints:")
    print("  - WebSocket: /ws/ext/{session_id}  (extension)")
    print("  - WebSocket: /ws/{user_id}         (Playwright clients)")
    print("  - HTTP     : /v1/sessions          (create session)")
    print("  - HTTP     : /run                  (dev mode task)")
    print("  - HTTP     : /health               (liveness)")
    print()
    print("Extension:")
    print("  1. Open chrome://extensions/")
    print("  2. Load unpacked: clients/brotto-extension/dist")
    print("  3. Configure server URL in extension options")
    print("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)
