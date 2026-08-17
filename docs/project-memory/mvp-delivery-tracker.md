# Browser Automation MVP Delivery Tracker

**Last updated:** 2026-08-17

This file is the durable, high-level status index. Detailed requirements
live in approved design specs and implementation plans. A delivery item moves
to `complete` only after its acceptance gates pass end to end.

| Item | Status | Notes | Exit gate |
| --- | --- | --- | --- |
| 1. Orchestrator agent loop + extension relay | In progress | `services/brotto-orchestrator` + `clients/brotto-extension` wired end-to-end; harness runs observe→plan→act with pydantic-ai | Contract tests, dev-mode + extension-mode E2E pass; human approval and login-page guardrails work |
| 2. Trajectory + audit recording | Pending | Not started | Every action links its pre-observation, proposal, policy decision, result, and post-observation in a durable, tamper-evident log |
| 3. Real-world eval suite | Pending | Per D10 in `decisions.md` | At least 5 real-site tasks (form fill, extraction, multi-step booking, error recovery, copy-paste) hit success-rate KPI |
| 4. Hardening + open-source packaging | Pending | Documentation, threat model review, Docker, license headers, CI | Threat-model review passes; reproducible container build; signed commits; CHANGELOG |

## Current blocking gate

Complete item 1's exit gate: contract tests for `ObservationV1` /
`BrowserAction`, dev-mode E2E (Playwright → harness → result), and
extension-mode E2E (background.ts → WS → harness → background.ts action
execution) all green. Human-approval and login-page guardrails must be
exercised.

## Working rules

- Work on one delivery item at a time.
- Locked decisions in `decisions.md` are not reopened without explicit
  re-discussion.
- Never commit `.env` files, secrets, dependency directories, generated
  bundles, screenshots, or browser data — `.gitignore` already covers all of
  these.
- Record verification evidence in the implementation handoff for each
  completed item.
- Public-site demonstrations supplement but do not replace controlled
  release gates.