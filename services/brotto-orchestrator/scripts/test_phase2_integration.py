#!/usr/bin/env python3
"""Test Phase 2: Unified BrowserInterface with dev + extension modes."""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "services/brotto-orchestrator/src")

from brotto_orchestrator.dev.playwright_browser import PlaywrightBrowser
from brotto_orchestrator.dev.websocket_browser import WebSocketBrowser
from brotto_orchestrator.domain.models import SessionDeps, ActionResult
from brotto_orchestrator.contracts import ObservationV1


async def test_playwright_mode():
    """Test dev mode: PlaywrightBrowser implements BrowserInterface."""
    print("\n=== Test 1: Dev Mode (Playwright) ===")

    try:
        browser = PlaywrightBrowser()
        await browser.launch(headless=True, url="https://example.com")

        # Test observe()
        obs = await browser.observe()
        print(f"✓ observe() works")
        print(f"  - URL: {obs.url}")
        print(f"  - Title: {obs.title}")
        print(f"  - Targets: {len(obs.semantic_targets or [])}")

        # Test execute() with ActionResult
        action = {"type": "scroll", "direction": "down"}
        deps = SessionDeps(session_id="test", sink=None)
        result = await browser.execute(action, deps)
        print(f"✓ execute() returns ActionResult")
        print(f"  - ok: {result.ok}")
        print(f"  - error: {result.error}")

        await browser.close()
        print("✓ Test 1 PASSED\n")
        return True

    except Exception as e:
        print(f"✗ Test 1 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


async def test_websocket_mock_mode():
    """Test extension mode: WebSocketBrowser with mock callbacks."""
    print("=== Test 2: Extension Mode (WebSocket Mock) ===")

    try:
        # Mock observation from extension
        mock_obs = ObservationV1.model_construct(
            observation_id="obs_ext_123",
            sequence=1,
            payload={},
            url="https://test.com",
            title="Test Page",
            semantic_targets=[
                {
                    "ref_id": "button_1",
                    "tag": "button",
                    "role": "button",
                    "name": "Click Me",
                    "coordinates": {"x": 100, "y": 50},
                }
            ],
            timestamp=None,
        )

        # Mock action result from extension
        mock_action_result = {
            "ok": True,
            "ref_id": "button_1",
            "evidence": "clicked successfully",
        }

        # Create WebSocketBrowser with mock callbacks
        async def mock_send_action(action):
            print(f"  [mock] extension received action: {action['type']}")
            return mock_action_result

        async def mock_receive_observation():
            print(f"  [mock] extension sent observation from {mock_obs.url}")
            return mock_obs

        browser = WebSocketBrowser(
            session_id="test_ext",
            send_action_fn=mock_send_action,
            receive_observation_fn=mock_receive_observation,
        )

        # Test observe()
        obs = await browser.observe()
        print(f"✓ observe() receives from extension")
        print(f"  - URL: {obs.url}")
        print(f"  - Targets: {len(obs.semantic_targets or [])}")

        # Test execute()
        action = {"type": "left_click", "target_id": "button_1"}
        deps = SessionDeps(session_id="test_ext", sink=None)
        result = await browser.execute(action, deps)
        print(f"✓ execute() sends to extension")
        print(f"  - ok: {result.ok}")
        print(f"  - ref_id: {result.ref_id}")

        await browser.close()
        print("✓ Test 2 PASSED\n")
        return True

    except Exception as e:
        print(f"✗ Test 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


async def test_interface_compatibility():
    """Verify both implement BrowserInterface correctly."""
    print("=== Test 3: BrowserInterface Compatibility ===")

    try:
        from brotto_orchestrator.browser_interface import BrowserInterface

        # Check PlaywrightBrowser
        assert issubclass(PlaywrightBrowser, BrowserInterface), "PlaywrightBrowser not BrowserInterface"
        print(f"✓ PlaywrightBrowser implements BrowserInterface")

        # Check WebSocketBrowser
        assert issubclass(WebSocketBrowser, BrowserInterface), "WebSocketBrowser not BrowserInterface"
        print(f"✓ WebSocketBrowser implements BrowserInterface")

        # Verify methods exist
        pb = PlaywrightBrowser()
        assert hasattr(pb, "observe"), "PlaywrightBrowser missing observe()"
        assert hasattr(pb, "execute"), "PlaywrightBrowser missing execute()"
        assert hasattr(pb, "close"), "PlaywrightBrowser missing close()"
        print(f"✓ PlaywrightBrowser has all required methods")

        wsb = WebSocketBrowser("test", lambda x: None, lambda: None)
        assert hasattr(wsb, "observe"), "WebSocketBrowser missing observe()"
        assert hasattr(wsb, "execute"), "WebSocketBrowser missing execute()"
        assert hasattr(wsb, "close"), "WebSocketBrowser missing close()"
        print(f"✓ WebSocketBrowser has all required methods")

        print("✓ Test 3 PASSED\n")
        return True

    except Exception as e:
        print(f"✗ Test 3 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


async def main() -> None:
    """Run Phase 2 integration tests."""
    print("\n" + "=" * 60)
    print("PHASE 2 INTEGRATION TEST SUITE")
    print("=" * 60)

    results = []

    # Test 1: Playwright dev mode
    results.append(await test_playwright_mode())

    # Test 2: WebSocket extension mode
    results.append(await test_websocket_mock_mode())

    # Test 3: Interface compatibility
    results.append(await test_interface_compatibility())

    # Summary
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)

    if passed == total:
        print("\n✅ Phase 2 Integration READY\n")
        print("Next: Wire WebSocket transport + run full end-to-end evals")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
