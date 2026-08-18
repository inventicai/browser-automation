#!/usr/bin/env python3
"""Start the Brotto orchestrator server.

Usage:
    uv run main.py            # start the FastAPI server (default)
    uv run main.py --help     # show this message
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# services/brotto-orchestrator/src must be importable regardless of cwd.
_SRC = Path(__file__).resolve().parent / "services" / "brotto-orchestrator" / "src"
sys.path.insert(0, str(_SRC))


def run_server() -> None:
    """Start the FastAPI server with WebSocket extension support."""
    print("\n" + "=" * 60)
    print("STARTING BROTTO ORCHESTRATOR")
    print("=" * 60)
    print("\nServer configuration:")
    print("  - Host: 0.0.0.0")
    print("  - Port: 8000")
    print("  - WebSocket: /ws/ext/{session_id} (extension mode)")
    print("\nTo load extension:")
    print("  1. Open chrome://extensions/")
    print("  2. Load unpacked: clients/brotto-extension/dist")
    print("  3. Configure server URL in extension options")
    print("\nStarting in 2 seconds...\n")

    import uvicorn
    from brotto_orchestrator.main import app

    time.sleep(2)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    try:
        run_server()
    except KeyboardInterrupt:
        print("\n\nServer stopped")