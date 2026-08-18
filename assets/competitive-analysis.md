# Brotto — Competitive Analysis

**Date:** 2026-08-18
**Scope:** Browser-automation agent category. Direct competitors named by the user (Claude in Chrome, browser-use, hermes-agent) plus discovered adjacent players. Internal SWOT and strategic recommendations for Brotto.

---

## 1. Brotto at a glance

**What it is:** A server-hosted browser automation agent (Python/FastAPI/pydantic-ai) that drives a user's *real* Chrome via a thin Manifest V3 extension. The extension is the only thing holding `chrome.debugger`; the server never speaks CDP to the user's browser. Dev mode runs the same agent on Playwright locally.

**Locked architecture (D1–D10):**
- Semantic CDP-AX tree extraction with stable `ref_id`s (no coordinates).
- `observe → plan → act → repeat` synchronous loop, one agent code path.
- pydantic-ai with Anthropic Claude (model-agnostic).
- WebSocket extension transport with sequence/reconnect goals (sequence *declared*, not yet wired).
- Critical actions (purchase, send, delete) gated on side-panel approval.
- **No** cookie/auth-header collection, **no** stealth, **no** CAPTCHA bypass.
- Apache-2.0.

**Current state:** working dev harness + working extension relay, but the repo is in transition. `services/brotto-orchestrator` has three overlapping agent loops; only `AgentHarness` is alive. `scripts/dev_evals.py` and `test_phase*.py` import modules that don't exist. Sequence tracking is in the contract but always emits `0`. `src/content.js` is dead code. The extension side panel is a polished ~3,200 LOC UI but has zero unit tests and no reconnection logic. D10's "real-world eval suite" is unimplemented.

In short: **Brotto's IP is mostly architectural choices and the side-panel UX. The implementation is real but pickier than the docs pretend.**

---

## 2. Competitive landscape

Maps to three concentric rings:

| Ring | Players | What they sell |
|---|---|---|
| **Direct** (browser-agent product for end users) | Claude in Chrome, OpenAI Operator/ChatGPT Agent, Perplexity Comet, rtrvr.ai, Skyvern | An agent that drives a browser for you |
| **Adjacent** (open frameworks, integrator wins) | **Browser-Use**, Stagehand, Notte, Hermes Agent | A library you'd embed in your own product |
| **Infrastructure** (raw browser, you bring the agent) | Browserbase, Anchor Browser, Steel.dev, Hyperbrowser, Kernel | Cloud Chromium with CDP/Playwright |

Browser-Use sits between Rings 1 and 2 — they ship both an open-source lib and a hosted Cloud product. Hermes Agent is a *general* agent that *can* browse; not a true direct competitor on dimension "browser automation is the product." Still relevant because it has 231k stars and is the OSS gravity well.

---

## 3. Competitor profiles

### 3.1 Direct

**Claude in Chrome (Anthropic)** — *the closest competitor.*
- Extension on all paid Claude plans ($20–$200/mo). Driven by Anthropic's own Claude, side panel UI.
- Wedge: deep integration with Claude Code + new Cowork product; "your session follows you" across surfaces.
- **Differentiators vs Brotto:** brand, model quality, ecosystem coupling. Same underlying pattern (extension + debugger).
- **Where Brotto is competitive:** explicit no-stealth, no-credential posture is a real trust story Anthropic has to defend with "guardrails" copy because they ship browser-mcp-class tooling. Brotto's server never sees cookies; Anthropic's session follows you across the Cloud, which is more invasive by design.
- **Where Brotto is weaker:** no Cloud product, no consumer brand, no Cowork-equivalent multi-surface runner, no multimodel frontier.
- *Threat level:* **High.** They own the model and the brand. The only defense is being stricter, faster, and more focused.

