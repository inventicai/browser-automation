"""Task 2 of 5: data extraction.

Sandbox: a static HTML page with a known table. The agent must
extract the data into a structured form.

The success check compares the agent's `extracted_data` against
the expected JSON. No LLM-as-judge.
"""

from __future__ import annotations

from ..spec import RunState, TaskSpec


DATA_HTML = """<!doctype html>
<html>
<head><title>Quarterly Revenue</title></head>
<body>
  <header><h1>Quarterly Revenue</h1></header>
  <main>
    <table id="revenue">
      <thead>
        <tr><th>Quarter</th><th>Revenue</th></tr>
      </thead>
      <tbody>
        <tr><td>Q1</td><td>120000</td></tr>
        <tr><td>Q2</td><td>145000</td></tr>
        <tr><td>Q3</td><td>160000</td></tr>
        <tr><td>Q4</td><td>180000</td></tr>
      </tbody>
    </table>
  </main>
</body>
</html>
"""


EXPECTED_TOTAL = 120000 + 145000 + 160000 + 180000  # 605000


def make_data_extract_task(start_url: str = "") -> TaskSpec:
    """Build the data extraction task."""

    async def success_check(state: RunState) -> bool:
        data = state.extracted_data or {}
        if not isinstance(data, dict):
            return False
        # The agent must surface the total. We accept any key that
        # carries the value 605000 — the agent can name it differently.
        return EXPECTED_TOTAL in (data.get("total"), data.get("revenue_total"), data.get("sum"))

    return TaskSpec(
        name="data_extract",
        goal=(
            "Read the table under 'Quarterly Revenue' and report the total "
            "revenue across all four quarters."
        ),
        start_url=start_url,
        success_check=success_check,
        max_steps=4,
    )


__all__ = ["DATA_HTML", "EXPECTED_TOTAL", "make_data_extract_task"]
