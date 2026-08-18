# Brotto Roadmap — Two-Sided Coin

**Wedge:** Banks (regulated industry) on the enterprise side. Apache-2.0 self-host on the developer side. They reinforce each other: bank buyers vet the OSS code, devs become the OSS pipeline that produces bank-ready code.

**Doctrine:** Tier 0 ships before Tier 1. Tier 1 ships before Tier 2. No tier skipping. At every tier we ask: "can this ship on a Friday afternoon?" If not, it's not done.

For each item: **Why** (the forcing function), **Effort** (S ≤ 1 day, M = 2–5 days, L = 1–3 weeks), **Side** (B = bank, O = OSS, both).

---

## Tier 0 — Make it work (foundation)

The repo has to actually work cleanly before anything else. This is mostly cleanup of the current state.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 0.1 | **Kill the dead agent loops.** Delete `AgentLoop` and `AgentLoopInferenceAdapter`. Pick `AgentHarness`. Add a single import check at build time. | Three loops = confused architecture. Anyone reading the code today can't tell which is real. | S | B/O |
| 0.2 | **Wire D9 sequence tracking + WS reconnection.** State machine on the orchestrator side. Extension resumes on reconnect. | Hard fail for multi-step workflows. Any tab navigation that disconnects the WS kills the session. D9 is declared but unused. | M | B/O |
| 0.3 | **Publish the model benchmark.** Run haiku-4-5 vs sonnet-4-6 vs opus-4-7 on the dev eval suite. Publish the numbers. | "haiku default" is a guess. We can't tell banks "we use the right model" without numbers. | M | B |
| 0.4 | **Delete the dead `scripts/dev_evals.py` and `scripts/test_phase*.py`.** They import modules that don't exist. | Publicly broken scripts in a bank-facing repo is a credibility hit. | S | O |
| 0.5 | **Translate `PERMISSIONS.md` to match the manifest.** Doc lists `activeTab` and `tabGroups` that aren't requested. | First thing a security team checks. | S | B |
| 0.6 | **Add automated WS protocol tests.** Round-trip an observation/action sequence. Catch reversions. | The protocol is the spine. No tests = no contracts. | M | B/O |

**Done-tier-0 marker:** A single agent loop. WS that survives a disconnect. Five passing tests. Public model numbers.

---

## Tier 1 — Make it credible (proof)

Without numbers, banks won't even take the meeting.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 1.1 | **Public eval suite (D10).** 5 tasks on real sites (login + form, data extraction, multi-step, error recovery, cross-tab). JSONL prompt versions. GitHub Pages leaderboard. | The single biggest credibility lever. Cuts through every marketing claim in the category. | L | B/O |
| 1.2 | **Threat model adversarial scenarios.** Expand `THREAT_MODEL.md` with 6–10 concrete attack scenarios (prompt injection, action smuggling, replay, MITM, exfil via screenshot, etc.). | Banks *will* ask "what if X". We need answers before they ask. | M | B |
| 1.3 | **E2E test harness covering locked decisions.** D1: target extraction stable across reflow. D2: actions resolve to ref_id, not coords. D5: errors surface to agent. D7: same agent runs in dev and extension mode. | "Production-grade" in `PLAN.md` is unproven. We need tests that prove the lock-ins hold. | M | B/O |
| 1.4 | **Architecture diagram.** One PNG showing ext→server→model→back, with the WSS boundary, the chrome.debugger surface, the AX extraction pipeline. | Banks ask for this in the first call. Strangers ask for this on the landing page. | S | B/O |
| 1.5 | **Public benchmark results in `benchmark/`.** Not just the code, but the runs. File an issue every time a model regresses. | Defends against the "is this maintained?" objection. | S | B/O |

**Done-tier-1 marker:** Anyone can clone the repo, run the eval suite, replicate the numbers, and read the threat model.

---

## Tier 2 — Make it trustworthy (the moat)