**Browser-Use** — *the open-source incumbent.*
- 99.7k stars, MIT-licensed, Python API over Rust core → Chromium.
- DUAL product: open-source lib + Cloud ($29 Dev / $299 Business) with stealth, proxy rotation, CAPTCHA solving, 1000+ integrations, persistent FS.
- Action space: built-in click/type + `@tools.action` custom tools. Beta with Rust harness for frontier models.
- **Reports:** 78% on 100 real-world benchmark tasks; 89% on WebVoyager (per Respan); cloud completion ordered 3–5× faster on their own model.
- **Where Brotto is competitive:** server/extension split with explicit no-stealth is the *opposite* of Browser-Use's position — they win the "scrape whatever" market, Brotto owns the "respect the user's logged-in state" market.
- **Where Brotto is weaker:** no Cloud, no hosted offering, no integrations beyond what the extension gives, no model-selection story (single Claude default).
- *Threat level:* **High for OSS mindshare**, low for stealing direct users — different buyers.

**OpenAI Operator / ChatGPT Agent** — *the model-vendor incumbent.*
- $200/mo on ChatGPT Pro. Uses its own remote browser (not yours). 61.3% on OSWorld. Now folded into ChatGPT Agent.
- **Where Brotto is competitive:** Brotto's extension acts on the *user's* real Chrome, not a remote proxy. For users with logged-in states, web app data, and consent to all data being processed on their own browser, this is materially better.
- **Where Brotto is weaker:** OpenAI has the model frontier, the safety research published, and a free agent inside the world's most-used chat product.
- *Threat level:* **High for any consumer-facing positioning**, low for power-user/plugin positioning.

**Perplexity Comet** — *the AI browser.*
- New Chromium-based browser, side panel assistant. Free + Perplexity Pro.
- Screenshot-based iterative workflow (per published reviews).
- **Where Brotto overlaps:** none meaningfully. Comet is a browser; Brotto is an extension shipping in the user's browser. Different buyer.
- *Threat level:* **Low** for now (different product shape), but as a brand-as-browser model it could compress all extension players.

**rtrvr.ai** — *the BYOK disruptor.*
- Free extension, BYOK. 81.4% success rate on its own benchmark. Marketing posture: "free with your own API keys vs Claude for Chrome at $200/mo."
- Same shape as Brotto (extension + remote agent) but extended to data-extraction/scraping.
- **Where Brotto overlaps:** structural twin. **Where Brotto is sharper:** Brotto's threat model is explicit *against* rtrvr's use cases (no scraping posture, no native browser, no IP rotation). rtrvr wins the indie/scrape market; Brotto should win the "I want my AI in my own logged-in browser" market.
- *Threat level:* **Medium.** Same shape, more polish, more marketing. The differentiator has to be visible.

**Skyvern** — *open-source, no selectors.*
- Computer vision + LLM, no brittle DOM selectors. API-first.
- Targets enterprise form-filling/data-extraction. Open source, retains infra.
- *Threat level:* **Medium.** Different stack (CV not CDP-AX), but increasingly the "deeply robust" alternative.

### 3.2 Adjacent

**Hermes Agent** *(self-improving general agent, not "browser-first")*
- 231k stars. Model-agnostic, runs on $5 VPS to GPU cluster. Browser via MCP. Closed learning loop, persistent memory, scheduled tasks, multi-platform gateway.
- *Threat level:* **High for developer mindshare**, low for direct user overlap. Their browser tooling is opt-in among many skills; Brotto's entire product is the browser.

**Stagehand (Browserbase)** — *deterministic + AI hybrid.*
- Open-source SDK. Code for stable paths, AI for unknown. Plugs into Browserbase cloud. The pragmatic middle.

**Notte** — *full-stack framework.*
- Claims to "eliminate integration pain" across the agent stack.

**Steel.dev / Hyperbrowser / Anchor Browser** — *raw browser infra.*
- $0.05–0.10/hr browser time. The pickaxe layer. Hyperbrowser 41% on multi-step benchmarks; Steel smallest $/hr.

---

## 4. Feature comparison matrix

