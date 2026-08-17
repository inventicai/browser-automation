# Contributing

## Workflow

1. Branch off `main`.
2. Push commits to your branch.
3. Open a PR targeting `main`.
4. Wait for the **`CI`** check (aggregator of orchestrator tests + extension build) to go green.
5. Wait for a reviewer assigned by `.github/CODEOWNERS` to approve.
6. Squash-merge once both are green.

Direct pushes to `main` are blocked by branch protection — see below.

## Required local checks before pushing

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

## Branch protection setup (one-time, repo admin)

The CI workflow in `.github/workflows/ci.yml` provides a single
required check named **`CI`** (an aggregator job that fails if either
of `Orchestrator tests` or `Extension build` fails). Branch protection
must require it.

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

After this runs, `main` is merge-locked: PRs need green CI plus a
CODEOWNERS approval, and no one — admins included — can push directly.

## Adjusting CODEOWNERS

`.github/CODEOWNERS` ships pointing at `@inventicai/maintainers`. If
that team does not exist yet, replace it with a real GitHub team
(Settings → Teams) or individual `@handle`s before the first PR — a
missing owner silently turns auto-assignment off.

## Commit conventions

See `CLAUDE.md` → "Commit Conventions". No AI-tool trailers, ever.
`git filter-repo` has been used historically to clean up slips; please
strip any auto-injected trailer before committing.