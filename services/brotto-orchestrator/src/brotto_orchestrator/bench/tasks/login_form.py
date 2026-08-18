"""Task 1 of 5: login form fill.

Sandbox: a static HTML page with a username + password form and a
submit button. Submission re-renders the page with a welcome banner.

The success check is purely deterministic — the URL changes after
submit, and the success banner has a stable id. No LLM-as-judge.
"""

from __future__ import annotations

from ..spec import RunState, TaskSpec


LOGIN_HTML = """<!doctype html>
<html>
<head><title>Demo Login</title></head>
<body>
  <header><h1>Demo Login</h1></header>
  <main>
    <form id="login-form" action="/welcome" method="get">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" autocomplete="username" />

      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" />

      <button id="submit" type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>
"""


WELCOME_HTML = """<!doctype html>
<html>
<head><title>Welcome</title></head>
<body>
  <header><h1>Welcome</h1></header>
  <main>
    <p id="welcome-banner">Welcome, demo!</p>
  </main>
</body>
</html>
"""


def make_login_form_task(start_url: str = "") -> TaskSpec:
    """Build the login form task. The runner supplies `start_url`."""

    async def success_check(state: RunState) -> bool:
        # After submit, the URL ends with /welcome and the body
        # contains the welcome banner. We check both — neither alone
        # is enough (URL alone could be a redirect; banner alone
        # could be present in a stale page).
        return (
            state.final_url.endswith("/welcome")
            and "Welcome, demo!" in str(state.extracted_data or "")
        )

    return TaskSpec(
        name="login_form",
        goal=(
            "Fill out the login form: type 'demo' into the username field, "
            "type 'demo123' into the password field, then click Sign in."
        ),
        start_url=start_url,
        success_check=success_check,
        max_steps=6,
    )


__all__ = ["LOGIN_HTML", "WELCOME_HTML", "make_login_form_task"]
