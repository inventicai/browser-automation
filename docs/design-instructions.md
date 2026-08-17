# Inventic Design Instructions

> Internal design language for the Brotto extension UI. Derived from the
> Inventic Brand Guidelines One Pager (v1.0). All future UI changes in this
> project should follow these rules.

---

## 1. Brand at a Glance

- **Inventic Blue** is the primary brand color. Use it for primary actions, links, active states, and the wordmark.
- **Light Blue** is the accent. Use it for highlights, secondary surfaces, and the secondary peak of the brand mark.
- **White** is the canvas. The side panel is white-first.
- **Dark Text** (`#1A1A1A`) is the default body text.
- The brand mark is a **mountain peak** — a primary blue triangle with a smaller light-blue triangle overlaying its right side. Never redraw it as a flat icon, a letter, or one solid shape.

The brand feels **clean, confident, technical, and quiet**. The product is a power tool — the UI should not compete with the work the agent is doing.

---

## 2. Color Tokens

### Primary

| Token                  | Value                | Use                                              |
| ---------------------- | -------------------- | ------------------------------------------------ |
| `--brand-primary`      | `#0052CC`            | Primary buttons, links, brand wordmark, badges   |
| `--brand-primary-hover`| `#003D99`            | Hovered/pressed primary buttons                  |
| `--brand-primary-soft` | `rgba(0,82,204,0.10)`| Focus halos, filled secondary states, soft chips |
| `--brand-light`        | `#6DB3D8`            | Accents, scrollbar hover, secondary peak, soft pills |
| `--brand-light-soft`   | `rgba(109,179,216,0.16)` | Connecting / reconnecting status pills        |
| `--brand-deep`         | `#003D99`            | Hover text on light-blue surfaces                |
| `--brand-navy`         | `#001A4D`            | Overlays (settings backdrop)                     |

### Neutrals (white-first)

| Token            | Value     | Use                              |
| ---------------- | --------- | -------------------------------- |
| `--bg`           | `#FFFFFF` | Page background                  |
| `--surface`      | `#FFFFFF` | Cards, bubbles, header           |
| `--surface-1`    | `#F8FAFC` | Subtle alt surfaces (input bg)   |
| `--surface-2`    | `#EEF3F8` | Step details, hints, soft chips  |
| `--surface-3`    | `#E2EAF2` | Hover state on `--surface-2`     |
| `--border`       | `#D9E2EC` | All dividers                     |
| `--border-soft`  | `#E8EEF4` | Inner borders on cards           |
| `--text`         | `#1A1A1A` | Default body text                |
| `--text-muted`   | `#5A6877` | Secondary text, labels           |
| `--text-faint`   | `#94A2B0` | Tertiary, hints, placeholders    |

### Status (kept distinct from brand)

| Token         | Value                | Use                       |
| ------------- | -------------------- | ------------------------- |
| `--green`     | `#16A34A`            | Success, focused, done    |
| `--green-soft`| `rgba(22,163,74,0.10)`                          |
| `--red`       | `#DC2626`            | Error, stop, denied       |
| `--red-soft`  | `rgba(220,38,38,0.10)`                          |
| `--amber`     | `#D97706`            | Approval needed, paused   |
| `--amber-soft`| `rgba(217,119,6,0.10)`                          |

> **Rule:** Never use a status color as a brand color. Never use brand blue for "error" or "warning" — the user needs to distinguish at a glance.

### Translucent overlays

Use `rgba(0, 26, 77, 0.40)` (brand navy at 40%) for modals/backdrops, not pure black. This keeps the brand feel.

---

## 3. Typography

| Style           | Family       | Weight       | Size          | Notes                           |
| --------------- | ------------ | ------------ | ------------- | ------------------------------- |
| Wordmark        | **Poppins**  | 700          | 17px          | Brand name in header            |
| Page heading    | **Poppins**  | 700          | 18px          | Empty-state title               |
| Badge / label   | **Poppins**  | 700          | 9–10px        | All-caps, `letter-spacing: 0.05–0.08em` |
| Body            | **Inter**    | 400–500      | 13–14px       | Default paragraph text          |
| Meta / footnote | **Inter**    | 500          | 11–12px       | Status captions                 |
| Mono code       | ui-monospace | 400          | 11–12px       | URLs, facts, step details       |

**Rules:**

- **Headings, badges, and labels** always use Poppins, always with a positive letter-spacing.
- **Body text** always uses Inter.
- **Minimum text size is 11px.** Never go below 11px on text — even meta and hints.
- For empty states, the title is 18px Poppins Bold in `--brand-primary`. The subtitle is 13px Inter Regular in `--text-muted`.
- Section labels (e.g. "Steps", "Time") are uppercased Poppins 600 at 10px with `letter-spacing: 0.05em`.

---

## 4. The Brand Mark

The mountain mark is two triangles:

```svg
<svg viewBox="0 0 32 32">
  <path d="M5 24 L14 8 L18 14 L23 19 L26 22 Z" fill="#0052CC"/>
  <path d="M18 14 L23 19 L26 22 L24 22 L19 18 Z" fill="#6DB3D8"/>
</svg>
```

**Single source of truth:** `clients/brotto-extension/src/assets/icon.svg`. The same geometry is reused inline in `sidepanel.html` for the header and empty-state marks. If you change the mountain, update the SVG and rebuild — the build script renders PNGs at 16/32/48/128 for the extension icon.

**Sizes (in-app):**

- Header: 24×24 px
- Empty state: 56×56 px (use the `--lg` modifier class)

**Sizes (extension icon):**

