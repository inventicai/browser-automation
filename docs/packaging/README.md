# Extension packaging & distribution

Brotto's browser extension is published without going through the Chrome Web Store. **The channel is GitHub Releases** — each `v*` tag gets a signed `.crx` attached as a release artifact.

## How a release ships

1. Engineer bumps `version` in `clients/brotto-extension/manifest.json` and `package.json`.
2. Engineer pushes a `v*` Git tag (e.g. `git tag v1.0.1 && git push origin v1.0.1`).
3. `.github/workflows/release.yml` runs:
   - Builds the extension (`npm run build`)
   - Runs `scripts/release.mjs` to sign the CRX (`dist/brotto.crx`) and zip the unpacked variant for Edge Add-ons (`dist/brotto-edge.zip`)
   - Creates a GitHub Release at the tag, attaching both files
4. Chrome testers download `brotto.crx` from the Releases page and drag it into `chrome://extensions/`.

## Auto-update

**Not active today.** `update.xml` requires a hosting layer (Cloudflare Pages, GitHub Pages, etc.) that we deferred. When/if we add one, `scripts/release.mjs` can be extended to emit the manifest alongside `brotto.crx` — no schema changes needed.

## Testers — installing the local build

Before a tag has been pushed, the local `dist/brotto.crx` works as a one-off:

1. `cd clients/brotto-extension && npm run build && npm run release:chrome`
2. Open `chrome://extensions/`
3. Enable **Developer mode** (top-right, once per browser)
4. Drag `clients/brotto-extension/dist/brotto.crx` onto the page
5. Confirm the install prompt
6. Brotto icon appears in toolbar; click it for the side panel

## Repo map

```
clients/brotto-extension/
  scripts/release.mjs       CRX pack + Edge ZIP (update.xml dormant)
  manifest.json             version, no update_url
  crx-signing.pem           gitignored; lives in 1Password + GH secret BROTTO_CRX_PEM

.github/workflows/release.yml
  Triggered on tag v*  →  builds, signs, attaches CRX + ZIP to a GitHub Release
```

## Setup checklist (one-time)

- [ ] Generate `clients/brotto-extension/crx-signing.pem` once via `openssl genrsa -out clients/brotto-extension/crx-signing.pem 2048`. Back up out-of-band (1Password or similar). Store contents in the `BROTTO_CRX_PEM` GitHub secret.
- [ ] Done. Push a `v*` tag and the GH Action does the rest.

## Future work (deferred)

- **Hosted auto-update** — re-introduce CF Pages or GH Pages once we have a real domain. `scripts/release.mjs` already has the shape; we'd just plug the URL back in.
- **Edge Add-ons** — `docs/packaging/edge-unlisted.md` is a Partner Center runbook ready when needed. Pull `brotto-edge.zip` from each GH Release.

## Threat-model notes

This is a power-tool extension with `debugger` and `<all_urls>` permissions. Distributing via GH Releases keeps it off the public Chrome Web Store and the install link is internal-only. The signing key controls the extension identity — if it leaks, treat as compromised and rotate. See `THREAT_MODEL.md` at the repo root for the full security picture.
