from __future__ import annotations

import asyncio
import re


# URL path fragments that indicate a real login/auth flow.
LOGIN_URL_PATTERNS = (
    "/login", "/signin", "/auth", "/sso", "/session/",
    "/sign-in", "/log-in", "/oauth/",
)

# Strong markers in page content — these indicate a real login page.
# Anything matching here is enough when paired with a URL or title signal.
STRONG_CONTENT_MARKERS = (
    r"password",
    r"authenticate",
    r"sso",
    r"saml",
    r"oauth",
    r"azure.*ad",
    r"microsoft.*login",
)

# Weak markers in page content — "Sign in" buttons in signed-in menus,
# "credentials" mentions, etc. NEVER trigger on their own.
WEAK_CONTENT_MARKERS = (
    r"sign.?in",
    r"log.?in",
    r"username",
    r"credentials",
)

# Force-trigger: a session-expired message means the user was logged out,
# even on a page that otherwise looks normal.
_SESSION_EXPIRED_RE = re.compile(r"session.*expired", re.I)

# Patterns that match a login-flavoured page title.
_LOGIN_TITLE_RE = re.compile(r"sign.?in|log.?in|authenticate", re.I)

_STRONG_RE = [re.compile(p, re.I) for p in STRONG_CONTENT_MARKERS]


def check_login_page(page_title: str, ax_tree: str, url: str) -> bool:
    """Detect a login page. Returns True when the agent should pause for login.

    Title and URL are each independently authoritative — a page titled
    "Sign in" IS a login page, and a URL on a known login path is too.

    An AX-tree STRONG marker alone is NOT sufficient: "password" appears
    on Google Search via the password manager, "oauth" appears in Gmail
    from analytics/integration tags, and "Sign in" links live in headers
    of already-signed-in pages like GitHub. Firing on those yields a
    false-positive login pause mid-task. A strong marker only counts
    when paired with corroboration from title or URL.

    "Session expired" in the content force-triggers regardless, since
    that means the user was logged out from a modal on the current page.
    """
    # Force-trigger: session expired is unambiguous.
    if _SESSION_EXPIRED_RE.search(ax_tree):
        return True

    # Page title is authoritative — a login page is titled "Sign in" / "Log in".
    if _LOGIN_TITLE_RE.search(page_title):
        return True

    # URL on a known login path is authoritative.
    url_lower = url.lower()
    if any(p in url_lower for p in LOGIN_URL_PATTERNS):
        return True

    # AX tree strong marker alone is too noisy — require corroboration.
    # If title/URL above matched, we already returned True; reaching here
    # means neither matched, so a lone "password" / "oauth" / etc. is
    # treated as incidental and does not pause the agent.
    if any(r.search(ax_tree) for r in _STRONG_RE):
        if _LOGIN_TITLE_RE.search(page_title):
            return True
        if any(p in url_lower for p in LOGIN_URL_PATTERNS):
            return True
        return False

    return False


CRITICAL_PATTERNS = [
    r"delete", r"submit.*form", r"send.*email", r"create.*ticket",
    r"approve", r"reject", r"payment", r"transfer",
    r"publish", r"deploy", r"confirm",
]

_CRITICAL_RE = [re.compile(p, re.I) for p in CRITICAL_PATTERNS]


def check_critical_action(action: str, action_args: dict) -> bool:
    if action in {"task_complete", "cannot_complete", "ask_human"}:
        return False
    combined = f"{action} {action_args}"
    return any(r.search(combined) for r in _CRITICAL_RE)


def check_sensitive_action(action: str, action_args: dict, policy) -> bool:
    """True iff secure mode is on AND the action matches an entry in
    `policy.sensitive_actions`. The list is matched as a substring against
    either the action name or any string in action_args — admins author
    both forms (``"payment"`` matches a ``payment`` action OR a click
    with ``description="payment button"``).

    Normal mode → always False (the regex `CRITICAL_PATTERNS` guard above
    still applies; sensitive_actions is the secure-mode-only escalation).

    Terminal / internal / question actions are skipped — those are
    metadata, not things the user should approve. (E.g. a click with
    description matching `payment` should fire; but a scratchpad write
    whose notes happen to mention "payment" should not.)
    """
    if getattr(policy, "mode", None) != "secure":
        return False
    patterns = getattr(policy, "sensitive_actions", None) or []
    if not patterns:
        return False
    if action in {"task_complete", "cannot_complete", "ask_human",
                  "write_scratchpad", "append_scratchpad", "read_scratchpad",
                  "recall_memory", "read_page_text"}:
        return False
    # Match against action name + arg values joined into one string.
    # Cheap substring scan; no regex needed for the curated list.
    haystack = " ".join([action] + [str(v) for v in action_args.values()]).lower()
    return any(p.lower() in haystack for p in patterns)


async def wait_for_redirect(get_url_fn, from_url: str, timeout: int = 120) -> str:
    """Poll until URL changes from from_url. Returns new URL."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        current = await get_url_fn()
        if current != from_url:
            return current
        await asyncio.sleep(1.5)
    raise TimeoutError(f"No redirect from {from_url} after {timeout}s")
