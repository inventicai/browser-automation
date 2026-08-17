# Architectural Decisions - Brotto Python Orchestrator

## Context
Building production-grade browser automation agent inspired by browser-use (89.1% success) and Claude in Chrome. Locked decisions prevent revisiting solved problems.

---

## D1: Semantic Target Extraction via CDP Accessibility Tree

**Decision**: Use Chrome DevTools Protocol Accessibility API, not JavaScript DOM queries.

**Rationale**:
- CDP AX tree is the canonical representation (same as browser's assistive tech sees)
- Stable node IDs across page mutations
- Computed roles, names, values (not fragile text parsing)
- Matches TypeScript implementation exactly
- 99% accurate vs. CSS selector brittleness

**Not**: JavaScript `document.querySelectorAll()` or Playwright's built-in accessibility API (insufficient detail).

**Implementation**:
- `AXTreeExtractor.extract_targets()` using `page.context.new_cdp_session()`
- `Accessibility.enable()` → `Accessibility.getFullAXTree()` → `DOM.getBoxModel()` for coords
- Filter interactive roles: button, link, textbox, checkbox, etc.
- Generate stable `ref_id` via hash(role, name, nodeId)
- Cap at 50 targets per page (agent context window)

**Status**: Locked. No fallback to simpler extraction methods.

---

## D2: Semantic Targets + Ref IDs, Not Coordinates

**Decision**: Actions reference targets by stable `target_id`, not (x, y) coordinates.

**Rationale**:
- Coordinates change when page reflows (responsive design)
- Ref IDs are stable across DOM updates
- Enables agent to reason about elements (target = "submit_button")
- Matches action schema from brotto-contracts

**Action format**:
```json
{
  "type": "left_click",
  "target_id": "button_a1b2c3d4",
  "confidence": 0.95
}
```

**Not**: `{"type": "left_click", "x": 250, "y": 100}` (brittle).

**Execution**:
- Store mapping: ref_id → DOM selector + backendNodeId
- Playwright: use `DOM.querySelector()` to find element
- Fallback: `page.click('[data-ref-id="..."]')` if we inject attrs

**Status**: Locked. Agent always outputs ref_ids.

---

## D3: Agent Loop: Observe → Plan → Act → Repeat

**Decision**: Synchronous, single-threaded loop per session. No async action dispatch.

**Rationale**:
- Predictable sequencing (no race conditions)
- Clear causality: action result → next observation
- Browser state is sequential (one user interaction at a time)
- Easier debugging / error recovery

**Not**: Fire-and-forget actions or parallel tool calls.

**Loop pseudocode**:
```
while not terminated:
  observation = screenshot_to_observation()
  context = build_context(observation, history, goal)
  action = agent.run(context)
  result = execute_action(action)
  history.append((action, result))
  if action.type == "terminate":
    break
```

**Status**: Locked. No architectural change to this loop.

---

## D4: Context Input: Structured Observation, Not Vision Embedding

**Decision**: Send structured observation (URL, targets, HTML) + screenshot, not embedding/vector.

**Rationale**:
- LLMs understand structured text better than embeddings
- Screenshot is reference/verification, not primary input
- Token-efficient: ~500 tokens per observation
- Vision models are slower and more expensive than text

**Observation format**:
```
OBSERVATION:
  url: https://example.com
  title: "Login - Example"
  targets (5):
    [button_1a2b] button "Sign In" @ (250, 100)
    [input_3c4d] textbox "Email" @ (200, 150)
    ...
  screenshot: data:image/png;base64,...
```

**Not**: Embed targets as vectors or omit screenshot.

**Fallback**: If CDP fails, screenshot + vision-based element detection.

**Status**: Locked. Hybrid text + screenshot, not pure vision.

---

## D5: Error Handling: Agent Sees Failures, Not Silent Retries

**Decision**: When action fails, report error to agent immediately. Agent adapts.

**Rationale**:
- Agent learns from failures (similar to human debugging)
- Better recovery strategies (agent knows why it failed)
- Prevents infinite loops (agent can terminate if stuck)
- Transparent error messaging

**Action result format**:
```json
{
  "ok": false,
  "action_type": "left_click",
  "target_id": "button_a1b2c3d4",
  "error": "Element not visible: covered by modal dialog",
  "suggestion": "Close modal first, then retry"
}
```

**Agent behavior**:
- Sees error in history
- Next observation includes current page state
- Agent decides: retry, try alternative, terminate, ask for help

**Not**: Retry 3x automatically, then give up.

**Status**: Locked. Errors surface to agent immediately.

---

## D6: Agent Framework: PydanticAI

**Decision**: Use PydanticAI with Anthropic API (Claude Haiku 4.5 by default).

**Rationale**:
- Strong on browser tasks (Claude trained on web data)
- Structured output (BrowserAction discriminated union)
- Tool support via PydanticAI
- Model-agnostic (supports OpenAI, Azure, local models)
- Proven in production (Anthropic uses it)

**Not**: LangChain, LlamaIndex, or custom loops.

**Configuration**:
```python
model = AnthropicModel(model_name="claude-haiku-4-5", api_key=api_key)
agent = Agent(
  model=model,
  output_type=BrowserAction,
  instructions=compose_system_prompt(),
  tools=[...],
  capabilities=[PolicyHooks(...), ApprovalCapability(...), HistoryCapability(...)]
)
```

**Status**: Locked. No model swapping without explicit reason.

---

## D7: Dev Mode vs Extension Mode: Shared Agent Code

**Decision**: Single agent factory, pluggable browser interface (dev vs. extension).

**Rationale**:
- Code duplication is enemy of quality
- Both modes test same agent logic
- Changes benefit both simultaneously
- Extension can use dev harness for debugging

**Architecture**:
```
Agent Factory (shared)
    ├── Agent Loop (shared)
    ├── Context Builder (shared)
    ├── Action Executor (shared, pluggable)
    ├── Error Recovery (shared)
    └── History Management (shared)

Browser Interface (pluggable)
    ├── PlaywrightBrowser (dev)
    │   ├── screenshot_to_observation()
    │   ├── execute_action()
    │   └── close()
    └── WebSocketBrowser (extension)
        ├── observation from client
        ├── send action to client
        └── stream results
```

**Not**: Duplicate agent logic for extension vs. dev.

**Status**: Locked. Lego-block modularity is non-negotiable.

---

## D8: Dev Harness: Playwright + CDP

**Decision**: Use Playwright for local browser automation in dev mode.

**Rationale**:
- Mature, well-tested automation library
- Direct CDP access via `page.context.new_cdp_session()`
- Chrome/Chromium out of the box
- Handles frames, iframes, multiple pages

**Not**: Raw CDP client or other browser automation (Selenium, Puppeteer).

**Integration**:
- PlaywrightBrowser wraps Playwright page
- AXTreeExtractor uses CDP session from page context
- execute_action() uses Playwright methods (click, fill, goto, etc.)

**Status**: Locked. Playwright is the dev harness.

---

## D9: Extension Mode: WebSocket + Sequence Tracking

**Decision**: Extension sends observations, server sends actions, via WebSocket with strict sequence IDs.

**Rationale**:
- Asynchronous but ordered (sequence IDs prevent out-of-order processing)
- Stateless server (extension holds session state)
- Replay protection (same sequence ID = ignore duplicate)
- Minimal latency (no polling)

**Not**: HTTP REST, server-side session state, or polling.

**Protocol**:
```json
Extension → Server: 
  {"type": "observation", "sequence": 42, "session_id": "...", "payload": {...}}

Server → Extension:
  {"type": "action", "sequence": 42, "action": {...}}
```

**Status**: Locked. WebSocket with sequence tracking.

---

## D10: Evals: Real-World Tasks, Not Synthetic

**Decision**: Eval tasks are real websites + workflows, not mocked pages.

**Rationale**:
- Synthetic tests don't catch real world failures (CAPTCHAs, layout surprises, auth)
- Real tasks prove production readiness
- Benchmarkable against browser-use, other agents

**Eval tasks** (Phase 4):
1. Job application form (navigation + form fill)
2. Price comparison (multi-site extraction)
3. Reservation booking (multi-step workflow)
4. Error recovery (intentional blockers)
5. Data entry (copy-paste from doc to form)

**Metrics**:
- Success rate (task completed)
- Steps to completion
- Latency per step
- Token usage

**Not**: Mocked pages, synthetic observations, or scripted successes.

**Status**: Locked. Evals are real or nothing.

---

## Open Questions (To Decide Later)

- **Vision fallback**: When should agent see screenshot vs. just structured obs?
- **State persistence**: How to handle multi-page workflows with state?
- **Rate limiting**: Token budgets per session / per day?
- **Memory**: How many steps to keep in history before compression?

---

## Decision Review Cadence

- Review after Phase 1 (locked decisions) ✓
- Review before Phase 2 implementation (may refine based on reality)
- No changes to locked decisions without explicit re-discussion

**Last reviewed**: 2026-08-14
