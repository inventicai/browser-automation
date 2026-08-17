from __future__ import annotations

from collections import Counter

from .context import StepSummary


def check_stagnation(
    summaries: list[StepSummary],
    window: int = 3,
) -> tuple[bool, str]:
    if len(summaries) < window:
        return False, ""

    recent = summaries[-window:]
    urls = [s.url for s in recent]

    # Stuck on the same page
    if len(set(urls)) == 1:
        return True, f"Stuck on {urls[0]} for {window} consecutive steps"

    # Repeating the same action
    actions = [s.action_taken for s in recent]
    most_common, count = Counter(actions).most_common(1)[0]
    if count >= window:
        return True, f"Repeated same action {window} times: '{most_common}'"

    # Consecutive find_element failures (2+ in the window)
    failed_finds = [
        s for s in recent
        if "find_element" in s.action_taken and "not found" in s.outcome.lower()
    ]
    if len(failed_finds) >= window - 1:
        return True, f"find_element failed {len(failed_finds)} consecutive times — element does not exist in AX tree"

    # URL-hopping with zero extraction (visited many pages, got nothing)
    if len(summaries) >= 5:
        window5 = summaries[-5:]
        extracted_any = any(s.extracted for s in window5)
        unique_urls = len(set(s.url for s in window5))
        if unique_urls >= 4 and not extracted_any:
            return True, f"Navigated to {unique_urls} different URLs in 5 steps with nothing extracted"

    return False, ""
