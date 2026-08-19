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

    Each of the three signals is independently sufficient on its own:
      - URL on a known login/auth path (e.g. /login, /signin, /sso)
      - Page title matches a login phrase (e.g. "Sign in", "Log in")
      - Content has a STRONG marker (password, authenticate, sso, etc.)

    The previous heuristic combined all three into one string and ran a
    single regex against the whole thing, so any "Sign in" button in a
    signed-in page's header would trigger the login pause. The new rule
    keeps the page title and the URL as authoritative signals (a page
    titled "Sign in" IS a login page) but treats "Sign in" inside the AX
    tree as a weak marker — common in headers of signed-in pages like
    GitHub — and requires a strong marker to fire from the AX tree alone.

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

    # AX tree alone requires a strong marker (password, authenticate, sso…).
    # "Sign in" buttons in headers are weak and don't count.
    if any(r.search(ax_tree) for r in _STRONG_RE):
        return True

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


async def wait_for_redirect(get_url_fn, from_url: str, timeout: int = 120) -> str:
    """Poll until URL changes from from_url. Returns new URL."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        current = await get_url_fn()
        if current != from_url:
            return current
        await asyncio.sleep(1.5)
    raise TimeoutError(f"No redirect from {from_url} after {timeout}s")
