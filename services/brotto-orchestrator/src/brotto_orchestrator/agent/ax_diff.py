from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..dev.ax_tree_extractor import SemanticTarget

MAX_DIFF_CHARS = 800


def compute_ax_diff(prev: list["SemanticTarget"], curr: list["SemanticTarget"]) -> str:
    if not prev:
        return ""

    prev_map = {t.ref_id: t for t in prev}
    curr_map = {t.ref_id: t for t in curr}

    added = [t for ref, t in curr_map.items() if ref not in prev_map and (t.name or t.value)]
    removed = [t for ref, t in prev_map.items() if ref not in curr_map and (t.name or t.value)]
    modified = [
        (prev_map[ref], curr_map[ref])
        for ref in prev_map
        if ref in curr_map and (
            prev_map[ref].name != curr_map[ref].name
            or str(prev_map[ref].value) != str(curr_map[ref].value)
        )
        and (curr_map[ref].name or curr_map[ref].value)
    ]

    if not added and not removed and not modified:
        return "(no changes detected)"

    lines: list[str] = []
    for t in added[:10]:
        lines.append(f"  + [{t.ref_id}] {t.role} \"{t.name or t.value}\"")
    for t in removed[:10]:
        lines.append(f"  - [{t.ref_id}] {t.role} \"{t.name or t.value}\"")
    for old, new in modified[:10]:
        old_text = old.name or str(old.value)
        new_text = new.name or str(new.value)
        lines.append(f"  ~ [{new.ref_id}] {new.role} \"{old_text}\" → \"{new_text}\"")

    result = "\n".join(lines)
    if len(result) > MAX_DIFF_CHARS:
        result = result[:MAX_DIFF_CHARS] + "\n  [diff truncated]"
    return result
