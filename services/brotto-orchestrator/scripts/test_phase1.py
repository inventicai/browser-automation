#!/usr/bin/env python3
"""Test Phase 1: Agent Harness + AX Tree Extraction + Context Management."""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "services/brotto-orchestrator/src")

from brotto_orchestrator.dev.ax_tree_extractor import AXTreeExtractor, SemanticTarget
from brotto_orchestrator.context.manager import ContextManager
from brotto_orchestrator.context.builder import build_context


async def test_ax_tree_extraction():
    """Test CDP AX tree extraction with real browser."""
    print("\n=== Test 1: CDP AX Tree Extraction ===")

    try:
        from brotto_orchestrator.dev.playwright_browser import PlaywrightBrowser

        browser = PlaywrightBrowser()
        await browser.launch(headless=True, url="https://example.com")

        obs = await browser.screenshot_to_observation()

        print(f"✓ Observation created")
        print(f"  - URL: {obs.url}")
        print(f"  - Title: {obs.title}")
        print(f"  - Targets extracted: {len(obs.semantic_targets or [])}")

        if obs.semantic_targets:
            for target in obs.semantic_targets[:3]:
                print(f"    [{target['ref_id']}] {target['tag']} ({target['role']}) - {target['name']}")

        await browser.close()
        print("✓ Test 1 PASSED\n")
        return True

    except Exception as e:
        print(f"✗ Test 1 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_context_management():
    """Test context formatting and token budgeting."""
    print("=== Test 2: Context Management ===")

    try:
        # Sample observation
        obs = {
            "url": "https://example.com/login",
            "title": "Login Page",
            "semantic_targets": [
                {
                    "ref_id": "input_email_1",
                    "tag": "input",
                    "role": "textbox",
                    "name": "Email",
                    "coordinates": {"x": 200, "y": 150},
                },
                {
                    "ref_id": "input_password_2",
                    "tag": "input",
                    "role": "textbox",
                    "name": "Password",
                    "coordinates": {"x": 200, "y": 200},
                },
                {
                    "ref_id": "button_submit_3",
                    "tag": "button",
                    "role": "button",
                    "name": "Sign In",
                    "coordinates": {"x": 200, "y": 250},
                },
            ],
        }

        # Sample history
        history = [
            {"step": 1, "type": "visit_url", "result": {"ok": True}},
            {
                "step": 2,
                "type": "left_click",
                "result": {"ok": True, "error": None},
            },
        ]

        memory = {"user_email": "test@example.com"}
        goal = "Login to the website"

        # Build context
        context = build_context(
            observation=obs,
            history=history,
            memory=memory,
            goal=goal,
        )

        print(f"✓ Context built successfully")
        print(f"  - Length: {len(context)} characters")

        tokens = ContextManager.estimate_tokens(context)
        print(f"  - Estimated tokens: {tokens}")

        # Test token budgeting
        print(f"  - Token budget: {ContextManager.TOKEN_BUDGET_TOTAL}")
        remaining = ContextManager.TOKEN_BUDGET_TOTAL - tokens
        print(f"  - Remaining: {remaining} tokens")

        if remaining > 0:
            print("✓ Test 2 PASSED\n")
            return True
        else:
            print("✗ Context exceeds token budget\n")
            return False

    except Exception as e:
        print(f"✗ Test 2 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_semantic_target_model():
    """Test SemanticTarget data structure."""
    print("=== Test 3: Semantic Target Model ===")

    try:
        target = SemanticTarget(
            ref_id="button_submit_1",
            tag="button",
            role="button",
            name="Sign In",
            coordinates={"x": 250, "y": 300},
            backend_node_id=42,
        )

        print(f"✓ SemanticTarget created")
        print(f"  - ref_id: {target.ref_id}")
        print(f"  - role: {target.role}")
        print(f"  - name: {target.name}")
        print(f"  - coordinates: {target.coordinates}")
        print("✓ Test 3 PASSED\n")
        return True

    except Exception as e:
        print(f"✗ Test 3 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all Phase 1 tests."""
    print("\n" + "=" * 60)
    print("PHASE 1 TEST SUITE")
    print("=" * 60)

    results = []

    # Test 1: CDP AX Tree Extraction
    results.append(await test_ax_tree_extraction())

    # Test 2: Context Management
    results.append(test_context_management())

    # Test 3: Semantic Target Model
    results.append(test_semantic_target_model())

    # Summary
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)

    if passed == total:
        print("\n✅ Phase 1 READY FOR PHASE 2\n")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Fix before Phase 2.\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