This is the *positive* form of the threat model — what we guarantee, not what we forbid.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 2.1 | **"What Brotto can never see / do / persist" page.** One HTML page. Plain English. Map 1:1 against Browser-Use's docs. | rtrvr.ai and Browser-Use have features Brotto refuses. Translate refuses into guarantees. | S | B/O |
| 2.2 | **Public dependency audit.** `pip-audit` + `npm audit` in CI. SBOM in the repo. | First line of any security questionnaire. | S | B |
| 2.3 | **No-secret attestation.** Architectural proof: orchestrator never reads cookies/Authorization, never persists browser state. Show the code paths. | Banks need to verify "no credential exfiltration" is a *property of the code*, not a *promise*. | M | B |
| 2.4 | **Dependency provenance.** Lock all deps with hashes. Pin transitive. | One supply-chain leak kills a bank deal. | S | B |
| 2.5 | **Data Processing Addendum (DPA) template.** Public. Bank legal can crib from it. | Removes 4–6 weeks from procurement. | S | B |

**Done-tier-2 marker:** A bank security team can sign off on the architecture from public artifacts alone.

---

## Tier 3 — Make it findable (distribution)

Distribution is the bottleneck for the OSS side. Banks won't find you without a developer pipeline.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 3.1 | **Landing page** — "Your AI, your browser." Single sentence. Pricing CTA. Demo GIF. | The product has no marketing surface. | M | B/O |
| 3.2 | **One-click Docker deploy.** `docker run` → working server. Verify on Render and Fly. | Self-host is the entire pitch. Make it trivial. | M | O |
| 3.3 | **Docs site.** Mintlify or Docusaurus. Public. Versioned. | Bank engineers need to evaluate without sales calls. | M | B/O |
| 3.4 | **README rewrite.** Positioning, GIF, "why Brotto", quickstart, threat model link. | First thing OSS devs see. | S | O |
| 3.5 | **"Built with Brotto" series.** Three blog posts / video tutorials using Brotto for real workflows. | Proof of life. Also surfaces the eval suite. | M | O |
| 3.6 | **Issue templates + RFC process.** Public roadmap. `good-first-issue` labeled. | OSS contributors don't show up without these. | S | O |

**Done-tier-3 marker:** A developer can find Brotto, deploy it in 5 minutes, and use it for a real task within an hour.

---

## Tier 4 — Make it bank-ready (the wedge)

This is the long pole. Most of it is operational, not code.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 4.1 | **Multi-tab workflow support.** The harness assumes one tab. Banks have 10+ tabs per workflow. | Real users contradict the singular assumption. | L | B |
| 4.2 | **Audit log export.** Every action, every model call, every approval. JSONL + parquet. | Compliance team can't buy what they can't audit. | M | B |
| 4.3 | **SSO / SAML / OIDC.** | Bank IdP. Hard requirement. | M | B |
| 4.4 | **Role-based access control.** Roles: admin, operator, viewer. | Bank access controls. | M | B |
| 4.5 | **Custom approval policies per action type.** Banks want to define "what counts as a critical action" themselves. | Hardcoded regex on the agent is a poor fit for enterprise. | M | B |
| 4.6 | **On-prem / VPC deployment option.** | Some banks physically cannot use multi-tenant Cloud. | L | B |
| 4.7 | **Data residency.** Region pinning for Cloud. | EU banks. | M | B |
| 4.8 | **Penetration test report.** | Procurement gates. | L (vendor) | B |

**Done-tier-4 marker:** A bank can complete a vendor risk assessment from public artifacts and a single sales call.

---

## Tier 5 — Make it sellable (the Cloud)

The product has to charge money.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 5.1 | **Brotto Cloud MVP.** Hosted, BYOK, no managed browsers. Single-region. | Cheapest Cloud flavor. Validates the wedge. | L | B |
| 5.2 | **Pricing tiers.** Free (community), Team ($X/seat), Enterprise (custom). | Banks pay per seat. | S | B |
| 5.3 | **Billing.** Stripe. | Revenue. | M | B |
| 5.4 | **Status page + incident response.** | SLAs require this. | S | B |
| 5.5 | **SOC2 Type II readiness.** | Most banks require this. ISO 27001 alternative for EU. | L (vendor) | B |
| 5.6 | **Procurement docs.** Security questionnaire answers, BAA, DPA, vendor risk packet. | Removes procurement friction. | M | B |

