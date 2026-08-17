from __future__ import annotations

import asyncio
import re

LOGIN_SIGNALS = [
    r"sign.?in", r"log.?in", r"password", r"username",
    r"authenticate", r"sso", r"credentials",
    r"microsoft.*login", r"azure.*ad",
    r"saml", r"oauth", r"session.*expired",
]

CRITICAL_PATTERNS = [
    r"delete", r"submit.*form", r"send.*email", r"create.*ticket",
    r"approve", r"reject", r"payment", r"transfer",
    r"publish", r"deploy", r"confirm",
]

_LOGIN_RE = [re.compile(p, re.I) for p in LOGIN_SIGNALS]
_CRITICAL_RE = [re.compile(p, re.I) for p in CRITICAL_PATTERNS]


def check_login_page(page_title: str, ax_tree: str, url: str) -> bool:
    # Only check title + URL — AX tree of any authenticated page contains "sign in" in menus
    combined = f"{page_title} {url}"
    return any(r.search(combined) for r in _LOGIN_RE)


_TERMINAL = {"task_complete", "cannot_complete", "ask_human"}


def check_critical_action(action: str, action_args: dict) -> bool:
    if action in _TERMINAL:
        return False
    combined = f"{action} {action_args}"
    return any(r.search(combined) for r in _CRITICAL_RE)


async def wait_for_redirect(get_url_fn, from_url: str, timeout: int = 120) -> str:
    """Poll until URL changes from from_url. Returns new URL."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        current = await get_url_fn()
        if current != from_url:
            return current
        await asyncio.sleep(1.5)
    raise TimeoutError(f"No redirect from {from_url} after {timeout}s")
