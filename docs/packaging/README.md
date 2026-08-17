# Extension packaging & distribution

Brotto's browser extension is published without going through the Chrome Web Store. **The channel is GitHub Pages** — each `v*` tag gets a signed `.crx` and a Chrome `update.xml` deployed to a `gh-pages` branch, which GitHub Pages serves at `https://inventicai.github.io/browser-automation/`.

## How a release ships

1. Engineer bumps `version` in `clients/brotto-extension/manifest.json` and `package.json`.
2. Engineer pushes a `v*` Git tag (e.g. `git tag v1.0.1 && git push origin v1.0.1`).
3. `.github/workflows/release.yml` runs:
   - Builds the extension (`npm run build`)
   - Runs `scripts/release.mjs` to sign the CRX (`dist/brotto.crx`), write `dist/update.xml`, and zip the unpacked variant for Edge Add-ons (`dist/brotto-edge.zip`)
   - Stages `dist/brotto.crx` and `dist/update.xml` into `install/release/`
   - Pushes the `install/` directory to the `gh-pages` branch via `peaceiris/actions-gh-pages`
   - Attaches `brotto-edge.zip` to a GitHub Release at the tag
4. Chrome testers visit the Pages URL, click Download, drag the `.crx` into `chrome://extensions/`.
5. Chrome then auto-polls `update.xml` on subsequent launches and pulls newer `brotto.crx` versions transparently.

## Auto-update

**Active.** The manifest's `update_url` points at `https://inventicai.github.io/browser-automation/release/update.xml`. Each release overwrites that file with the new version. Chrome's auto-updater respects it for self-hosted CRX installs (Developer-mode drag-drop). CRX3 requires strict-monotonic version bumps — never ship a re-tag of the same version.

## Tester install path

1. Visit [https://inventicai.github.io/browser-automation/](https://inventicai.github.io/browser-automation/)
2. Click **Download Brotto for Chrome** (saves `brotto.crx` via the `release/` path)
3. `chrome://extensions/` → Developer mode on (one-time) → drag `brotto.crx` onto the page → confirm
4. Toolbar icon appears; click for the side panel

## Local install before first tag (faster than waiting on CI)

```
cd clients/brotto-extension && npm run build && npm run release:chrome
```
Then drag `clients/brotto-extension/dist/brotto.crx` onto `chrome://extensions/`. (No auto-update, since the manifest's `update_url` only works when GH Pages serves the matching `update.xml`.)

## Repo map

```
clients/brotto-extension/
  scripts/release.mjs       CRX pack + update.xml + Edge ZIP
  manifest.json             version + update_url pointing at GH Pages
  crx-signing.pem           gitignored; lives in 1Password + GH secret BROTTO_CRX_PEM

install/                    GH Pages source (peaceiris deploys to `gh-pages` branch)
  index.html                landing page with the download button
  release/                  CI-staged: brotto.crx + update.xml (gitignored)

.github/workflows/release.yml
  Triggered on tag v*  →  builds, signs, deploys to gh-pages, attaches Edge ZIP to GH Release
```

## Setup checklist (one-time)

- [ ] **Generate the signing key.** `openssl genrsa -out clients/brotto-extension/crx-signing.pem 2048`. Back up out-of-band (1Password). Store contents in the `BROTTO_CRX_PEM` GitHub secret (include BEGIN/END markers and newlines).
- [ ] **Enable GitHub Pages.** Repo → Settings → Pages → Source = "Deploy from a branch" → branch = `gh-pages`, folder = `/` (root). Save. (The first tag push auto-creates the `gh-pages` branch via `peaceiris/actions-gh-pages`.)
- [ ] **Verify the URL.** After the first tag lands, `https://inventicai.github.io/browser-automation/` should serve the install landing. If the org is private or the repo is private, GitHub Pages is gated — flip repo visibility or use a separate public mirror, your call.

That's it. Push a `v*` tag and the GH Action does the rest.

## Threat-model notes

This is a power-tool extension with `debugger` and `<all_urls>` permissions. Distributing via GH Pages keeps it off the public Chrome Web Store and the install link is internal-only. Two specific risks worth flagging:

- **The signing key controls the extension identity.** If `crx-signing.pem` leaks, treat as compromised and rotate. The `update_url` is also a trust anchor — if GH Pages DNS were hijacked, Chrome could ship a malicious update. Worth pinning or moving to a domain you control once you have one.
- **Auto-update opt-out.** Chrome may auto-update installed copies on its own schedule. If a release has a critical bug, `update.xml` can be edited to point at a known-good CRX, but rotation is faster than recall.

See `THREAT_MODEL.md` at the repo root for the full picture.
