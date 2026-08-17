# Architecture Baseline: Fara 1.5 Browser Automation MVP

**Recorded:** 2026-08-03
**Status:** Verified repository baseline before canonical-loop implementation

## Product intent

The product is a self-hosted browser automation platform using Fara 1.5 for computer-use decisions and a thin browser client for execution in an existing authenticated browser session. The client may transmit screenshots and deliberately selected, sanitized observation metadata to the customer's self-hosted server. It must never transmit cookies, authorization headers, local storage, session storage, credentials, password values, or raw browser-profile data.

The longer-term product records complete action trajectories. When recipe recording is enabled, a successful trajectory can later be compiled into a deterministic Playwright workflow that runs without model inference and consumes zero model tokens.

## Approved delivery order

1. Canonical agent loop and versioned client protocol.
2. Secure thin extension with deterministic observations and action acknowledgements.
3. Append-only trajectory and audit recording.
4. Recipe intermediate representation, Playwright compiler, and validated zero-token replay.

Each item must produce a working vertical slice and pass its acceptance tests before the next item begins.

## Approved architecture decisions

- TypeScript owns the control plane and canonical agent loop.
- Python is restricted to the Fara inference service.
- The committed shared schema packages become the only protocol and action contracts.
- The client connects outbound over authenticated WSS.
- Exactly one action may be in flight per session.
- Every action references the observation from which it was planned.
- Every action returns an explicit typed result and a settled post-action observation.
- Invalid model output is a repairable inference error, never successful completion.
- Model completion is a proposal that requires structured findings and deterministic verification.
- Security policy is enforced in code on both orchestrator and client boundaries.
- Every state transition produces a versioned trajectory event for future audit and recipe compilation.

## Verified current-state findings

The active demonstration does not use the intended platform architecture. The browser extension talks to an ad-hoc Python HTTP/SSE relay in `services/playwright-relay/fara-relay.py`. That relay calls the Fara-compatible endpoint directly and maintains process-local history. The committed TypeScript orchestrator, shared relay protocol, shared Fara action schema, policy engine, audit service, and structured extension relay are not connected to this runtime path.

The observed premature completion has deterministic causes:

- Unparseable, malformed, prose-only, or unexpected model output falls through to `done`.
- `terminate` is trusted without completion evidence.
- `pause_and_memorize_fact` is treated as terminal.
- Requested actions have no action ID, observation ID, result acknowledgement, or verified post-state.
- The controller assumes execution succeeded after a fixed delay.
- Duplicate continuations can create overlapping inference.
- Both an executable `done` action and a terminal `done` event are emitted.
- Prompt instructions such as a minimum action count are not enforced by the controller.

There are three incompatible action contracts in the repository: the active Python relay XML dialect, the TypeScript orchestrator parser dialect, and the inference-service prompt dialect. These must be replaced by one constrained, versioned structured-output contract.

## Existing components worth retaining selectively

- `packages/fara-action-schema`: useful action and observation concepts, but it needs reconciliation and versioning.
- `packages/relay-protocol`: useful sequencing, heartbeat, and session concepts, but it is not wired into the active path and conflicts with some eval expectations.
- `services/agent-orchestrator`: useful state-machine, history, retry, budget, executor, and completion abstractions, but the server runtime is a scaffold and does not execute the loop.
- `clients/browser-extension/src/relay.ts`: useful WebSocket/reconnect concepts, but it is unused by the active background service worker.
- `clients/browser-extension/src/action-executor.ts`: useful structured executor concepts, but it is duplicated by the active background action switch.
- `services/audit-service`: substantial schema, persistence, privacy, export, and retention work; it is disconnected from the active loop and has causal-linkage/session-caching defects.
- `services/artifact-service`: useful encrypted artifact primitives; it is not trajectory storage and needs durable metadata/key-management hardening before production use.

## Components that do not exist yet

- A durable canonical run/step/action/observation event log integrated with execution.
- A recipe recording toggle tied to trajectory eligibility.
- A recipe schema or intermediate representation.
- Semantic target stabilization and locator synthesis.
- A deterministic Playwright compiler.
- Recipe static security validation, replay validation, versioning, signing, or registry.
- A zero-token recipe runtime with equivalence telemetry.

## Dirty-worktree warning

The linked implementation worktree contains extensive pre-existing modified files and generated dependency/build directories. The active `services/playwright-relay/` implementation is untracked, including an `.env` file. Implementation work must preserve these changes, stage only deliberate files, and never commit secrets, dependency directories, or generated bundles. Legacy runtime paths should be quarantined only after the canonical path passes equivalence and end-to-end tests.

## Security invariants

- No cookie export or cookie-reading protocol capability.
- No authorization-header, storage-value, credential, password, or browser-profile transmission.
- Screenshot and semantic metadata transmission only to the configured customer-controlled server.
- Sanitization and redaction occur before an observation leaves the browser.
- Only explicitly attached tabs and allowed HTTP(S) origins may be automated.
- High-impact actions require deterministic policy approval.
- Sessions use random identifiers, short-lived credentials, message expiry, sequence validation, payload limits, and replay protection.
- Durable artifacts are encrypted, content-addressed, retention-controlled, and excluded by default.

## Target acceptance KPIs for the canonical loop

- Zero malformed model responses classified as completion.
- Zero forbidden browser data transmitted in the security corpus.
- Exactly one in-flight action per session.
- Idempotent handling of every duplicate action result in the test corpus.
- Every terminal success contains structured findings and verifier evidence.
- No duplicate completion events.
- Cancellation reaches a terminal state and detaches the client within five seconds.
- At least 90% success on the controlled multi-step browser-task suite for the selected Fara deployment.
- Every executed action links its pre-observation, proposal, policy decision, result, and post-observation.
