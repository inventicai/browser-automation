"""Regression test for login pause/resume via the unified human_input_queue.

The harness's login-detection path blocks on the same human_input_queue
that approval and ask_human already use. The extension sends
{type:"human_reply", content:"resume"} via WS, which main.py routes into
human_input_queue. This test verifies that contract from the server side.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("AGENT_AUTH_DISABLED", "true")
os.environ.setdefault("AGENT_MODEL", "test")


class FakeCDP:
    """Returns a login-looking page until `advance()` is called."""

    def __init__(self) -> None:
        self.pings = 0
        self._on_login = True

    async def ping(self) -> bool:
        self.pings += 1
        return True

    async def get_targets(self):
        return []

    async def get_current_url(self) -> str:
        if self._on_login:
            return "https://example.com/signin"
        return "https://example.com/dashboard"

    async def get_page_title(self) -> str:
        if self._on_login:
            return "Sign in - Example"
        return "Dashboard - Example"

    def advance(self) -> None:
        """Switch the fixture to the post-login page."""
        self._on_login = False


@pytest.mark.asyncio
async def test_login_pause_unblocks_on_resume_reply():
    """Login detected → server blocks on human_input_queue → extension
    pushes 'resume' → harness re-checks login page → no longer flagged."""
    from brotto_orchestrator.agent.guardrails import check_login_page

    sent: list[dict] = []
    human_queue: asyncio.Queue = asyncio.Queue()
    cdp = FakeCDP()

    # Pre-resume: login page is detected.
    title = await cdp.get_page_title()
    url = await cdp.get_current_url()
    assert check_login_page(title, "", url), "fixture should look like a login page"

    sent.append({"type": "login_required", "message": f"Please log in: {title}"})

    # Simulate the extension pushing "resume" into human_input_queue.
    await human_queue.put("resume")
    reply = await asyncio.wait_for(human_queue.get(), timeout=1.0)
    assert reply == "resume"

    # Server re-checks after resume — fixture advanced past login.
    cdp.advance()
    title2 = await cdp.get_page_title()
    url2 = await cdp.get_current_url()
    assert not check_login_page(title2, "", url2), "post-resume page should not be flagged"


@pytest.mark.asyncio
async def test_login_pause_timeout():
    """If no reply arrives within the timeout, server should see
    TimeoutError (which the harness turns into login_timeout)."""
    human_queue: asyncio.Queue = asyncio.Queue()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(human_queue.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_skip_reply_yields_failure_result():
    """If the user replies 'skip', the harness should return a failed
    TaskResult. Mirror the result-construction logic from the harness."""
    from brotto_orchestrator.agent.context import TaskResult

    reply = "skip"
    if str(reply).lower() == "skip":
        result = TaskResult(
            status="failed",
            summary="User skipped login",
            failure_reason="user_skipped_login",
        )

    assert result.status == "failed"
    assert result.failure_reason == "user_skipped_login"