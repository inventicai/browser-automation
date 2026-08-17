"""Regression test for login-resume: the relay must surface fresh URL/title
to wait_for_redirect polls, not just serve a stale cache."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("AGENT_AUTH_DISABLED", "true")


@pytest.mark.asyncio
async def test_get_current_url_drains_pending_observation():
    """If the SW pushes a new observation (e.g. Continue click → login done),
    the next get_current_url() call must reflect it without an explicit
    get_targets() round-trip first."""
    from brotto_orchestrator.cdp.extension_relay import ExtensionCDPRelay

    obs_queue: asyncio.Queue = asyncio.Queue()
    ws_send = AsyncMock()

    relay = ExtensionCDPRelay(
        ws_send=ws_send,
        obs_queue=obs_queue,
        session_id="test",
    )

    # Prime the cache the way the agent step would.
    await obs_queue.put({"url": "https://login.example.com/", "title": "Sign in", "axTargets": []})
    await relay._get_observation()
    assert (await relay.get_current_url()) == "https://login.example.com/"
    ws_send.assert_not_called()  # first _get_observation consumed the primed item

    # SW sends a fresh observation (Continue click or webNavigation.onCommitted).
    await obs_queue.put({"url": "https://app.example.com/dashboard", "title": "Home", "axTargets": []})

    # get_current_url() must reflect it without anyone calling _get_observation
    # first — wait_for_redirect relies on this.
    new_url = await relay.get_current_url()
    assert new_url == "https://app.example.com/dashboard", (
        f"stale URL returned: {new_url!r} — relay did not drain pending observation"
    )
    assert ws_send.call_count == 0, "get_current_url must not request a new observation when one is queued"


@pytest.mark.asyncio
async def test_get_page_title_drains_pending_observation():
    """Same drain-on-read contract for title."""
    from brotto_orchestrator.cdp.extension_relay import ExtensionCDPRelay

    obs_queue: asyncio.Queue = asyncio.Queue()
    ws_send = AsyncMock()

    relay = ExtensionCDPRelay(ws_send=ws_send, obs_queue=obs_queue, session_id="test")

    await obs_queue.put({"url": "https://login.example.com/", "title": "Sign in", "axTargets": []})
    await relay._get_observation()

    await obs_queue.put({"url": "https://app.example.com/", "title": "Dashboard", "axTargets": []})

    assert (await relay.get_page_title()) == "Dashboard"


@pytest.mark.asyncio
async def test_get_current_url_no_pending_keeps_cache():
    """If nothing is queued, get_current_url should not block or request a
    new observation — it should return whatever the cache holds."""
    from brotto_orchestrator.cdp.extension_relay import ExtensionCDPRelay

    obs_queue: asyncio.Queue = asyncio.Queue()
    ws_send = AsyncMock()

    relay = ExtensionCDPRelay(ws_send=ws_send, obs_queue=obs_queue, session_id="test")

    await obs_queue.put({"url": "https://login.example.com/", "title": "Sign in", "axTargets": []})
    await relay._get_observation()

    # No new observation queued.
    url = await relay.get_current_url()
    assert url == "https://login.example.com/"
    assert ws_send.call_count == 0


# Import AsyncMock at module level so the @pytest.mark.asyncio tests above
# can use it without per-test imports.
from unittest.mock import AsyncMock  # noqa: E402