# Contributing

## Workflow

1. Branch off `main`.
2. Push commits to your branch.
3. Open a PR targeting `main`.
4. Wait for the **`CI`** check (aggregator of orchestrator tests + extension build) to go green.
5. Wait for a reviewer assigned by `.github/CODEOWNERS` to approve.
6. Squash-merge once both are green.

Direct pushes to `main` are blocked by branch protection — see below.

## Local checks before pushing

Run the same checks CI runs locally:

```bash
# Orchestrator tests (Python 3.12 + uv)
uv sync --group dev
uv run pytest services/brotto-orchestrator/tests -v

# Extension build (Node 20 + npm)
cd clients/brotto-extension
npm ci
npm run build          # esbuild bundle
npx tsc --noEmit       # type check (CI runs both)
```

A green run here usually matches a green CI run.

## Commit conventions

- No AI-tool trailers in commit messages. That means no `Co-Authored-By: …` from any AI assistant, no "Generated with [tool]" footers, no body text naming an AI assistant, vendor, or `noreply@…` address. Commit authors appear as humans only.
- If a template or tool auto-injects such a trailer, strip it before `git commit` runs. Applies to every commit on every branch in this repo, including past history.
- `git filter-repo` has been used historically to clean up slips.

## Repository hygiene — model neutrality

The agent layer is model-agnostic (D6); the public source must match.

- No file in this repository may name a specific AI model identifier — not in source, tests, CI, docs, examples, READMEs, or decision records.
- Source defaults come from env (`AGENT_MODEL`); never hardcode a specific model id as a fallback. Raise on missing env rather than naming one.
- Tests must not pass model-id literal strings; parametrize from a fixture or assert against the env value.
- CI matrices source model lists from secrets or workflow-level env, not the committed YAML.
- Documentation, competitive analysis, and benchmark READMEs may discuss models in general terms ("frontier vs mid-tier latency", "the default agent model") but must not name specific ids.
- Applies retroactively: when a leak is found in existing code or docs, flag it and scrub it; don't leave it because it pre-dates the rule.
- To rotate or add models, change env / secrets — not source.

## Branch protection setup (one-time, repo admin)

The CI workflow in `.github/workflows/ci.yml` provides a single required check named **`CI`** (an aggregator job that fails if either of `Orchestrator tests` or `Extension build` fails). Branch protection must require it.

Configure once via **GitHub → Settings → Branches → Add rule**:

| Setting | Value |
|---|---|
| Branch name pattern | `main` |
| Require a pull request before merging | ✓ |
| Require approvals | ✓ (1 minimum) |
| Dismiss stale pull request approvals when new commits are pushed | ✓ |
| Require review from Code Owners | ✓ |
| Require status checks to pass before merging | ✓ |
| Status checks that must pass | `CI` |
| Require linear history | ✓ |
| Do not allow force pushes | ✓ |
| Do not allow deletions | ✓ |
| Do not allow bypass for repository administrators | ✓ (recommended) |

### One-time CLI alternative

If you prefer scripting the rule (or want to keep it in source-of-truth):

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/inventicai/browser-automation/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["CI"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false
}
JSON
```

After this runs, `main` is merge-locked: PRs need green CI plus a CODEOWNERS approval, and no one — admins included — can push directly.

## Adjusting CODEOWNERS

`.github/CODEOWNERS` ships pointing at `@inventicai/maintainers`. If that team does not exist yet, replace it with a real GitHub team (Settings → Teams) or individual `@handle`s before the first PR — a missing owner silently turns auto-assignment off.