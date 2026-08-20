// Isolated test for the CONTEXT cell update logic.
//
// The backend is the source of truth: per step it sends
// `{tokens, window, pct}` (pct pre-computed from `result.usage()`).
// The harness's `_build_context` helper does the math. The frontend
// just stores the object and renders it. This test mirrors that
// exact shape so a discrepancy is a bug, not a copy-paste drift.

"use strict";

const elements = {
  contextCell: { hidden: false, classList: { add() {}, remove() {} } },
  contextValue: { textContent: "", title: "" },
};
const document = {
  getElementById(id) {
    return elements[id] || null;
  },
};

const state = {};

// ponytail: mirror of sidepanel.js. Backend emits pct to one decimal;
// we round to int for the cell when the value is large enough that
// sub-percent doesn't matter visually.
function updateContextUsage() {
  const cell = document.getElementById("contextCell");
  const value = document.getElementById("contextValue");
  if (!cell || !value) return;
  const { tokens, window: windowSize, pct } = state.lastContext || {};
  if (tokens == null || pct == null) {
    value.textContent = "0%";
    value.title = windowSize
      ? `${windowSize.toLocaleString()} tokens window`
      : "no context yet";
    cell.hidden = false;
    return;
  }
  const displayPct = +pct.toFixed(1);
  value.textContent = `${displayPct}%`;
  value.title = `${tokens.toLocaleString()} / ${windowSize.toLocaleString()} tokens (${pct}%)`;
  cell.hidden = false;
}

function reset() {
  state.lastContext = null;
  elements.contextValue.textContent = "";
  elements.contextValue.title = "";
  elements.contextCell.hidden = false;
}

let passed = 0;
let failed = 0;

function assert(name, cond, detail) {
  if (cond) {
    passed++;
    console.log(`  ok  ${name}`);
  } else {
    failed++;
    console.log(`  FAIL ${name}  ${detail || ""}`);
  }
}

function tooltipSays(tokens, windowSize, pct) {
  const t = elements.contextValue.title;
  return (
    t.includes(tokens.toLocaleString())
    && t.includes(windowSize.toLocaleString())
    && t.includes(`${pct}%`)
  );
}

console.log("updateContextUsage isolated tests");

// Test 1: no context yet — null state, fallback tooltip.
reset();
updateContextUsage();
assert("no context → 0%",
  elements.contextValue.textContent === "0%",
  `got "${elements.contextValue.textContent}"`);
assert("no context → 'no context yet' tooltip",
  elements.contextValue.title === "no context yet",
  `got "${elements.contextValue.title}"`);

// Test 2: 8000 tokens / 400000 → 2.0%, rounded to integer 2.
reset();
state.lastContext = { tokens: 8000, window: 400000, pct: 2.0 };
updateContextUsage();
assert("8000/400000 → '2%'",
  elements.contextValue.textContent === "2%",
  `got "${elements.contextValue.textContent}"`);
assert("8000/400000 → tooltip has decimal pct",
  tooltipSays(8000, 400000, 2.0),
  `got "${elements.contextValue.title}"`);

// Test 3: 50000 tokens / 400000 → 12.5%, displayed as '12.5%'.
reset();
state.lastContext = { tokens: 50000, window: 400000, pct: 12.5 };
updateContextUsage();
assert("50000/400000 → '12.5%'",
  elements.contextValue.textContent === "12.5%",
  `got "${elements.contextValue.textContent}"`);

// Test 4: 100000 tokens / 400000 → 25%. Big pct gets rounded.
reset();
state.lastContext = { tokens: 100000, window: 400000, pct: 25.0 };
updateContextUsage();
assert("100000/400000 → '25%'",
  elements.contextValue.textContent === "25%",
  `got "${elements.contextValue.textContent}"`);

// Test 5: tokens exactly 0 — treated as null/0%, displays 0.
reset();
state.lastContext = { tokens: 0, window: 400000, pct: 0 };
updateContextUsage();
assert("0 tokens → '0%'",
  elements.contextValue.textContent === "0%",
  `got "${elements.contextValue.textContent}"`);

// Test 6: very large context (above 100%).
reset();
state.lastContext = { tokens: 75000, window: 50000, pct: 150.0 };
updateContextUsage();
assert("75k / 50k window → '150%'",
  elements.contextValue.textContent === "150%",
  `got "${elements.contextValue.textContent}"`);

// Test 7: simulate the step_card flow — backend sends {context: {...}}.
reset();
const msg = { context: { tokens: 16000, window: 400000, pct: 4.0 } };
if (msg.context && typeof msg.context === 'object') state.lastContext = msg.context;
updateContextUsage();
assert("step_card 16k / 400k → '4%'",
  elements.contextValue.textContent === "4%",
  `got "${elements.contextValue.textContent}"`);

// Test 8: empty step_card — messages without context are passed through.
reset();
const empty = {};
if (empty.context && typeof empty.context === 'object') state.lastContext = empty.context;
updateContextUsage();
assert("empty step_card → 0%",
  elements.contextValue.textContent === "0%",
  `got "${elements.contextValue.textContent}"`);

// Test 9: context_update flow.
reset();
state.lastContext = { tokens: 8000, window: 400000, pct: 2.0 };
updateContextUsage();
assert("context_update 8k → '2%'",
  elements.contextValue.textContent === "2%",
  `got "${elements.contextValue.textContent}"`);

// Test 10: small pct < 10 keeps decimal (e.g. 2.5% stays 2.5%).
reset();
state.lastContext = { tokens: 10000, window: 400000, pct: 2.5 };
updateContextUsage();
assert("2.5% shows as '2.5%'",
  elements.contextValue.textContent === "2.5%",
  `got "${elements.contextValue.textContent}"`);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
