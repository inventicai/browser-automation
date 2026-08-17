from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..dev.ax_tree_extractor import SemanticTarget

KEEP_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox",
    "checkbox", "radio", "menuitem", "tab", "listitem",
    "heading", "dialog", "alert", "form", "main", "nav",
    "option", "switch", "slider", "spinbutton", "gridcell",
}

STRIP_ROLES = {"generic", "none", "presentation", "separator"}

MAX_CHARS = 6000
ROW_Y_THRESHOLD = 30  # px — elements within this y-band are considered "same row"


def _group_by_row(targets: list["SemanticTarget"]) -> dict[int, list["SemanticTarget"]]:
    """Bucket targets into horizontal bands by y-coordinate.

    Elements with similar y-coordinates (within ROW_Y_THRESHOLD) are grouped together.
    Returns a dict mapping canonical y-coordinate to list of targets in that row.
    """
    rows: dict[int, list["SemanticTarget"]] = {}
    for t in targets:
        if not t.coordinates:
            continue
        cy = t.coordinates.get("y", 0)
        # Find existing band within threshold
        matched = False
        for band_y in sorted(rows.keys()):
            if abs(cy - band_y) <= ROW_Y_THRESHOLD:
                rows[band_y].append(t)
                matched = True
                break
        if not matched:
            rows[cy] = [t]
    return rows


def _compute_annotations(targets: list["SemanticTarget"]) -> dict[str, str]:
    """Compute action annotations for elements in list/table rows.

    Strategy: mark all checkboxes in list contexts as [☐ select-only].
    In lists/tables with links/buttons, checkboxes are bulk-select controls, not openers.
    """
    annotations: dict[str, str] = {}

    # Detect list context: multiple rows or list-like roles
    has_list_items = any(t.role.lower() in ("listitem", "option", "gridcell", "row") for t in targets)
    has_links_or_buttons = any(t.role.lower() in ("link", "button") for t in targets)
    is_list_context = has_list_items or (has_links_or_buttons and len(targets) > 3)

    if is_list_context:
        # In list context, mark ALL checkboxes as select-only
        for t in targets:
            if t.role.lower() == "checkbox":
                annotations[t.ref_id] = "[☐ select-only]"
            elif t.role.lower() in ("link", "button") and t.name:
                annotations[t.ref_id] = "[→ open]"
    else:
        # In non-list contexts, use spatial grouping
        rows = _group_by_row(targets)
        for row_members in rows.values():
            checkboxes = [t for t in row_members if t.role.lower() == "checkbox"]
            openers = [t for t in row_members
                       if t.role.lower() in ("link", "button", "listitem", "gridcell")]
            if checkboxes and openers:
                for t in openers:
                    annotations[t.ref_id] = "[→ open]"
                for t in checkboxes:
                    annotations[t.ref_id] = "[☐ select-only]"

    return annotations


def filter_ax_targets(
    targets: list["SemanticTarget"],
    viewport_coords: tuple[int, int, int, int] | None = None,
) -> str:
    """Filter SemanticTargets to a token-capped AX tree string.

    viewport_coords: (x, y, width, height) bounding box — elements outside are marked off-screen.

    Elements are annotated to clarify their action:
    - [→ open] — primary action for this row (click to open/select the item)
    - [☐ select-only] — bulk-selection control (never opens the item)
    """
    # Compute spatial annotations (marks primary actions and selection controls)
    annotations = _compute_annotations(targets)

    # Fallback suppression for elements without coordinates (extension path).
    # Keep the name-match heuristic as a secondary guard.
    has_list_rows = any(t.role.lower() in ("listitem", "option", "gridcell", "row") for t in targets)
    link_names = {t.name.lower() for t in targets if t.role.lower() == "link" and t.name}
    shadow_checkboxes = {
        t.ref_id for t in targets
        if t.role.lower() == "checkbox"
        and not t.coordinates  # only suppress if no y-coordinate available
        and t.name and t.name.lower() in link_names
        and has_list_rows
    }

    lines: list[str] = []
    offscreen: list[str] = []

    for t in targets:
        if t.ref_id in shadow_checkboxes:
            continue
        role = t.role.lower()
        if role in STRIP_ROLES:
            continue
        if not t.name and not t.value:
            continue  # unactionable — no text to describe or click target
        if role not in KEEP_ROLES:
            continue

        line = f"[{t.ref_id}] {role}"
        if t.name:
            line += f' "{t.name[:80]}"'
        if t.value:
            line += f' value="{str(t.value)[:80]}"'
        # Append action annotation if computed
        ann = annotations.get(t.ref_id)
        if ann:
            line += f"  {ann}"

        if viewport_coords and t.coordinates:
            vx, vy, vw, vh = viewport_coords
            cx, cy = t.coordinates.get("x", 0), t.coordinates.get("y", 0)
            in_viewport = vx <= cx <= vx + vw and vy <= cy <= vy + vh
            if not in_viewport:
                offscreen.append(f"[off-screen] {line}")
                continue

        lines.append(line)

    result = "\n".join(lines)
    remaining = MAX_CHARS - len(result)
    if remaining > 0 and offscreen:
        off_block = "\n".join(offscreen)[:remaining - 1]
        result = result + "\n" + off_block

    if len(result) >= MAX_CHARS:
        result = result[:MAX_CHARS] + "\n[tree truncated — scroll to reveal more]"

    return result
