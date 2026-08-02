# Administration

Everything an administrator can change lives in the database, and there are
two ways to change it: the `repo-mcp-admin` command and the web interface's
administrative console.

They are the same operations. Both call the routes and functions in
`common/repo_mcp_common/admin.py`, so a squad created from a terminal and one
created from a browser are the same row, validated by the same rules and
recorded in the same audit table. A gap between the two is a bug;
`common/tests/test_cli_config.py` fails when one appears.

No change needs a restart. Every mutation advances a generation counter that
both services poll, so an edit reaches every replica within one poll interval
(`CONFIG_POLL_SECONDS`, five seconds by default).

## Which surface to use

| | Terminal | Console |
| --- | --- | --- |
| Reaches the database directly | yes | no, through the gateway |
| Works when the gateway is down | yes | no |
| Works when the identity provider is down | yes | yes |
| Scriptable | yes | no |
| Shows the effect of a change | after a re-read | immediately |

The terminal is the one to reach for when the platform is not yet running, or
is not running well. The console is the one for ordinary changes.

## The commands

```
repo-mcp-admin squad list
repo-mcp-admin squad set NAME --group LDAP_GROUP --project PATTERN [...]
repo-mcp-admin squad remove NAME

repo-mcp-admin role list
repo-mcp-admin role set ROLE --group LDAP_GROUP [--group ...]

repo-mcp-admin connector list
repo-mcp-admin connector set NAME --provider P --squad S [--setting k=v ...]
repo-mcp-admin connector check NAME
repo-mcp-admin connector remove NAME

repo-mcp-admin secret list
repo-mcp-admin secret set NAME [--value V] [--description D]
repo-mcp-admin secret remove NAME

repo-mcp-admin settings
repo-mcp-admin set KEY VALUE

repo-mcp-admin audit [--limit N]
repo-mcp-admin admins
repo-mcp-admin answer-cache [--purge] [--squad S] [--project P]

repo-mcp-admin status
repo-mcp-admin init | init-db | create-admin | set-password | import
repo-mcp-admin generate-key
```

`--help` on any of them lists its options. All of them read `DATABASE_URL` and
`SECRETS_KEY` from the environment, the same way the services do.

## Squads

A squad is an LDAP group set, a project allowlist and an engine tool profile.
It is the isolation boundary: which repositories a person can reach, and with
which tools.

```bash
repo-mcp-admin squad set payments \
  --group squad-payments --group squad-payments-leads \
  --project 'acme-payments-*' --project acme-ledger \
  --profile analysis
```

A group may belong to one squad only. Two squads claiming the same group would
make the boundary ambiguous, so the second one is refused:

```
error: LDAP group 'squad-payments' is already mapped to another squad
```

`--structural-only` refuses the tools that return source code, for a squad
that should see shape and not content. `--disabled` keeps the row and refuses
the requests.

## Roles

A role decides what a person may do; a squad decides which data they may do it
to. The two are independent, and the role list is fixed — the capabilities
behind each are in `gateway/app/roles.py`. What is editable is which LDAP
groups map to which role.

```bash
repo-mcp-admin role set lead --group squad-payments-leads --group squad-checkout-leads
```

`set` replaces rather than appends: the groups given are the groups the role
has afterwards. Someone holding groups from several roles gets the most
privileged one.

## Connectors

A connector is a provider, the squad its repositories belong to, and the
filters deciding which are indexed.

```bash
repo-mcp-admin secret set connector.acme-github.token --description 'GitHub token for acme'
repo-mcp-admin connector set acme-github \
  --provider github --squad payments \
  --setting org=acme \
  --token-secret connector.acme-github.token \
  --include 'acme-*' --exclude 'acme-legacy-*'
```

The token is not stored on the connector; it is a secret, referenced by name.
Provider settings differ — `org` for GitHub, `group` and `base_url` for
GitLab, `workspace` and `project_key` for Bitbucket — and the console asks for
the right ones per provider rather than offering a free-form box.

### Checking one

Four things must be right at once — the provider, the container name, a token
with the right scope, and patterns that keep something — and getting any of
them wrong looks identical afterwards: nothing is indexed. So ask:

