"""Tests for the login form task."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from brotto_orchestrator.bench.spec import RunState  # noqa: E402
from brotto_orchestrator.bench.tasks.login_form import (  # noqa: E402
    LOGIN_HTML,
    WELCOME_HTML,
    make_login_form_task,
)


@pytest.mark.asyncio
async def test_success_check_passes_when_url_and_banner_match():
    task = make_login_form_task()
    state = RunState(
        final_url="http://127.0.0.1:8090/welcome",
        extracted_data={"page_text": "Welcome, demo!"},
    )
    assert await task.success_check(state) is True


@pytest.mark.asyncio
async def test_success_check_fails_when_url_is_wrong():
    task = make_login_form_task()
    state = RunState(
        final_url="http://127.0.0.1:8090/",
        extracted_data={"page_text": "Welcome, demo!"},
    )
    assert await task.success_check(state) is False


@pytest.mark.asyncio
async def test_success_check_fails_without_banner():
    task = make_login_form_task()
    state = RunState(
        final_url="http://127.0.0.1:8090/welcome",
        extracted_data={"page_text": "Bad credentials"},
    )
    assert await task.success_check(state) is False


@pytest.mark.asyncio
async def test_success_check_requires_extracted_data():
    """If the agent didn't extract anything, the check fails."""
    task = make_login_form_task()
    state = RunState(final_url="http://127.0.0.1:8090/welcome", extracted_data=None)
    assert await task.success_check(state) is False


def test_login_html_has_required_fields():
    """The sandbox must expose the fields the agent will type into."""
    assert 'id="username"' in LOGIN_HTML
    assert 'id="password"' in LOGIN_HTML
    assert 'id="submit"' in LOGIN_HTML


def test_welcome_html_has_stable_banner():
    """The success check depends on the banner id."""
    assert 'id="welcome-banner"' in WELCOME_HTML
    assert "Welcome, demo!" in WELCOME_HTML


def test_task_has_typed_goal():
    """The goal must give the agent enough to act without ambiguity."""
    task = make_login_form_task()
    assert "demo" in task.goal
    assert "demo123" in task.goal
    assert "Sign in" in task.goal or "submit" in task.goal.lower()
