# Brotto Python Orchestrator - Production-Grade Implementation Plan

**Goal**: Build production-grade agent harness + extraction + context management matching browser-use and Claude in Chrome quality levels.

**Inspiration**: browser-use (89.1% success rate, Python → Rust core → Browser harness), Claude in Chrome (extension-based, vision + CDP)

## Phase 1: Core Architecture & Decisions

### 1.1 Agent Harness Design
**Task**: Define the agent loop and context management pipeline

Key decisions to lock in:
- Agent input format: structured observation vs. vision embeddings vs. hybrid
- Action schema: semantic targets + ref_ids (not coordinates)
- Error recovery: retry logic, fallback strategies
- Context size management: token budgeting
- Tool system: PydanticAI tools vs. custom action dispatch

**Deliverables**:
- `decisions.md` - locked architectural choices
- Agent harness spike with proper loop implementation
- Context builder that mirrors TypeScript version exactly

### 1.2 Semantic Extraction (CDP AX Tree)
**Task**: Production-grade element extraction via CDP

Currently broken:
- Using JavaScript DOM queries instead of CDP Accessibility Tree
- No stable ref_ids or coordinate mapping
- Action execution doesn't match extracted targets

Implementation:
- Complete CDP AX tree extractor (already started in ax_tree_extractor.py)
- Map AX nodes → semantic targets with stable IDs
- Coordinate extraction via DOM.getBoxModel for each element
- Filter to interactive roles only (button, link, textbox, etc.)
- Handle frames/iframes correctly
- Fallback to screenshot-based vision when CDP fails

**Deliverables**:
- Production AX tree extractor with proper error handling
- Semantic target model matching brotto-contracts
- End-to-end test: DOM → AX tree → targets → actions

### 1.3 Context Management
**Task**: Right-sized context for LLM

What the agent sees each turn:
1. **Observation** (current page state):
   - URL, title
   - Top-K interactive targets (25-50 max, filtered)
   - Screenshot (optional, based on model)
   - Previous action results
   
2. **Memory** (working context):
   - Goal statement
   - Last N steps (history)
   - Extracted data (stored references)
   - Page state changes

3. **Prompt structure**:
   - System prompt (agent rules + action schema)
   - Current observation formatted clearly
   - History showing past actions + results
   - Memory of extracted data

**Deliverables**:
- Context formatter that produces right-sized prompts
- Token counter to stay within budget
- History compression strategy
- Memory storage + retrieval

## Phase 2: Action Execution & Robustness

### 2.1 Action → DOM Execution
**Task**: Map semantic targets to real browser actions

Current problem: Actions reference targets that don't exist on page.

Solution:
- Map action.target_id → actual DOM element via cached map
- Use stable selectors (data attributes + role-based)
- Implement coordinate-based clicking as fallback
- Handle visibility checks before clicking
- Proper error messages when target missing

**Deliverables**:
- ActionExecutor that handles:
  - left_click(target_id)
  - insert_text(target_id, text)
  - visit_url(url)
  - key(key_name)
  - wait(duration_ms)
  - scroll(direction)
  - terminate()

### 2.2 Error Recovery
**Task**: When actions fail, agent recovers gracefully

Strategies:
- If target_id missing: agent sees error + current page state
- If click timeout: report timeout, suggest alternatives
- If navigation fails: show error, suggest URL correction
- If text input fails: check element disabled/readonly, report

**Deliverables**:
- Error classification system
- Recovery suggestions in action results
- Test: intentional failures → agent adapts

### 2.3 Vision as Fallback
**Task**: When CDP/extraction fails, use screenshot + vision

Optional (Phase 2+):
- Screenshot analysis with Claude Vision
- Bounding box detection from screenshot
- Hybrid: CDP targets + vision for verification

## Phase 3: Dev vs Extension Modes (Lego Blocks)

### 3.1 Unified Layer
**Task**: Single code path for both dev (Playwright) and extension (WebSocket) modes

Current state: ActionHandler abstraction done, but needs integration

Components:
- **Observation generation**: PlaywrightBrowser (dev) vs. WebSocket client (extension)
- **Action execution**: execute_action() implementation
- **Context building**: same for both
- **Agent loop**: same for both

**Deliverables**:
- Pluggable browser interface (dev vs. extension)
- Shared agent factory
- Shared action execution pipeline
- Evals run in both modes simultaneously

### 3.2 Dev Harness
**Task**: Playwright-based dev environment for testing

Must have:
- Real Chrome with CDP access
- Screenshot + AX tree extraction
- Action execution
- Proper error reporting
- Performance logging

### 3.3 Extension Mode
**Task**: WebSocket-based extension integration

Must have:
- Client sends observations via WebSocket
- Server runs agent loop
- Server sends actions back to extension
- Proper session/sequence tracking

## Phase 4: Evaluation & Benchmarking

### 4.1 Dev Eval Suite
**Task**: Structured tasks to measure quality

5 real-world tasks:
1. Navigation + form filling (e.g., job application)
2. Data extraction (e.g., find prices across sites)
3. Problem solving (e.g., cart management)
4. Error recovery (intentional blockers)
5. Multi-step workflow (e.g., book flight + hotel)

**Metrics**:
- Success rate (task completed)
- Steps to completion
- Latency per action
- Token usage
- Error recovery frequency

### 4.2 Extension Eval
**Task**: Same eval suite run through WebSocket

Validates:
- Client → Server → Agent → Client roundtrip works
- Observation quality is consistent
- Action execution is reliable

## Implementation Order

1. **Lock decisions** → decisions.md
2. **Agent harness** → proper loop with context management
3. **AX tree extraction** → production-grade CDP integration
4. **Action execution** → semantic target mapping
5. **Error recovery** → graceful fallbacks
6. **Dev harness** → Playwright integration
7. **Extension integration** → WebSocket mode
8. **Evals** → measure quality
9. **Optimization** → iterate on metrics

## Critical Success Factors

- **Context quality**: Right information at right time (no noise)
- **Semantic targets**: Stable, accurate extraction via CDP
- **Action reliability**: 95%+ action execution success rate
- **Error recovery**: Agent doesn't get stuck, adapts gracefully
- **Latency**: < 5s per action (including LLM inference)
- **Both modes work**: Extension and dev harness equally functional

## Known Gaps to Address

- Screenshot + vision integration (fallback strategy)
- Frame/iframe handling in AX tree
- State persistence across navigations
- Token budget management for long workflows
- Rate limiting + quota management for LLM calls