```console
$ repo-mcp-admin connector check acme-github
acme-github: ok — 34 of 41 repositories would be indexed
  acme/payments-api
  acme/payments-web
  …
  (2 archived or empty, which are never indexed)
```

It runs real discovery against the provider — read-only, never cloning — and
names what is wrong when something is:

| What it says | What to change |
| --- | --- |
| `the token was refused` | The secret's value, or the token's scope |
| `no such organisation, or the token cannot see it` | The `org`, `group` or `workspace` setting |
| `N repositories found and the patterns keep none of them` | `--include` and `--exclude` |
| `the provider answered but holds no repositories` | The container is genuinely empty, or the token sees nothing in it |
| `github needs the 'org' setting` | A missing provider setting |

The console has the same thing as a **Check** button on the connector form,
and there it runs against what is on screen rather than what is stored — so a
wrong token is found before saving. It exits non-zero when the connector does
not work, which is what makes it usable from a deployment script.

## Secrets

Access tokens and API keys, encrypted with `SECRETS_KEY` and decrypted only in
memory, by the service that needs them.

```bash
# prompted, so it stays out of the shell history
repo-mcp-admin secret set connector.acme-github.token

# or from a pipe, for a script
printf '%s' "$TOKEN" | repo-mcp-admin secret set connector.acme-github.token
```

A stored value is never sent back — not to the console, not to `/admin/config`,
not to `secret list`. Replacing one means typing it again, which is the
correct trade for never having it on a screen.

Losing `SECRETS_KEY` makes every stored value unreadable. There is no recovery
path, by design. `repo-mcp-admin generate-key` prints a new one; keep it where
you keep your other deployment secrets.

## Settings

```bash
repo-mcp-admin settings              # every key, its value, and where it came from
repo-mcp-admin set litellm.model gpt-4o
repo-mcp-admin set indexer.concurrency 4
```

The keys are the ones in `DEFAULT_SETTINGS` in
`common/repo_mcp_common/store.py`; anything else is refused, with the known
list in the message. A value is JSON where it parses and a bare string
otherwise, so `set oidc.issuer https://sso.example.com` does what it looks
like it does.

## Administrator accounts

Local accounts, deliberately outside the directory, so a platform whose
identity provider is down can still be configured. That is the entire reason
they are acceptable, and it is why they reach configuration only — never a
graph, never source. See
[adr/0007-break-glass-administrator.md](adr/0007-break-glass-administrator.md).

```bash
repo-mcp-admin admins
repo-mcp-admin create-admin --username ada --force
repo-mcp-admin set-password ada
```

Creating an account is not offered in the console. A credential that bypasses
the directory is handed out by someone with access to the host, not through a
browser session. Changing your own password is offered, because that is the
account you already hold.

## Audit

```bash
repo-mcp-admin audit --limit 50
```

Every configuration change is recorded with who made it: the administrator's
username from the console, `cli` from a terminal, `import` from a YAML seed. A
secret's value is never in there.

This is separate from the request audit, which is one line of JSON per tool
call on stdout, refusals included. See
[architecture.md](architecture.md).

## The answer cache

```bash
repo-mcp-admin answer-cache                      # what is stored
repo-mcp-admin answer-cache --purge --squad payments
```

Reindexing already retires stale answers by epoch, so purging is for the other
case — a prompt or model change that makes previous answers undesirable rather
than out of date. See [adr/0009-answer-cache.md](adr/0009-answer-cache.md).

## First run

```bash
repo-mcp-admin generate-key            # keep the output
export SECRETS_KEY=...
repo-mcp-admin init                    # schema, and the first administrator
repo-mcp-admin import --tenants deploy/tenants.yaml --scan deploy/scan.yaml
repo-mcp-admin status
```

`init` is safe to re-run and is what the Compose stack calls on start, so a
fresh deployment reaches a usable state without anyone reading a runbook.
`import` seeds the database from the YAML documents; after that the database is
the source of truth and the files are a starting point, not a live
configuration. See
[adr/0006-configuration-in-the-database.md](adr/0006-configuration-in-the-database.md).

Whether migrations run automatically is governed by `MIGRATE_ON_START`, which
is off in production on purpose — see [environments.md](environments.md).
