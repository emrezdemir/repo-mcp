# Development

## Branching

Work happens on **`dev`**; `main` only moves when `dev` is merged into it.

```bash
git checkout dev
git pull origin dev
```

Configuration never differs between the two branches, so those merges do not
conflict over environment values. See [branching.md](branching.md).

## Setup

```bash
make setup
```

Creates a virtualenv per service, installs dependencies, copies the example
configuration into `deploy/tenants.yaml` and `deploy/scan.yaml`, and writes
`deploy/.env` with freshly generated secrets. Safe to re-run — existing
configuration is never overwritten.

`scripts/setup.sh --no-venv` installs into the active environment instead, if
you manage environments yourself, and `--config-only` skips Python altogether —
that one is for a server that will only run the Docker stack, see
[deployment.md](deployment.md).

Python 3.11 or newer is required, and CI tests 3.11 through 3.13. A newer
interpreter is allowed and warned about, because a dependency without a wheel
for it fails during `pip` in a way that looks like a fault here.

On Debian and Ubuntu, `venv` is a separate package. Without it `python3 -m venv`
creates the directory and then fails, so setup checks first and tells you to
`apt install python3-venv` rather than reporting a missing `pip`.

### Linux and macOS

Both are supported, on amd64 and arm64 alike: `make setup`, `make test`,
`make dev` and every check script run on either. Windows is not supported.
A deployment still belongs on Linux — see [deployment.md](deployment.md).

Two things genuinely differ on macOS, and neither needs anything installed.
Both are version floors set by what Apple ships, and both fail *silently* on a
Linux host — see [code-standards.md](code-standards.md) §3 for the rules.

**`make` is GNU Make 3.81**, from 2006; Linux is on 4.3 or newer. Both are GNU
Make, the `Makefile` works on either, and nothing added in 4.x may be used.

**The shell is bash 3.2**, from 2007; Linux is on 5.x. Anything you add to
`scripts/` has to work there, and the one that actually bites is empty arrays:
under `set -u`, bash 3.2 treats `"${arr[@]}"` on an empty array as a fatal
unbound variable. Three `make` targets shipped broken on macOS for exactly
this, so it is one of the few places where reading the standard beats running
the tests.

The published images carry **both architectures**, so `make up ARGS=--pull`
gets a native one on Apple Silicon. This matters more than it sounds: an image
of the wrong architecture does not merely run slowly here, it hangs — the
container starts and a shell in it works, and the engine binary then blocks
forever under emulation. If you ever see `make up` come up healthy while every
tool call times out, check the architecture first.

The engine binary is published for macOS too, so `make dev` can run real tool
calls here: take `codebase-memory-mcp-darwin-arm64.tar.gz` (or `-amd64` on an
Intel Mac) from the engine's releases, unpack it and put it on `PATH`.

It also installs a pre-commit hook that refuses to commit secrets or
environment-specific configuration. Install it on its own with `make hooks`,
and audit what is already tracked with `make check-secrets`.

## Running locally

```bash
make dev                 # both services, auto-reload, in the foreground
scripts/dev.sh gateway   # just one
```

`make dev` holds the terminal, which is what you want while writing code. For
the other loop — bring it up, poke it, tear it down — there is a background
form, and it takes about two seconds:

```bash
make dev-start           # returns once /healthz answers
make smoke               # or curl, or the browser at :8080/ui
make dev-stop
make dev-logs            # follow the background log
make dev ARGS=--status   # is it up?
```

`--stop` signals the supervisor and lets its existing exit trap take the
services down with it, so there is one process to signal and nothing can be
orphaned. It also checks the command line behind the recorded PID before
signalling anything: a PID file outlives its process and numbers get reused,
and a convenience script must not kill a stranger that inherited one.

JWT verification is switched off (`DEV_INSECURE_AUTH`) and a static token is
accepted, so there is no Keycloak dependency. The script prints the token and
the LDAP groups it impersonates — it picks the first tenant's groups from your
`tenants.yaml`, so the token maps to a real squad without extra setup.

Data lives in `.dev/` and is safe to delete.

The engine binary is not bundled for local runs. Without it on `PATH`,
everything except tool execution works — and a tool call returns a clear
`engine binary not found` error rather than a 500.

