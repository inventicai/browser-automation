"""Task 3 of 5: multi-step workflow.

Sandbox: a two-step page. Step 1 is a 'Continue' button on a
landing page. Step 2 is a form that requires a name.

The agent must:
1. Click Continue.
2. On the form page, type a name into the input.
3. Click Submit.

The success check confirms the URL ended with /submitted and the
extracted data carries the typed name.
"""

from __future__ import annotations

from ..spec import RunState, TaskSpec


LANDING_HTML = """<!doctype html>
<html>
<head><title>Welcome</title></head>
<body>
  <header><h1>Welcome</h1></header>
  <main>
    <p>Click continue to proceed.</p>
    <button id="continue">Continue</button>
  </main>
</body>
</html>
"""


FORM_HTML = """<!doctype html>
<html>
<head><title>Form</title></head>
<body>
  <header><h1>Fill the form</h1></header>
  <main>
    <form id="form" action="/submitted" method="get">
      <label for="name">Name</label>
      <input id="name" name="name" type="text" />
      <button id="submit" type="submit">Submit</button>
    </form>
  </main>
</body>
</html>
"""


def make_multi_step_task(start_url: str = "") -> TaskSpec:
    """Build the multi-step task."""

    async def success_check(state: RunState) -> bool:
        data = state.extracted_data or {}
        # The form posts to /submitted with ?name=<value>. The agent
        # must surface the typed name in its terminal payload.
        if not isinstance(data, dict):
            return False
        name = data.get("name") or data.get("typed_name")
        # URL ends with /submitted (with or without query string).
        url_ok = (
            state.final_url.endswith("/submitted")
            or "/submitted?" in state.final_url
        )
        return bool(name) and url_ok

    return TaskSpec(
        name="multi_step",
        goal=(
            "Click the 'Continue' button on the page, then on the next page "
            "type 'casey' into the Name field and press Submit."
        ),
        start_url=start_url,
        success_check=success_check,
        max_steps=8,
    )


__all__ = ["LANDING_HTML", "FORM_HTML", "make_multi_step_task"]
