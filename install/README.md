# Brotto install / distribution site

This directory is the static landing page that Brotto's self-hosted extension
distribution links to. It's a plain HTML/CSS file deployed as a Cloudflare
Pages project so we control the install URL (instead of forcing users through
the Chrome Web Store).

## How deploy works

```bash
npx wrangler pages deploy install --project-name=brotto-dist --branch=main
```

`wrangler` is already authenticated (account id is resolved from the existing
login), so no flags besides `--project-name` and `--branch` are required for a
fresh deploy. The whole `install/` directory is uploaded as the Pages
artifact.

## What gets uploaded where

- `install/index.html` becomes the project's root (`/`) on
  `brotto-dist.pages.dev`.
- `brotto.crx` and `update.xml` (extension artifacts produced by the
  extension's own build) are uploaded by a separate `wrangler pages deploy`
  of a sibling `dist/` directory, wired up in CI. That CI upload is out of
  scope here &mdash; this README only covers the landing page.
- The landing page links to `brotto.crx` as a relative path, so it resolves
  against whichever host serves the extension binary (the `dist/` Pages
  project, in production).

## Custom domain setup

From the Cloudflare dashboard: open the `brotto-dist` Pages project, go to
**Custom domains**, and add `dist.inventic.ch` (or whatever the live host
will be). Cloudflare provisions the certificate and CNAME automatically
because the zone is already on the same account &mdash; nothing else to
configure here. Update the install links in `clients/brotto-extension/` to
point at the custom host before publishing the extension.

## Local preview

```bash
npx wrangler pages dev install/
```

This serves the directory locally with the same routing Pages uses in
production. For a quick eyeball without installing wrangler, any static
server works: `python3 -m http.server` from the repo root and open
`http://localhost:8000/install/`.