## The test layers

Five layers, deliberately separated by what they need:

| Layer | Command | Needs | Covers |
| --- | --- | --- | --- |
| Unit | `make test` | nothing | authorization, configuration parsing, discovery, queue behaviour, the stdio bridge (against a fake engine) |
| Config | `make test` | nothing | the shipped example files still parse, the Compose file is valid with and without every profile |
| Interface | `make test` | Node and `gateway/webui/node_modules` | the web interface's own suite, run with vitest |
| Smoke | `make smoke` | a running stack | protocol handshake, auth rejections, live queries, metrics |
| End to end | `make e2e` | Docker | the container images, the real engine binary, git cloning, a real repository indexed and queried |

Unit tests need neither the engine nor network access, which is what keeps
them fast enough to run on every save. Anything that does need them belongs in
the smoke or end-to-end layer.

The interface layer is the one with a soft dependency. `make setup` installs no
Node, so `make test` **skips** those tests when Node or the dependencies are
missing and says what to run — `npm --prefix gateway/webui ci`, once. They used
to run in CI only, which is how a capability gate added in one session left
that job red through the whole of the next one with nobody looking: a check
that runs somewhere you do not watch is a check you do not have.

```bash
make test                              # everything
scripts/test.sh gateway                # one service
scripts/test.sh --lint                 # linting only
scripts/test.sh --fix                  # apply autofixes first
scripts/test.sh --cov                  # with coverage
scripts/test.sh gateway -- -k authorization -vv    # pass arguments to pytest
```

### The fake engine

`gateway/tests/test_cbm_bridge.py` runs a small Python script that speaks the
same line-delimited JSON-RPC as the real engine. That makes the awkward paths
testable without the binary: a call that times out mid-stream, a process that
exits unexpectedly, ten concurrent callers sharing one stdio stream, and a
missing binary.

## Debugging

```bash
make debug                  # local/dev setup
scripts/debug.sh --docker   # the Docker stack
scripts/debug.sh --tenant payments --token "$TOKEN" --gateway https://...
```

Checks the toolchain, the engine binary and its version, both configuration
files, storage (including stores sitting outside their tenant's allowlist),
container status, both services, a real MCP round trip, and the model backend.

It runs every check and reports all findings, because the useful answer is
usually the combination — "the engine is missing *and* the token is unset"
tells you more than either alone.

Common findings and what they mean:

| Finding | Cause |
| --- | --- |
| `engine binary not on PATH` | Expected with `--docker` (it lives in the image); a real problem for `scripts/dev.sh` |
| `GITHUB_TOKEN=MISSING` | Discovery will find nothing; fill in `deploy/.env` |
| `authentication failed (HTTP 401)` | Wrong token, or `DEV_INSECURE_AUTH` is off and you sent a static one |
| `authorization failed (HTTP 403)` | You belong to several squads — pass `--tenant` |
| `outside allowlist` under storage | The indexer wrote a project into the wrong tenant's cache; `list_projects` will disclose the name |

## Working with the stack

```bash
make up                        # build and start, waiting until healthy
scripts/stack.sh logs gateway  # follow one service
scripts/stack.sh shell indexer # a shell inside a container
scripts/stack.sh restart gateway
scripts/stack.sh reset         # stop and delete volumes (destroys indexes)
```

## Before opening a pull request

```bash
make fmt && make verify
```

`make verify` is tests, documentation rules and the secret scan in one gate.
All three run in CI, so a failure here is a failure there.

And `make e2e` if you touched the Dockerfile, the stdio bridge, or the
indexing path — those are exactly what unit tests do not cover.

CI additionally runs ShellCheck over `scripts/`, `helm lint` and `helm
template` over the chart, scans every tracked file for secrets, and builds
both images.

Open the pull request against **`dev`**, not `main`.

## House rules

- Python 3.11+, `ruff` for linting and formatting, 100-column lines.
- Comments explain *why*. When a constraint from the engine or a provider
  forced the shape of the code, say so — that is the comment the next reader
  needs.
- Error messages are read by operators at 3am: name what was wrong and what
  was expected.
- Authorization changes need a test for the denial path, not just the allow
  path.