| Capability | **Brotto** | **Browser-Use** | **Claude in Chrome** | **OpenAI Operator** | **Perplexity Comet** | **rtrvr.ai** | **Skyvern** |
|---|---|---|---|---|---|---|---|
| Extension in user's real browser | ✅ | ❌ (cloud or local) | ✅ | ❌ (remote) | n/a (full browser) | ✅ | ❌ |
| Cloud browser option | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| Server-only orchestrator | ✅ | partial (cloud) | ✅ (Anthropic) | ✅ (OpenAI) | ✅ (Perplexity) | ✅ (BYOK) | ✅ |
| Model-agnostic | ✅ (D6) | ✅ | ❌ (Claude only) | ❌ (OpenAI only) | ❌ (Perplexity + partners) | ✅ (BYOK) | ✅ |
| CDP-AX semantic targeting | ✅ (D1) | ✅ (DOM + AX) | ✅ (per docs) | unclear (vision-led) | ❌ (screenshots) | ✅ | ❌ (CV) |
| Coordinates-only clicking | ❌ (targeted) | partial | unclear | ❌ (vision) | ❌ | unclear | n/a |
| No-stealth / no-CAPTCHA-bypass posture | ✅ explicit | ❌ (selling it) | ✅ (Anthropic guidance) | ❌ | unclear | ❌ (selling it) | ❌ |
| Credential-coexistence story | ✅ (user's Chrome) | n/a | ✅ | ❌ (remote) | ✅ (local) | ✅ | ❌ |
| Critical-action approval flow | ✅ side panel | partial | ✅ ("guardrails") | ✅ | partial | unclear | ❌ |
| Reconnection / sequence tracking | ❌ (declared) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Eval suite with real-world tasks | ❌ (D10 unimplemented) | ✅ (100 hard tasks) | internal | internal (OSWorld 61.3%) | n/a | ✅ (81.4%) | internal |
| Open source | ✅ Apache-2.0 | ✅ MIT | ❌ | ❌ | ❌ | ❌ | ✅ |
| Pricing model | self-host | OSS free + $29/$299/mo cloud | $20–$200/mo | $200/mo | free + Pro | free BYOK | enterprise |
| Production battle-testing | low | very high | very high | very high | growing | low | niche |

---

## 5. SWOT for Brotto

### Strengths
- Differentiated threat model: the extension's *only* privilege is `chrome.debugger` on a user-selected tab. No cookies, no auth headers, no stealth. Architecturally honest "no CAPTCHA bypass" stance.
- Same agent code path for dev (Playwright) and extension (WS). Decoupled harness ⇒ cheap test harness.
- pydantic-ai + Anthropic default + model-agnostic keeps the door open.
- Apache-2.0 + clean repo + locked decisions ⇒ attracts contributors who dislike flaky open-core.
- Genuine product surface: a side panel with chat, plan, approval, clarify, scratchpad — the most complete UX outside of Claude in Chrome.

### Weaknesses
- No hosted offering. You have to run the Python server yourself. Limits adoption and revenue.
- No real-world eval suite (D10 unimplemented). Every claim is unverified.
- Sequence tracking & reconnection declared in the contract but not wired. Any tab navigation that disconnects the WS kills the session.
- Three overlapping agent loops in the orchestrator (`AgentHarness`, `AgentLoop`, `AgentLoopInferenceAdapter`). Only one is alive; the rest are dead weight and confuse the architecture.
- No e2e tests. The "production-grade" narration in `PLAN.md` is ahead of the `tests/` folder.
- `claude-haiku-4-5` pinned by default. No production user has benchmarked opus vs sonnet vs haiku on the harness.

### Opportunities
- **Enterprise "AI in your browser, but ours"** — the absence of a hosted Cloud product is actually a *feature* for IT/SOC teams that need BYO infrastructure. No one else owns this positioning. Own it loudly.
- **Verified no-stealth moat** — if Brotto publishes a transparent, testable `THREAT_MODEL.md` (it already has one) and accepts third-party audits, it becomes the default for regulated industries (banking, healthcare, legal) where Browser-Use and rtrvr.ai are excluded.
- **Power-user target** — devs/SREs/researchers who want a Claude in Chrome they can self-host on their own API keys. The rtrvr.ai pitch is BYOK-free; Brotto's is BYOK-with-trust.
- **Open eval suite as a wedge** — D10 is the single most valuable thing Brotto can ship. Real sites, fixed prompt versions, public leaderboard. Cuts through all marketing claims.
- **Distributed worker model** — the extension-as-only-priv architecture is genuinely novel vs Browser-Use and Clippy. If you can demonstrate it works for multi-tab workflows (the current single-tab assumption), it's a hard-to-replicate position.

### Threats
- Anthropic shipping a self-hostable Claude in Chrome (or just relaxing the plan requirement).
- Browser-Use adding a "please don't violate my target site" mode and siphoning the trust-first crowd.
- Chrome tightening `chrome.debugger` permissions for installed extensions (manifest V4 in flight).
- OpenAI bundling a "use my browser" bridge into ChatGPT Agent.
- The whole "browser agent" category getting commoditized by VLM-only screen-capture agents that don't need CDP at all (Perplexity Comet's screenshot workflow is the early sign).

