# Extension packaging & distribution

Brotto's browser extension is published without going through the Chrome Web Store. Two channels, both internal-only:

## What each channel looks like

| Channel | Audience | What tester does | Auto-updates |
|---|---|---|---|
| Self-hosted CRX on Cloudflare Pages | Chrome engineers + power users | Visit `https://dist.inventic.ch/`, drag-drop `brotto.crx` onto `chrome://extensions/` once | Yes, via `update.xml` |
| Unlisted Edge Add-ons | Chrome + Edge non-engineers | Click a Partner Center share-link, install | Yes, native |

The Chrome channel takes ~2 days of plumbing (one-time). The Edge channel is a manual Partner Center submission — first time takes ~30 minutes; subsequent updates are a ZIP upload.

## How a release ships

1. Engineer bumps `version` in `clients/brotto-extension/manifest.json` and `package.json` (CRX3 requires strict-monotonic).
2. Engineer pushes a `v*` Git tag.
3. `.github/workflows/release.yml` runs:
   - Builds the extension (`npm run build`)
   - Runs `scripts/release.mjs` to sign + pack the CRX, write `update.xml`, and zip for Edge
   - Deploys `brotto.crx` + `update.xml` + the install page to Cloudflare Pages
   - Attaches `brotto-edge.zip` to a GitHub Release (so a release engineer can re-upload to Partner Center)
4. Chrome testers pick up the update on next browser launch; Edge listings need a manual re-upload.

## Repo map

```
clients/brotto-extension/
  scripts/release.mjs       CRX pack + update.xml + Edge ZIP
  manifest.json             update_url, version
  crx-signing.pem           gitignored, lives in 1Password or GH secret BROTTO_CRX_PEM
install/                    Cloudflare Pages static site (landing page)
wrangler.toml               Pages project config
.github/workflows/release.yml
  Released to git tag v*  → builds + publishes
```

## Setup checklist (one-time)

- [ ] Generate `clients/brotto-extension/crx-signing.pem` once via `openssl genrsa -out clients/brotto-extension/crx-signing.pem 2048`. Back up out-of-band (1Password or similar). Store contents in the `BROTTO_CRX_PEM` GitHub secret.
- [ ] Provision a Cloudflare Pages project named `brotto-dist` and bind `dist.inventic.ch` (or your domain of choice) to it. Add `CF_API_TOKEN` + `CF_ACCOUNT_ID` as GitHub secrets.
- [ ] For Edge unlisted: see `docs/packaging/edge-unlisted.md` (one-time, ~30 minutes).

## Updating the Edge listing

After each tagged release:

1. Download `brotto-edge.zip` from the GitHub Release.
2. Partner Center → Brotto listing → Package → upload new ZIP → bump version field → submit.

Typically reviewed in 24–72 hours.

## Threat-model considerations

This is a power-tool extension with `debugger` and `<all_urls>` permissions. Both packaging channels keep it off the public Web Store, which means:

- The risk surface is the set of people with the install link.
- Auto-update URLs (`update.xml`) and host manifest are set in `manifest.json` — if those URLs change, the extension can be silently disabled by Chrome. Pin or sign them.
- The signing key (`crx-signing.pem`) controls the extension identity. **If it leaks, treat it as compromised and rotate.**

See `THREAT_MODEL.md` at the repo root for the full security picture.
