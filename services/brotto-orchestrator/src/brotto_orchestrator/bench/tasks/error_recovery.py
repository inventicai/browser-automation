"""Task 4 of 5: error recovery.

Sandbox: a page with a button that is initially disabled. The agent
must discover the disabled state and find a way to unlock it
(by checking the adjacent toggle), then click the button.

This stresses the agent's ability to observe state, recover from
an attempted action that didn't work, and try alternatives.
"""

from __future__ import annotations

from ..spec import RunState, TaskSpec


RECOVERY_HTML = """<!doctype html>
<html>
<head><title>Trial</title></head>
<body>
  <header><h1>Free trial</h1></header>
  <main>
    <p>Start your free trial by enabling the toggle, then clicking the button.</p>
    <label>
      <input id="toggle" type="checkbox" />
      Enable
    </label>
    <button id="start" disabled>Start trial</button>
  </main>
</body>
</html>
"""


def make_error_recovery_task(start_url: str = "") -> TaskSpec:
    """Build the error recovery task."""

    async def success_check(state: RunState) -> bool:
        # The agent must surface that the button was clicked. The
        # exact key is allowed to vary. We accept any of:
        #   {"clicked": True}, {"button": "clicked"}, {"trial_started": True}
        data = state.extracted_data or {}
        if not isinstance(data, dict):
            return False
        return bool(
            data.get("clicked")
            or data.get("trial_started")
            or data.get("button") == "clicked"
        )

    return TaskSpec(
        name="error_recovery",
        goal=(
            "Click the 'Start trial' button. If it is disabled, find the "
            "toggle that enables it and toggle it first, then click again."
        ),
        start_url=start_url,
        success_check=success_check,
        max_steps=6,
    )


__all__ = ["RECOVERY_HTML", "make_error_recovery_task"]