**Done-tier-5 marker:** A bank can buy Brotto without a phone call beyond the security review.

---

## Tier 6 — Make it community (the OSS moat)

Open source is the trust signal bank buyers use to evaluate. Without it, bank security teams will block the deal.

| # | Item | Why | Effort | Side |
|---|---|---|---|---|
| 6.1 | **Apache 2.0 maintained correctly.** CLA, contributor license, license headers. | Without CLA, multi-entity contributions can't be relicensed. | S | O |
| 6.2 | **Public roadmap.** | OSS contributors don't show up without a roadmap. | S | O |
| 6.3 | **RFC process.** Decisions stop being locked in private. | Reduces "this is just a personal project" objection. | S | O |
| 6.4 | **Community channel.** Discord or Matrix. | Where contributors live. | S | O |
| 6.5 | **Quarterly contributor call.** | Maintains trust. | S | O |
| 6.6 | **Self-host feature parity with Cloud** (where economically feasible). | Bank on-prem requires this. | L | B/O |

**Done-tier-6 marker:** A bank security team can say "we evaluated the code, not the vendor."

---

## Suggested sequence (first 90 days)

The fastest path to a bank meeting is **Tier 0 → Tier 1 → Tier 2 + Tier 3 in parallel → Tier 4 vendor-risk first items → Tier 5 MVP**.

**Days 1–14 (Tier 0):**
- 0.1, 0.4, 0.5, 0.6 are S/M and ship in week one. 0.2 and 0.3 are the harder pulls.

**Days 15–45 (Tier 1 + Tier 3 partial):**
- 1.1 (eval suite) is the highest-leverage. Block on it.
- 1.2, 1.3, 1.4, 1.5 are M. Land in parallel.
- 3.4 (README) is S. Ship same day.
- 3.1 (landing page) is M. Block on positioning copy.

**Days 46–90 (Tier 2 + Tier 3 + Tier 4 first):**
- 2.1, 2.2, 2.3, 2.4 are mostly S/M. Easy wins.
- 3.2 (Docker) is M. Unblocks Tier 4 on-prem.
- 4.2 (audit log), 4.3 (SSO), 4.4 (RBAC) are the bank-blocking items.

**Tier 5 Cloud MVP** is the next quarter. Don't try to land it inside 90 days.

---

## What I would not do

- **Skip the eval suite.** The single biggest lever. Five tasks on real sites. Public. Done.
- **Build a marketplace of integrations.** Browser-Use already has 1000+. You lose this race.
- **Compete on stealth/proxy/CAPTCHA.** Your thesis is the opposite.
- **Build a multi-surface "Cowork" analog.** Anthropic and Perplexity will outspend you.
- **Try to be both vertical-SaaS and platform.** Pick one. I'd pick platform because banking pipelines prefer platforms.
- **Reach for SOC2 Type II before Tier 2.** SOC2 over a half-built product is a reported-but-not-real certificate. Bank security teams will catch it.

---

## Open questions to decide before Tier 4 starts

1. **SOC2 vs ISO 27001.** US banks lean SOC2. EU banks lean ISO 27001. Pick by your first five target accounts.
2. **Hosted Cloud region.** US-only first, or EU-first? Affects 4.7.
3. **Multi-tenant Cloud vs single-tenant per bank.** Multi-tenant is cheaper; single-tenant is bank-default. Affects 4.6.
4. **Free OSS tier limits.** If free is unlimited, Cloud has no pull. If free is 10 tasks/day, Cloud eez to convert.
5. **Who is the first bank design partner?** Banks buy from people they know. Get one LOI before Tier 4.

These are the only decisions that block Tier 4. Everything else is execution.
