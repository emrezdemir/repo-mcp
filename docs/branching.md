# Branching and configuration

## Branches

```
main   ← stable. Only ever updated by merging dev.
  ▲
  │  merge, by the maintainer
  │
dev    ← integration branch. All work lands here first.
  ▲
  │  pull request (or direct push, for small changes)
  │
feature branches
```

- **`dev`** is where development happens. Branch from it, and open pull
  requests against it.
- **`main`** is stable. It only moves when someone merges `dev` into it —
  never by a direct push.

```bash
git checkout dev
git pull origin dev
git checkout -b feature/short-description
# work
git push -u origin feature/short-description
```

CI runs on both long-lived branches and on every pull request targeting
either.

## Branch names

`<type>/<short-description>`, lowercase kebab-case, at most 60 characters.
The type is not decoration — it says where the branch comes from, where it
goes, and how urgent it is.

| Type | Branch from | Merges into | Use for |
| --- | --- | --- | --- |
| `feature/` | `dev` | `dev` | New capability or a change in behaviour |
| `bugfix/` | `dev` | `dev` | A defect found in `dev`, not yet released |
| `hotfix/` | **`main`** | **`main` and `dev`** | A defect in released code that cannot wait for the next merge |
| `chore/` | `dev` | `dev` | Tooling, dependencies, refactors with no behaviour change |
| `docs/` | `dev` | `dev` | Documentation only |

```
feature/config-in-database      good
bugfix/webhook-signature-utf8   good
hotfix/token-leak-in-audit-log  good
chore/bump-ruff                 good

my-branch                       no type
feature/Fix_Stuff               not kebab-case
claude/whatever                 never name a branch after a tool or a person
```

**`hotfix/` is the one to get right.** It branches from `main`, because `dev`
may contain unreleased work that must not ship with an urgent fix. It merges
into **both** `main` and `dev` — a hotfix that only lands on `main` is
reintroduced by the next `dev` merge.

```bash
# hotfix
git checkout main && git pull origin main
git checkout -b hotfix/short-description
# fix, then merge into main (maintainer) and into dev (you)
git checkout dev && git merge hotfix/short-description
```

Branch names are checked by `scripts/check-branch.sh`, which runs in the
pre-commit hook and in CI on every pull request.

## Why main and dev never conflict

The usual reason two long-lived branches fight on every merge is
environment-specific configuration: one branch points at staging, the other at
production, and the same lines change on both sides forever.

That cannot happen here, because **no environment-specific value is tracked at
all**:

| Tracked (identical on every branch) | Untracked (differs per deployment) |
| --- | --- |
| `deploy/.env.example` | `deploy/.env` |
| `deploy/tenants.example.yaml` | `deploy/tenants.yaml` |
| `deploy/scan.example.yaml` | `deploy/scan.yaml` |
| `deploy/helm/values-*.example.yaml` | `deploy/helm/values-*.yaml` |
| Helm chart defaults in `values.yaml` | your own values file, passed with `-f` |

Every real value arrives from the environment, from an ignored file, from a
Kubernetes secret, or — for anything an administrator can change — from the
database. `main` and `dev` therefore carry byte-identical configuration, and a
merge only ever has to reconcile actual code.

CI enforces this: a job fails if `.env`, `deploy/tenants.yaml`,
`deploy/scan.yaml` or a non-example `deploy/helm/values-*.yaml` is ever
tracked on any branch.

## dev never falls behind main

Merging `dev` into `main` through a pull request leaves one commit on `main`
that `dev` never gets: the merge commit GitHub writes. The content is
identical — a diff between the two branches shows nothing — but the history
diverges by one commit per release, and from then on every comparison reports
a difference that is not a difference.

`.github/workflows/sync-dev.yml` closes it. On every push to `main` it
fast-forwards `dev` to `main`, which is always possible at that moment because
`dev` is an ancestor of `main`.

Three things it deliberately does not do:

- **It does not force.** If `dev` has moved on since the pull request merged,
  the push is not a fast-forward, the server refuses it, and the job fails
  with the offending commits printed. Nothing pushed to `dev` in the meantime
  is discarded.
- **It does not merge.** A merge would create yet another commit and put the
  branches back where they started.
- **It does nothing when there is nothing to do**, so a push to `main` that
  `dev` already contains is a no-op rather than an empty commit.

If `dev` is a protected branch, the workflow's push needs to be allowed
through — otherwise the job fails on every release with a permissions error
rather than silently doing nothing.

### Doing it without a pull request

If you would rather not have the merge commit at all, push `dev` straight to
`main`:

```bash
git push origin dev:main
```

That is a genuine fast-forward: no merge commit, nothing to sync back, and the
workflow above finds nothing to do. The trade is that there is no pull request
to review or to hang the checks on, so this suits a repository with one
maintainer and not much else.

## Branches are not environments

`main` and `dev` are a code lifecycle. Where the code *runs* is decided by
which image tag an environment deploys, not by which branch it sits on:
`dev` publishes `:dev-<sha>`, a version tag publishes `:vX.Y.Z`, and
production runs a tag that already ran in dev. Adding an environment is a
values file and a database, never a fourth long-lived branch.

The mechanics are in [environments.md](environments.md), and the reasoning in
[ADR-0008](adr/0008-environments-and-promotion.md).

## Secrets never reach the repository

Three layers, because each one alone has a hole:

1. **`.gitignore`** — stops the accident. Does nothing for a file that is
   already tracked, or one added with `git add -f`.
2. **`scripts/check-secrets.sh`** as a pre-commit hook — refuses forbidden
   paths and credential-shaped content before the commit exists. Installed by
   `make setup`, or on demand:

   ```bash
   make hooks
   ```

3. **CI** — scans every tracked file on every push and pull request, so a
   contributor who has not installed the hook is still caught before merge.

Check the current state at any time:

```bash
make check-secrets
```

The scanner looks for two things: paths that must never be tracked (`.env`,
the real config files, private keys, database files) and credential shapes in
content (GitHub, GitLab, Slack, AWS and OpenAI token formats, private key
headers, JWTs, and assignments carrying an inline value where an environment
reference is expected).

Patterns are length-anchored so documentation placeholders such as `ghp_...`
do not trip them. A scanner that cries wolf gets bypassed, and then it
protects nothing.

If something is genuinely a false positive, `git commit --no-verify` gets you
past it — please open an issue so the pattern can be tightened.

## If a secret does get committed

Removing it in a later commit is not enough; it stays in history and must be
treated as disclosed.

1. **Rotate the credential first.** Everything else is cleanup.
2. Remove it from history (`git filter-repo`, or BFG) and force-push.
3. Tell everyone with a clone to re-clone — a rewritten history plus an old
   clone reintroduces the secret on the next push.

See [SECURITY.md](../SECURITY.md) for reporting.
