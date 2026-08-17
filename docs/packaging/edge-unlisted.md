# Publishing Brotto on Edge Add-ons (unlisted)

## Why this exists

Edge Add-ons Unlisted is the path of zero-friction install for non-engineer testers: you send them a link, they click it, the extension lands in their browser. No DevTools, no "load unpacked", no Slack back-and-forth about how to flip a toggle in `edge://extensions`. This doc walks you through listing Brotto as unlisted on Partner Center so testers can install it with one click.

## 1. Account setup (one-time)

1. Go to https://partner.microsoft.com/dashboard/microsoftedge/overview and sign in with a Microsoft account. If you don't have one, create it first — a personal Outlook account is fine.
2. Pay the one-time **$0 developer registration fee**. Yes, even for unlisted. Microsoft still wants a publisher on file. Have a credit card on the account; the charge is symbolic but real.
3. Verify your publisher info (name, contact email, website). Use the Inventic contact details — this is what testers will see if they dig.
4. Once your dashboard loads, you're done. Bookmark it. You'll be back here every time you ship a new build.

## 2. Create the unlisted listing

1. In Partner Center, click **New extension** → **Manual upload**.
2. **Package type:** pick **Edge** (the "Chromium-style" platform option, not the legacy Edge add-in).
3. **Manifest version:** 3.
4. **Upload** the ZIP at `dist/brotto-edge.zip`. This file is produced by running `node clients/brotto-extension/scripts/release.mjs` from the repo root — the release script bumps the version in `manifest.json`, builds the extension, and drops the Edge-formatted ZIP into `dist/`. You don't need to touch the script; just run it.
5. **Visibility:** **Unlisted**. This is the whole point. People with the link can install it; it won't show up in the Add-ons search results.
6. **Pricing:** Free.

Click through the wizard until you land on the listing dashboard. Now the real work: filling out the tabs.

## 3. Store listing tabs

Partner Center shows several tabs for you to fill in. Here's what each one needs.

### Store listing (English)

- **Short name:** `Brotto`
- **Short description:** ≤132 characters. Something like: *"Drive your real browser with any AI model. Model-agnostic, open-source."* (lifted from `manifest.json`).
- **Long description:** the first two paragraphs of `clients/brotto-extension/README.md`. Copy them verbatim.
- **Category:** Productivity.
- **Screenshots:** minimum 1, max 5. Capture them from the side panel: open the extension in Edge, click the toolbar icon to open the side panel, run a quick automation task, and screenshot anything that looks good (the side panel itself, an in-flight task, a confirmed "done" state). PNG or JPEG, 1280×800 minimum.
- **Small icon (128×128):** the mountain mark from `assets/`. PNG with a transparent background.

### Privacy

Partner Center will ask you to justify each permission the extension declares. Here's the mapping for `manifest.json`:

- **`debugger`** — The core automation capability. Drives clicks, typing, screenshots, nav in the tab you selected. Allowlist of CDP commands; no arbitrary JS execution; attaches only when you click "Attach." *No remote code execution — the agent sends structured actions, not scripts.*
- **`<all_urls>`** — Means "the extension can theoretically talk to any site," not "it silently does." In practice, the extension only attaches to a tab you explicitly pick. Sensitive sites (banking, email, login) trigger a warning before attachment.
- **`tabs`** — Lists open tabs so you can pick which one to automate. Reads only titles, URLs, and favicons — never page content.
- **`sidePanel`** — Opens the side panel UI where the conversation with the agent lives.
- **`webNavigation`** — Used to detect when the selected tab finishes loading so the agent can keep going.
- **`storage`** — Saves your server URL and pairing state locally. Nothing leaves your machine.

Paste the relevant chunks from `clients/brotto-extension/PERMISSIONS.md` directly into the justification fields. The "Security Controls" and "What It Does NOT Enable" sections are exactly the tone Partner Center reviewers want to see.

### Single-purpose / justification

This is the free-text box where you explain what the extension does and why each permission is necessary. One line per permission is enough:

- **`debugger`** — Drive the user's selected browser tab via CDP (click, type, screenshot, navigate).
- **`<all_urls>`** — Allow automation on any website the user chooses; the extension does not auto-attach to anything.
- **`tabs`** — Let the user pick which tab to automate.
- **`sidePanel`** — Show the agent UI in the browser side panel.
- **`webNavigation`** — Detect navigation events in the attached tab.
- **`storage`** — Remember the server URL and pairing state between sessions.

End with a one-liner: *"Brotto is model-agnostic, open-source, and never executes arbitrary code from the server. All actions are structured CDP commands from an allowlist."*

## 4. Submit for review

Hit **Submit**. Unlisted submissions are typically reviewed within **24–72 hours** — usually faster, but don't promise a tester "by tomorrow morning."

If you get rejected, don't panic. Read the reviewer's comment carefully — they almost always name the exact paragraph or screenshot that needs work. Fix it, re-upload, resubmit. Don't argue in the comments; iterate.

When approved, the dashboard shows a **share link**. Copy it. That's the link you paste into your Slack DM to the tester. They click it, Edge prompts to install, they're done.

## 5. Updating the listing when a new release ships

Bump the version in `clients/brotto-extension/manifest.json` (the release script does this automatically when you run `node clients/brotto-extension/scripts/release.mjs`), re-run the script to produce a fresh `dist/brotto-edge.zip`, then in Partner Center upload the new ZIP as a new package and bump the **Version** field on the store listing tab. Resubmit. Same 24–72 hour window applies. Update the share link in your tester-invite doc with the new one once it's approved.

## Appendix — quick checklist

- [ ] Partner Center account created, $0 fee paid, publisher info verified
- [ ] `node clients/brotto-extension/scripts/release.mjs` run, `dist/brotto-edge.zip` ready
- [ ] New extension → Manual upload → Edge → MV3 → ZIP uploaded
- [ ] Visibility: Unlisted
- [ ] Pricing: Free
- [ ] Store listing: short name, description (≤132), long description (README first two paragraphs), category (Productivity), screenshots (≥1), 128×128 icon
- [ ] Privacy tab: each permission justified, PERMISSIONS.md language pasted in
- [ ] Single-purpose tab: one-line justification per permission + no-remote-code-exec note
- [ ] Submitted, share link saved, sent to testers