---

## 6. Strategic recommendations

**1. Ship the eval suite (D10) before any feature work.**
Five real tasks on real sites, JSONL prompt versions, public leaderboard. The single biggest lever to make Brotto credible. Halve a week of model work to verify whether haiku-4-5 is actually viable at default. Identify the gap to browser-use's 78% / 89% claims — *they get measured, you do not.*

**2. Stand up a sanitized offline mode for the eval suite.**
Because of the "no real user site" risk for testing, even your eval needs fake credentials. Build a small suite of "fake login" sandboxes (Auth0 dev keys, sandboxed Gmail, etc.) that mirror real flows without depending on `gmail.com`. That's the only honest way to run D10.

**3. Make the threat model a sales pitch.**
Publish a single page: "What Brotto can never see, can never do, can never persist." Map it 1:1 against Browser-Use's docs (stealth, proxy rotation, CAPTCHA solving) and rtrvr.ai. Differentiate on the badge: "no-stealth-by-construction, auditable, Apache-2.0."

**4. Decide hosted or self-host and stop pretending both.**
The current story is "you run the server." If you want adoption, you need one of:
- Official Docker image + one-click Render/Fly deploy. *Or*
- A tiny managed Cloud that's read-only by default.
Mixing them is how you end up like Localstack — beloved by developers, starved for revenue.

**5. Kill the dead agent loops.**
Pick `AgentHarness`. Delete everything else. The `BrowserInterface` ABC is the right abstraction; there isn't a need for three implementations of the loop. Also: implement D9 sequence tracking in the same PR — it's two lines of glue and a state machine.

**6. Add a basic e2e test harness.**
One test per locked decision. D1: target extraction has stable IDs across reflow. D2: actions never resolve to coordinates. D5: error frames surface to the agent. D7: same agent runs in dev and extension mode. The repo has *zero* of these; you'll lose credibility if you ship the eval suite without them.

**7. Skip the multi-tab / multi-surface Cowork analog.**
Claude and Perplexity are spending thousands of engineer-hours on this. You are not. The right move is to be the *best single-tab, your-browser, trust-first* agent. Anyone trying to beat Anthropic on surface count is going to lose.

**8. Pick a model-default story and publish it.**
Pick the cheapest model that hits a documented eval score. Sonnet/Opus as a "premium" toggle. Document the eval that earned each model its slot. This is the most-read page on a browser-agent landing site.

**9. Watch Chrome V4.**
The extension's only structural advantage is `chrome.debugger`. If Chrome V4 limits or removes that, Brotto's entire differentiator evaporates. Track the manifest changes, file comments on the public threads, and have a fallback story (steered Playwright? rented Chrome via WebDriver BiDi?).

---

## 7. Bottom line

Brotto is the **only** open-source, independently-hosted, trust-first browser agent in the category. Browser-Use is the open-source leader but sells privacy-violating "stealth" as a feature. Claude in Chrome wins on brand and model. Perplexity Comet is a different shape. OpenAI Operator uses a remote browser and charges $200/mo.

The strategic window is **small** but **real**: regulated industries, security-conscious developers, and "I want it on my own hardware" buyers. The window closes if (a) Anthropic relaxes Claude in Chrome's paywall, (b) Browser-Use ships a privacy mode, or (c) Chrome V4 strips `chrome.debugger`. Ship the eval suite, ship the audit, tell the threat-model story loud. Skip the multi-surface war — you will lose it.

---

## 8. Sources