- 16×16 (toolbar)
- 32×32 (Windows/HiDPI toolbar)
- 48×48 (extension management page)
- 128×128 (install + Chrome Web Store)

**Rules:**

- Never place the mark on a busy background without a white container.
- Never animate the mark.
- Never recolor — the two blues are the brand identity.
- The toolbar icon is the same mountain as the in-app marks — don't deviate.

---

## 5. Component Patterns

### Buttons

| Variant    | Background       | Border               | Text      | Use                                  |
| ---------- | ---------------- | -------------------- | --------- | ------------------------------------ |
| Primary    | `--brand-primary`| `--brand-primary`    | `#fff`    | "Approve", "Send", "New task" (CTA)  |
| Secondary  | `--surface-2`    | `--border`           | `--text`  | "Make changes", "Skip"               |
| Danger     | `--red-soft`     | `rgba(220,38,38,0.25)` | `--red` | "Deny", "Stop"                       |
| Icon       | transparent      | transparent          | `--text-muted` | Settings, close, tab actions    |

- Primary button hover: `--brand-primary-hover` + 1px lift + soft shadow.
- All buttons: 6px radius, 12px text, 6–6.5 weight 600.
- Disabled: 0.4 opacity, `cursor: not-allowed`.

### Bubbles

- **User bubble:** `--brand-primary` background, white text. Asymmetric — bottom-right corner is sharper (`--radius-sm`).
- **Assistant bubble:** `--surface` background, subtle border, soft shadow. Asymmetric — bottom-left corner is sharper.
- All bubbles: 11×14px padding, 14px radius on the three "round" corners.

### Cards (plan / approval / clarify)

- 14px radius, 1px `--border`, soft shadow.
- **Approval** has a 3px amber left border + amber badge. Signals "this needs you."
- **Clarify** has a 3px brand primary left border + brand badge. Signals "this is from the agent."
- **Plan** has no border accent, just a brand-colored badge.

### Status pill (header)

- 999px radius (pill), Poppins 700, 10px, uppercase, `letter-spacing: 0.05em`.
- Color varies by phase (see Status table). Always has a 1px border matching the soft color.

### Inputs

- 10px radius, 1px `--border`, focus ring = 3px brand-primary-soft.
- Goal composer: 14px Inter, 11×13px padding, 44px min height (taller than default — feels intentional).

### Status bar (steps + time)

- Two-column grid, labels uppercase Poppins 10px, values in tabular-nums.
- Only visible during execution — hidden when idle.

### Tab lifecycle bar

- Top border, collapsed by default. Click toggle to expand.
- Each row: badge (kind) + title + URL + tab id.

---

## 6. Spacing & Sizing

- Side panel: 320–480px wide.
- Header: 60px tall (was 52px — bumped to match Poppins wordmark proportions).
- Standard message padding: 18px top/bottom, 16px left/right.
- Bubble internal padding: 11px 14px.
- Card padding: 14px 16px.
- Button gaps: 8px.
- Vertical rhythm between messages: 6px.

---

## 7. Motion

- Use `cubic-bezier(0.16, 1, 0.3, 1)` for enter animations.
- Message enter: 220ms, `translateY(8px)` → 0.
- Hover lifts: 150ms, `translateY(-1px)` + shadow.
- Settings panel slide-in: 200ms.
- Don't add motion where it doesn't inform state. The product is a work tool — every animation should serve a comprehension purpose.

---

## 8. What NOT to Do

- ❌ Don't use the orange/amber accent (`#D97706`) for primary actions — it's only for approval/warning states.
- ❌ Don't use `DM Sans` or `Instrument Serif` — those are from the prior design.
- ❌ Don't introduce a `model name` or `model display` chip in the header. The extension is model-agnostic; the user doesn't need to see which model is running.
- ❌ Don't use a "B" letter mark. The brand mark is the mountain.
- ❌ Don't use the brand wordmark logo when the user is looking at the extension. The wordmark "Brotto" is fine; the mountain icon is the brand mark.
- ❌ Don't use emoji glyphs for action icons. Use either the mountain mark, letter glyphs, or unicode arrows (→, ▶, ✓).
- ❌ Don't add shadows to user bubbles. They're loud enough already.
- ❌ Don't drop below 11px text. The brand PDF explicitly says "Min 18pt text" for docs — for UI, the floor is 11px.

---

## 9. Pre-flight Checklist for New UI

Before merging a UI change, confirm:

- [ ] All primary actions use `--brand-primary` (not gray, not orange).
- [ ] All headings/badges use Poppins. All body uses Inter.
- [ ] No text below 11px.
- [ ] No "B" letter, no model name, no DM Sans, no Instrument Serif, no orange CTA.
- [ ] The brand mark is the mountain, not a letter, not a flat icon.
- [ ] Settings overlay uses navy at 40%, not pure black.
- [ ] Status pills use the documented color for each phase.
- [ ] Asymmetric bubble corners (user = bottom-right sharp; assistant = bottom-left sharp).
- [ ] No new color tokens introduced without updating this document.

---

## 10. Reference

- Brand PDF: `assets/Inventic_Brand_OnePager_Updated.pdf`
- Source of truth: `clients/brotto-extension/src/sidepanel.html` (the `:root` block and component styles).
- Mountain mark source: `clients/brotto-extension/src/assets/icon.svg` (also reused inline in `sidepanel.html`).
- Build: `cd clients/brotto-extension && node build.mjs` — requires `rsvg-convert` (librsvg) on the host for icon PNG generation.
- Extension name: `Brotto` (kept as-is for now).
- Brand version: `v1.0` — bump the version comment in the CSS `:root` block whenever this document changes.
