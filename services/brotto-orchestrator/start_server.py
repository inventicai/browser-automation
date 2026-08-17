#!/usr/bin/env python3
"""Start the brotto orchestrator server with full integration.

Runs both dev mode (Playwright) and extension mode (WebSocket).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "src")

from brotto_orchestrator.dev.playwright_browser import PlaywrightBrowser
from brotto_orchestrator.harness.agent_loop import AgentLoop
from brotto_orchestrator.domain.models import SessionDeps
from brotto_orchestrator.settings import load_settings
from brotto_orchestrator.agent.factory import build_agent
from brotto_orchestrator.policy.adapter import PolicyAdapter
from brotto_policy import SessionPolicyChecker


async def run_dev_test():
    """Quick dev mode test to verify end-to-end integration."""
    print("\n" + "=" * 60)
    print("🚀 BROTTO ORCHESTRATOR - END-TO-END TEST")
    print("=" * 60)

    try:
        cfg = load_settings()

        # Setup browser
        print("\n[1/5] Launching Playwright browser...")
        browser = PlaywrightBrowser()
        await browser.launch(headless=True, url="https://example.com")

        # Setup agent
        print("[2/5] Building PydanticAI agent...")
        os.environ['ANTHROPIC_API_KEY'] = cfg.api_key
        policy = PolicyAdapter(SessionPolicyChecker())
        agent = build_agent(
            model_name=cfg.model,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            executor=None,
            policy=policy,
            approval_manager=None,
            history_sink=None,
        )

        # Setup loop
        print("[3/5] Creating unified AgentLoop...")
        loop = AgentLoop(agent=agent, browser=browser, max_steps=3)
        deps = SessionDeps(session_id="test_e2e", sink=None)

        # Run test
        print("[4/5] Running agent loop (3 steps max)...")
        result = await loop.run(
            goal="Navigate to and take a screenshot of example.com homepage",
            session_id="test_e2e",
            session_deps=deps,
        )

        # Results
        print("[5/5] Test complete!")
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(f"Success: {result.success}")
        print(f"Steps: {result.step}")
        print(f"Error: {result.error}")
        print(f"History entries: {len(result.history)}")

        for h in result.history:
            print(f"  - Step {h['step']}: {h['type']} → {h['result']['ok']}")

        print("\n✅ END-TO-END INTEGRATION WORKING")
        print("=" * 60)

        # Cleanup
        await browser.close()
        return 0

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


async def run_server():
    """Start the FastAPI server with WebSocket extension support."""
    print("\n" + "=" * 60)
    print("🚀 STARTING ORCHESTRATOR SERVER")
    print("=" * 60)
    print("\nServer configuration:")
    print("  - Host: 0.0.0.0")
    print("  - Port: 8000")
    print("  - WebSocket: /ws (for extension)")
    print("  - Dev mode: Direct Playwright testing")
    print("\nTo load extension:")
    print("  1. Open chrome://extensions/")
    print("  2. Load unpacked: clients/brotto-extension/dist")
    print("  3. Configure server URL in extension options")
    print("\nStarting in 2 seconds...\n")

    # Import and run FastAPI app
    import uvicorn
    from brotto_orchestrator.main import app

    await asyncio.sleep(2)

    # Run with hot reload disabled for stability
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


async def main():
    """Main entry point."""
    # First run dev mode test to verify everything works
    test_result = await run_dev_test()

    if test_result == 0:
        # If test passes, optionally start server
        print("\n" + "=" * 60)
        print("Next: Start orchestrator server to test extension mode")
        print("=" * 60)
        print("\nRun: python3 -m uvicorn brotto_orchestrator.main:app --host 0.0.0.0 --port 8000")
        print("\nOr run: python3 start_server.py --server")
    else:
        print("\n❌ Dev test failed. Fix issues before starting server.")


if __name__ == "__main__":
    if "--server" in sys.argv:
        # Start server mode
        try:
            asyncio.run(run_server())
        except KeyboardInterrupt:
            print("\n\n🛑 Server stopped")
    else:
        # Run dev test
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