### Brotto (internal)
- `/Users/apple/Work/code/inventic/browser-automation/PLAN.md`
- `/Users/apple/Work/code/inventic/browser-automation/decisions.md`
- `/Users/apple/Work/code/inventic/browser-automation/docs/THREAT_MODEL.md`
- `/Users/apple/Work/code/inventic/browser-automation/docs/design-instructions.md`
- `/Users/apple/Work/code/inventic/browser-automation/clients/brotto-extension/`
- `/Users/apple/Work/code/inventic/browser-automation/services/brotto-orchestrator/`

### Browser-Use
- [github.com/browser-use/browser-use](https://github.com/browser-use/browser-use) — 99.7k stars, 0.13 release, Rust core
- [browser-use.com](https://browser-use.com/) — pricing tiers, stealth benchmarks
- [browser-use.com/posts/ai-browser-agent-benchmark](https://browser-use.com/posts/ai-browser-agent-benchmark) — 78% on 100 hard tasks
- [browser-use.com/posts/production-architecture-browser-use](https://browser-use.com/posts/production-architecture-browser-use) — production architecture writeup
- [respan.ai/market-map/compare/browser-use-vs-stagehand](https://www.respan.ai/market-map/compare/browser-use-vs-stagehand) — WebVoyager 89% claim
- [futureagi.com/blog/evaluating-browser-use-agents-2026](https://futureagi.com/blog/evaluating-browser-use-agents-2026/) — 78% WebArena vs 22% production gap

### Claude in Chrome
- [claude.com/claude-in-chrome](https://claude.com/claude-in-chrome) — Anthropic product page
- [claude.com/pricing](https://claude.com/pricing) — $20–$200/mo plans
- [claude.com/claude-in-chrome#send](https://claude.com/claude-in-chrome#send) — sensitive-action gates
- [anthropic.com/research/prompt-injection-defenses](https://anthropic.com/research/prompt-injection-defenses) — safety blog
- [agenticindex.io/vendors/claude-for-chrome](https://agenticindex.io/vendors/claude-for-chrome) — 7.5/14 capability score
- [rtrvr.ai/blog/rtrvr-vs-claude-for-chrome](https://www.rtrvr.ai/blog/rtrvr-vs-claude-for-chrome) — independent comparison

### Hermes Agent
- [github.com/NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) — 231k stars
- [hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs) — docs landing
- [hermes-agent.nousresearch.com/docs/integrations](https://hermes-agent.nousresearch.com/docs/integrations/) — browser integration
- [github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/browser.md](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/browser.md) — browser tool docs
- [github.com/NousResearch/hermes-agent/issues/15445](https://github.com/NousResearch/hermes-agent/issues/15445) — Obscura backend discussion

### OpenAI Operator / ChatGPT Agent
- [openai.com/index/introducing-operator](https://openai.com/index/introducing-operator/) — launch
- [openai.com/index/computer-using-agent](https://openai.com/index/computer-using-agent/) — CUA API
- [openai.com/index/introducing-chatgpt-agent](https://openai.com/index/introducing-chatgpt-agent/) — Operator folded into ChatGPT Agent
- [coasty.ai/blog/openai-operator-review-2026-20260403](https://coasty.ai/blog/openai-operator-review-2026-20260403) — 61.3% OSWorld
- [futureagi.com/blog/openai-operator-2025](https://futureagi.com/blog/openai-operator-2025/) — 2026 status & alternatives

### Perplexity Comet
- [perplexity.ai/comet](https://www.perplexity.ai/comet) — product page
- [perplexity.ai/hub/blog/introducing-comet](https://www.perplexity.ai/hub/blog/introducing-comet) — launch
- [efficient.app/apps/comet](https://efficient.app/apps/comet) — 2026 review
- [humansecurity.com/ai-agent/perplexity-comet](https://www.humansecurity.com/ai-agent/perplexity-comet/) — security posture

### rtrvr.ai
- [rtrvr.ai/blog/rtrvr-vs-claude-for-chrome](https://www.rtrvr.ai/blog/rtrvr-vs-claude-for-chrome) — 81.4% success rate, BYOK positioning
- [rtrvr.ai/blog/rtrvr-vs-apify](https://www.rtrvr.ai/blog/rtrvr-vs-apify) — vs scraping platforms
- [rtrvr.ai/blog/rtrvr-vs-chat4data-thunderbit-browse-ai-bardeen](https://www.rtrvr.ai/blog/rtrvr-vs-chat4data-thunderbit-browse-ai-bardeen) — annual cost comparison

### Skyvern
- [skyvern.com](https://www.skyvern.com/) — open-source CV approach
- [skyvern.com/blog/anchorbrowser-vs-skyvern](https://www.skyvern.com/blog/anchorbrowser-vs-skyvern/) — June 2026 comparison
- [skyvern.com/blog/browserbase-vs-stagehand-which-is-better](https://www.skyvern.com/blog/browserbase-vs-stagehand-which-is-better/) — framework comparison

### Browserbase / Stagehand
- [browserbase.com/stagehand](https://www.browserbase.com/stagehand) — hybrid code+AI
- [morphllm.com/stagehand-mcp](https://www.morphllm.com/stagehand-mcp) — MCP integration

### Anchor Browser
- [anchorbrowser.io](https://anchorbrowser.io/) — cloud browser for agents
- [o-mega.ai/articles/top-10-anchor-browser-alternatives-2026](https://o-mega.ai/articles/top-10-anchor-browser-alternatives-2026) — landscape

### Steel.dev / Hyperbrowser / Notte
- [steel.dev](https://steel.dev/) — $0.05–0.10/hr browser infra
- [steel.dev/blog](https://steel.dev/blog) — pricing tiers
- [llms.steel.dev/articles/browser-infrastructure-for-ai-agents-compared](https://llms.steel.dev/articles/browser-infrastructure-for-ai-agents-compared/) — 5-way infra comparison
- [joinnextdev.com](https://www.joinnextdev.com/a/hyperbrowser/steeldev-vs-hyperbrowser-which-wins-for-ai-agents) — Steel vs Hyperbrowser
- [humanbrowser.cloud/compare/best-cloud-browsers-for-ai-agents](https://humanbrowser.cloud/compare/best-cloud-browsers-for-ai-agents) — pricing
- [proxidize.com/blog/best-cloud-browsers-for-ai-agents](https://proxidize.com/blog/best-cloud-browsers-for-ai-agents/) — 7 options
- [aimultiple.com/remote-browsers](https://aimultiple.com/remote-browsers) — Steel 45%, Hyperbrowser 41%
- [notte.cc/blog/browser-agent-stack-2026](https://www.notte.cc/blog/browser-agent-stack-2026) — taxonomy

### Aggregator comparisons
- [firecrawl.dev/blog/best-browser-agents](https://www.firecrawl.dev/blog/best-browser-agents) — 11-way comparison
- [dev.to/stevengonsalvez/browser-tools-for-ai-agents-part-2-the-framework-wars-browser-use-stagehand-skyvern-4gn](https://dev.to/stevengonsalvez/browser-tools-for-ai-agents-part-2-the-framework-wars-browser-use-stagehand-skyvern-4gn) — framework wars
- [scrapfly.io/blog/posts/best-ai-browser-agents](https://scrapfly.io/blog/posts/best-ai-browser-agents) — 7 best
- [o-mega.ai/articles/top-10-browser-use-agents-full-review-2026](https://o-mega.ai/articles/top-10-browser-use-agents-full-review-2026) — 10-way review
- [leaderboard.steel.dev](https://leaderboard.steel.dev/) — benchmark leaderboards
- [moclaw.ai/blog/ai-browser-automation-tool-2026-guide](https://moclaw.ai/blog/ai-browser-automation-tool-2026-guide) — 2026 guide

### Research papers
- [arxiv.org/html/2510.03285v1](https://arxiv.org/html/2510.03285v1) — WAREX WebArena reliability
- [invariantlabs.ai/blog/what-we-learned-from-analyzing-web-agents](https://invariantlabs.ai/blog/what-we-learned-from-analyzing-web-agents) — failure analysis
- [halluminate.ai/blog/benchmark](https://halluminate.ai/blog/benchmark) — Web Bench
- [openreview.net/pdf?id=lmeXa6aaoR](https://openreview.net/pdf?id=lmeXa6aaoR) — BrowserArena
- [reddit.com/r/AI_Agents/comments/1v695rl](https://www.reddit.com/r/AI_Agents/comments/1v695rl/i_benchmarked_my_browser_agent_against_browser/) — independent benchmark
