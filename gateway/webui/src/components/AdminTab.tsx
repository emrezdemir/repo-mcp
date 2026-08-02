/* The administrative console.
 *
 * Upstream's third tab was "control": engine processes, log tails and a
 * filesystem browser. Those are single-machine surfaces — on a shared platform
 * they are neither safe nor meaningful — so this replaces it with the thing a
 * shared platform actually needs: squads, roles, connectors, secrets,
 * settings, the audit trail, administrator accounts and the answer cache.
 *
 * Everything here is also a `repo-mcp-admin` command, through the same
 * functions. A refusal — "LDAP group 'squad-payments' is already mapped to
 * another squad" — arrives verbatim, because it is the platform's own words.
 */

import { useCallback, useEffect, useState } from "react";
import * as admin from "../api/admin";

type Section = "squads" | "roles" | "connectors" | "secrets" | "settings" | "cache" | "audit" | "accounts";

const SECTIONS: { id: Section; label: string }[] = [
  { id: "squads", label: "Squads" },
  { id: "roles", label: "Roles" },
  { id: "connectors", label: "Connectors" },
  { id: "secrets", label: "Secrets" },
  { id: "settings", label: "Settings" },
  { id: "cache", label: "Answer cache" },
  { id: "audit", label: "Audit" },
  { id: "accounts", label: "Administrators" },
];

const ROLES = [
  ["admin", "everything, including configuration"],
  ["lead", "read, analyse, trigger indexing, write ADRs"],
  ["developer", "read the graph and the source, analyse changes"],
  ["qa", "read the graph and the source, ingest traces"],
  ["devops", "read, trigger indexing, ingest traces"],
  ["viewer", "read the graph, not the source"],
] as const;

const PROFILES = [
  ["analysis", "analysis — read-only inspection"],
  ["scout", "scout — structure only, no source"],
  ["all", "all — every tool the engine has"],
];

const PROVIDERS = ["github", "gitlab", "bitbucket"];
const MODES = ["moderate", "fast", "full", "cross-repo-intelligence"];

/* Provider settings differ, so the form asks for the right ones rather than
 * offering a key/value box. common/repo_mcp_common/providers.py reads them. */
const PROVIDER_FIELDS: Record<string, [string, string, string][]> = {
  github: [["org", "Organisation", "acme"], ["base_url", "API base URL (Enterprise only)", ""]],
  gitlab: [["group", "Group", "acme/backend"], ["base_url", "Base URL", "https://gitlab.example.com"]],
  bitbucket: [
    ["workspace", "Workspace", "acme"],
    ["project_key", "Project key", "PAY"],
    ["username", "Username", "ci-bot"],
  ],
};

const asList = (text: string) =>
  text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);

// ── small building blocks ────────────────────────────────────────────

const card = "rounded-lg border border-border/40 bg-white/[0.03] p-4";
const input =
  "w-full px-2.5 py-1.5 rounded-md bg-black/30 border border-border/40 text-[12px] outline-none focus:border-primary/50";
const primary =
  "px-3 py-1.5 rounded-md bg-primary/15 text-primary text-[12px] font-medium hover:bg-primary/25 transition-colors disabled:opacity-50";
const plain =
  "px-3 py-1.5 rounded-md bg-white/[0.06] text-[12px] hover:bg-white/[0.1] transition-colors disabled:opacity-50";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-muted-foreground/60">{hint}</span>}
    </label>
  );
}

function Table({ head, rows }: { head: string[]; rows: React.ReactNode[][] }) {
  if (!rows.length) return <p className="text-[12px] text-muted-foreground">None.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-muted-foreground">
            {head.map((h) => (
              <th key={h} className="text-left font-medium py-1.5 pr-4">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-border/20">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-4 font-mono align-top">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── sign-in ──────────────────────────────────────────────────────────

function AdminSignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      const { must_change_password } = await admin.signIn(username, password);
      setPassword("");
      onSignedIn();
      if (must_change_password) {
        setError("this administrator still has its generated password");
      }
    } catch (exception) {
      setError((exception as Error).message);
    }
  };

  return (
    <div className="p-8 max-w-sm mx-auto">
      <div className={card}>
        <h2 className="text-[14px] font-semibold mb-1">Administrator sign-in</h2>
        <p className="text-[11px] text-muted-foreground mb-4">
          A local account, separate from the directory. It reaches configuration
          only — never a graph, never source code.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Username">
            <input className={input} value={username} autoComplete="username"
                   onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="Password">
            <input className={input} type="password" value={password} autoComplete="current-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button type="submit" className={primary}>Sign in</button>
        </form>
        {error && <p className="text-[12px] text-red-400 mt-3">{error}</p>}
      </div>
    </div>
  );
}

// ── the console ──────────────────────────────────────────────────────

export function AdminTab() {
  const [config, setConfig] = useState<admin.Config | null>(null);
  const [section, setSection] = useState<Section>("squads");
  const [signedIn, setSignedIn] = useState(Boolean(admin.adminToken()));
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      setConfig(await admin.readConfig());
      setSignedIn(true);
    } catch (exception) {
      if (exception instanceof admin.AdminUnauthenticated) setSignedIn(false);
      else setError((exception as Error).message);
    }
  }, []);

  useEffect(() => {
    if (signedIn) void reload();
  }, [signedIn, reload]);

  const run = useCallback(
    async (work: () => Promise<unknown>, done: string) => {
      setError("");
      setNotice("");
      try {
        await work();
        setNotice(done);
        await reload();
      } catch (exception) {
        setError((exception as Error).message);
      }
    },
    [reload],
  );

  if (!signedIn) return <AdminSignIn onSignedIn={() => setSignedIn(true)} />;
  if (!config) return <p className="p-8 text-[12px] text-muted-foreground">Loading…</p>;

  return (
    <div className="h-full overflow-auto">
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <nav className="flex flex-wrap gap-1 border-b border-border/30 pb-3">
          {SECTIONS.map((entry) => (
            <button
              key={entry.id}
              onClick={() => { setSection(entry.id); setNotice(""); setError(""); }}
              className={`px-3 py-1 rounded-md text-[12px] transition-colors ${
                section === entry.id
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]"
              }`}
            >
              {entry.label}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-muted-foreground/60 self-center">
            generation {config.generation}
          </span>
        </nav>

        {notice && <p className="text-[12px] text-primary">{notice}</p>}
        {error && <p className="text-[12px] text-red-400">{error}</p>}

        {section === "squads" && <Squads config={config} run={run} />}
        {section === "roles" && <Roles config={config} run={run} />}
        {section === "connectors" && <Connectors config={config} run={run} />}
        {section === "secrets" && <Secrets config={config} run={run} />}
        {section === "settings" && <Settings config={config} run={run} />}
        {section === "cache" && <Cache run={run} />}
        {section === "audit" && <Audit />}
        {section === "accounts" && <Accounts config={config} run={run} />}
      </div>
    </div>
  );
}

type Run = (work: () => Promise<unknown>, done: string) => Promise<void>;

// ── squads ───────────────────────────────────────────────────────────

function Squads({ config, run }: { config: admin.Config; run: Run }) {
  const [editing, setEditing] = useState<admin.Squad | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground mb-3">Squads</h3>
        <Table
          head={["Name", "Profile", "Enabled", "LDAP groups", "Projects", ""]}
          rows={config.tenants.map((squad) => [
            squad.name,
            squad.tool_profile,
            squad.enabled ? "yes" : "no",
            squad.ldap_groups.join(", "),
            squad.projects.join(", "),
            <span className="space-x-2 whitespace-nowrap">
              <button className="text-primary hover:underline"
                      onClick={() => { setEditing(squad); setCreating(false); }}>edit</button>
              <button className="text-red-400 hover:underline"
                      onClick={() => {
                        if (!confirm(`Delete the squad ${squad.name}? Its members lose access at once.`)) return;
                        void run(() => admin.deleteSquad(squad.name), `squad ${squad.name} deleted`);
                      }}>delete</button>
            </span>,
          ])}
        />
        {config.tenants.length === 0 && (
          <p className="text-[11px] text-muted-foreground/70 mt-2">
            Until one exists every request is refused for want of a squad.
          </p>
        )}
      </div>

      {!creating && !editing && (
        <button className={plain} onClick={() => setCreating(true)}>Add a squad</button>
      )}
      {(creating || editing) && (
        <SquadEditor
          squad={editing}
          run={run}
          onDone={() => { setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function SquadEditor({ squad, run, onDone }: { squad: admin.Squad | null; run: Run; onDone: () => void }) {
  const [name, setName] = useState(squad?.name ?? "");
  const [groups, setGroups] = useState((squad?.ldap_groups ?? []).join(", "));
  const [projects, setProjects] = useState((squad?.projects ?? []).join(", "));
  const [profile, setProfile] = useState(squad?.tool_profile ?? "analysis");
  const [structural, setStructural] = useState(Boolean(squad?.structural_only));
  const [enabled, setEnabled] = useState(squad ? squad.enabled : true);

  const save = () =>
    run(async () => {
      const target = (squad?.name ?? name).trim();
      if (!target) throw new Error("a squad needs a name");
      await admin.putSquad(target, {
        ldap_groups: asList(groups),
        projects: asList(projects),
        tool_profile: profile,
        structural_only: structural,
        enabled,
      });
      onDone();
    }, `squad ${squad?.name ?? name} saved`);

  return (
    <div className={`${card} space-y-3 max-w-xl`}>
      <Field label="Name">
        <input className={input} value={name} disabled={Boolean(squad)} placeholder="payments"
               onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="LDAP groups" hint="Comma separated. A group may belong to one squad only.">
        <input className={input} value={groups} placeholder="squad-payments, squad-payments-leads"
               onChange={(e) => setGroups(e.target.value)} />
      </Field>
      <Field label="Projects" hint="Names or globs. Anything outside this list is refused.">
        <input className={input} value={projects} placeholder="acme-payments-*, acme-ledger"
               onChange={(e) => setProjects(e.target.value)} />
      </Field>
      <Field label="Tool profile">
        <select className={input} value={profile} onChange={(e) => setProfile(e.target.value)}>
          {PROFILES.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
        </select>
      </Field>
      <label className="flex items-center gap-2 text-[12px]">
        <input type="checkbox" checked={structural} onChange={(e) => setStructural(e.target.checked)} />
        Structure only — refuse the tools that return source
      </label>
      <label className="flex items-center gap-2 text-[12px]">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enabled
      </label>
      <div className="flex gap-2">
        <button className={primary} onClick={save}>{squad ? "Save" : "Create"}</button>
        <button className={plain} onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

// ── roles ────────────────────────────────────────────────────────────

function Roles({ config, run }: { config: admin.Config; run: Run }) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        A role decides what a person may do; a squad decides which data they may do it to.
        Someone holding groups from several roles gets the most privileged one.
      </p>
      {ROLES.map(([role, what]) => (
        <RoleEditor key={role} role={role} what={what} groups={config.roles?.[role] ?? []} run={run} />
      ))}
    </div>
  );
}

function RoleEditor({ role, what, groups, run }: { role: string; what: string; groups: string[]; run: Run }) {
  const [value, setValue] = useState(groups.join(", "));
  useEffect(() => setValue(groups.join(", ")), [groups]);

  return (
    <div className={`${card} flex items-end gap-3`}>
      <div className="flex-1">
        <Field label={`${role} — ${what}`} hint="Comma separated. Saving an empty box removes the role.">
          <input className={input} value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
      </div>
      <button className={plain} onClick={() => run(() => admin.putRole(role, asList(value)), `role ${role} saved`)}>
        Save
      </button>
    </div>
  );
}

// ── connectors ───────────────────────────────────────────────────────

function Connectors({ config, run }: { config: admin.Config; run: Run }) {
  const [editing, setEditing] = useState<admin.Connector | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground mb-3">Connectors</h3>
        <Table
          head={["Name", "Provider", "Squad", "Mode", "Enabled", "Token secret", ""]}
          rows={config.connectors.map((connector) => [
            connector.name, connector.provider, connector.tenant, connector.mode,
            connector.enabled ? "yes" : "no", connector.token_secret ?? "—",
            <span className="space-x-2 whitespace-nowrap">
              <button className="text-primary hover:underline"
                      onClick={() => { setEditing(connector); setCreating(false); }}>edit</button>
              <button className="text-red-400 hover:underline"
                      onClick={() => {
                        if (!confirm(`Delete the connector ${connector.name}? Indexed graphs are kept.`)) return;
                        void run(() => admin.deleteConnector(connector.name), `connector ${connector.name} deleted`);
                      }}>delete</button>
            </span>,
          ])}
        />
        <p className="text-[11px] text-muted-foreground/70 mt-2">
          {config.connectors.length === 0
            ? "Nothing is discovered or indexed until one exists."
            : "Open one and press Check to ask the provider what it can currently see."}
        </p>
      </div>

      {!creating && !editing && (
        <button className={plain} onClick={() => setCreating(true)}>Add a connector</button>
      )}
      {(creating || editing) && (
        <ConnectorEditor connector={editing} config={config} run={run}
                         onDone={() => { setCreating(false); setEditing(null); }} />
      )}
    </div>
  );
}

function ConnectorEditor({
  connector, config, run, onDone,
}: { connector: admin.Connector | null; config: admin.Config; run: Run; onDone: () => void }) {
  const [name, setName] = useState(connector?.name ?? "");
  const [provider, setProvider] = useState(connector?.provider ?? "github");
  const [squad, setSquad] = useState(connector?.tenant ?? config.tenants[0]?.name ?? "");
  const [token, setToken] = useState(connector?.token_secret ?? "");
  const [include, setInclude] = useState((connector?.include ?? ["*"]).join(", "));
  const [exclude, setExclude] = useState((connector?.exclude ?? []).join(", "));
  const [mode, setMode] = useState(connector?.mode ?? "moderate");
  const [persistence, setPersistence] = useState(connector ? connector.persistence !== false : true);
  const [enabled, setEnabled] = useState(connector ? connector.enabled : true);
  const [fields, setFields] = useState<Record<string, string>>(connector?.settings ?? {});

  /* A new token normally means leaving this form, storing a secret on another
   * tab and coming back — losing everything typed so far. The token can be
   * stored from here instead. */
  const [newSecret, setNewSecret] = useState(false);
  const [secretValue, setSecretValue] = useState("");

  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<admin.ConnectorCheck | null>(null);
  const [checkError, setCheckError] = useState("");

  const providerSettings = () => {
    const settings: Record<string, string> = {};
    for (const [key] of PROVIDER_FIELDS[provider] ?? []) {
      if (fields[key]?.trim()) settings[key] = fields[key].trim();
    }
    return settings;
  };

  /* Storing the secret is a real write, so it happens before the check that
   * needs it and before the save that references it — not twice. */
  const storeSecretIfNew = async () => {
    if (!newSecret) return;
    if (!token.trim()) throw new Error("the new secret needs a name");
    if (!secretValue) throw new Error("the new secret needs a value");
    await admin.putSecret(token.trim(), secretValue, `token for the ${name || "new"} connector`);
    setNewSecret(false);
    setSecretValue("");
  };

  const check = async () => {
    setChecking(true);
    setCheckError("");
    setResult(null);
    try {
      await storeSecretIfNew();
      setResult(
        await admin.checkConnector({
          provider,
          settings: providerSettings(),
          token_secret: token.trim() || null,
          include: asList(include),
          exclude: asList(exclude),
        }),
      );
    } catch (exception) {
      setCheckError((exception as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const save = () =>
    run(async () => {
      const target = (connector?.name ?? name).trim();
      if (!target) throw new Error("a connector needs a name");
      await storeSecretIfNew();
      await admin.putConnector(target, {
        provider, tenant: squad, settings: providerSettings(),
        token_secret: token.trim() || null,
        include: asList(include), exclude: asList(exclude),
        mode, persistence, enabled,
      });
      onDone();
    }, `connector ${connector?.name ?? name} saved`);

  return (
    <div className={`${card} space-y-3 max-w-xl`}>
      <Field label="Name">
        <input className={input} value={name} disabled={Boolean(connector)} placeholder="acme-github"
               onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Provider">
        <select className={input} value={provider} onChange={(e) => setProvider(e.target.value)}>
          {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </Field>
      {(PROVIDER_FIELDS[provider] ?? []).map(([key, label, placeholder]) => (
        <Field key={key} label={label}>
          <input className={input} placeholder={placeholder} value={fields[key] ?? ""}
                 onChange={(e) => setFields({ ...fields, [key]: e.target.value })} />
        </Field>
      ))}
      <Field label="Squad" hint="Where discovered repositories are indexed. Create the squad first.">
        <select className={input} value={squad} onChange={(e) => setSquad(e.target.value)}>
          {config.tenants.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
        </select>
      </Field>
      <Field label="Token secret" hint="Encrypted at rest; the value is never sent back.">
        {newSecret ? (
          <div className="space-y-1.5">
            <input className={input} value={token} placeholder="connector.acme-github.token"
                   onChange={(e) => setToken(e.target.value)} />
            <input className={input} type="password" autoComplete="off" value={secretValue}
                   placeholder="paste the token" onChange={(e) => setSecretValue(e.target.value)} />
            <button className="text-[11px] text-muted-foreground hover:text-foreground"
                    onClick={() => { setNewSecret(false); setToken(connector?.token_secret ?? ""); setSecretValue(""); }}>
              use a stored secret instead
            </button>
          </div>
        ) : (
          <div className="space-y-1.5">
            <select className={input} value={token} onChange={(e) => setToken(e.target.value)}>
              <option value="">(none)</option>
              {config.secrets.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </select>
            <button className="text-[11px] text-primary hover:underline"
                    onClick={() => { setNewSecret(true); setToken(""); }}>
              store a new token here
            </button>
          </div>
        )}
      </Field>
      <Field label="Include"><input className={input} value={include} onChange={(e) => setInclude(e.target.value)} /></Field>
      <Field label="Exclude"><input className={input} value={exclude} placeholder="legacy-*"
                                    onChange={(e) => setExclude(e.target.value)} /></Field>
      <Field label="Index mode">
        <select className={input} value={mode} onChange={(e) => setMode(e.target.value)}>
          {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </Field>
      <label className="flex items-center gap-2 text-[12px]">
        <input type="checkbox" checked={persistence} onChange={(e) => setPersistence(e.target.checked)} />
        Write a shareable graph artifact
      </label>
      <label className="flex items-center gap-2 text-[12px]">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enabled
      </label>
      <div className="flex gap-2">
        <button className={primary} onClick={save}>{connector ? "Save" : "Create"}</button>
        <button className={plain} disabled={checking} onClick={() => void check()}>
          {checking ? "Checking…" : "Check"}
        </button>
        <button className={plain} onClick={onDone}>Cancel</button>
      </div>

      {checkError && <p className="text-[12px] text-red-400">{checkError}</p>}
      {result && <CheckReport result={result} />}
    </div>
  );
}

/* What the provider answered.
 *
 * The counts matter more than the names: "34 of 41" says the patterns are
 * doing something, and a zero says which of the four things to change. The
 * names are there because a valid token pointed at the wrong organisation
 * returns a perfectly healthy-looking count of the wrong repositories. */
function CheckReport({ result }: { result: admin.ConnectorCheck }) {
  return (
    <div className={`${card} space-y-2`}>
      <p className={`text-[12px] ${result.ok ? "text-primary" : "text-red-400"}`}>
        {result.ok
          ? `${result.matched} of ${result.discovered}${result.truncated ? "+" : ""} repositories would be indexed`
          : result.reason}
      </p>
      {result.sample.length > 0 && (
        <ul className="text-[11px] font-mono text-muted-foreground space-y-0.5">
          {result.sample.map((name) => <li key={name}>{name}</li>)}
          {result.matched > result.sample.length && (
            <li className="text-muted-foreground/60">
              and {result.matched - result.sample.length} more
            </li>
          )}
        </ul>
      )}
      {result.excluded.length > 0 && (
        <p className="text-[11px] text-muted-foreground/60">
          Excluded by the patterns: {result.excluded.join(", ")}
        </p>
      )}
      {result.skipped > 0 && (
        <p className="text-[11px] text-muted-foreground/60">
          {result.skipped} archived or empty, which are never indexed.
        </p>
      )}
      {result.truncated && (
        <p className="text-[11px] text-muted-foreground/60">
          Stopped after the first {result.discovered}; the real total is higher.
        </p>
      )}
    </div>
  );
}

// ── secrets ──────────────────────────────────────────────────────────

function Secrets({ config, run }: { config: admin.Config; run: Run }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground mb-3">Secrets</h3>
        <Table
          head={["Name", "Description", ""]}
          rows={config.secrets.map((secret) => [
            secret.name, secret.description ?? "",
            <button className="text-red-400 hover:underline"
                    onClick={() => {
                      if (!confirm(`Delete the secret ${secret.name}? Anything referencing it stops working.`)) return;
                      void run(() => admin.deleteSecret(secret.name), `secret ${secret.name} deleted`);
                    }}>delete</button>,
          ])}
        />
      </div>

      <div className={`${card} space-y-3 max-w-xl`}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground">Store a secret</h3>
        <Field label="Name" hint="Referenced by this name from a connector or a squad.">
          <input className={input} value={name} placeholder="connector.acme-github.token"
                 onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Value">
          <input className={input} type="password" autoComplete="off" value={value}
                 onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Field label="Description">
          <input className={input} value={description} placeholder="GitHub token for the acme org"
                 onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <button className={primary}
                onClick={() => run(async () => {
                  if (!name.trim()) throw new Error("a secret needs a name");
                  if (!value) throw new Error("a secret needs a value");
                  await admin.putSecret(name.trim(), value, description);
                  setName(""); setValue(""); setDescription("");
                }, `secret ${name} stored`)}>
          Store
        </button>
      </div>

      <p className="text-[11px] text-muted-foreground/70 max-w-xl">
        Values are encrypted with SECRETS_KEY and decrypted only in memory, by the
        service that needs them. A stored value is never sent back, which is why
        replacing one means typing it again. Losing that key makes every stored
        value unreadable; there is no recovery path, by design.
      </p>
    </div>
  );
}

// ── settings ─────────────────────────────────────────────────────────

const SETTING_GROUPS: [string, string][] = [
  ["Identity", "oidc."],
  ["Model access", "litellm."],
  ["Smart tools", "smart_tools."],
  ["Engine", "engine."],
  ["Indexer", "indexer."],
  ["Answer cache", "answer_cache."],
  ["Prompt compression", "headroom."],
];

function Settings({ config, run }: { config: admin.Config; run: Run }) {
  const entries = Object.entries(config.settings).sort(([a], [b]) => a.localeCompare(b));
  const shown = new Set<string>();
  const groups = SETTING_GROUPS.map(([title, prefix]) => {
    const mine = entries.filter(([key]) => key.startsWith(prefix));
    mine.forEach(([key]) => shown.add(key));
    return [title, mine] as const;
  }).filter(([, mine]) => mine.length);
  const rest = entries.filter(([key]) => !shown.has(key));

  return (
    <div className="space-y-4">
      {[...groups, ...(rest.length ? [["Other", rest] as const] : [])].map(([title, mine]) => (
        <div key={title} className={card}>
          <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground mb-3">{title}</h3>
          <div className="space-y-2">
            {mine.map(([key, value]) => <SettingRow key={key} name={key} value={value} run={run} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function SettingRow({ name, value, run }: { name: string; value: unknown; run: Run }) {
  const [draft, setDraft] = useState(
    typeof value === "object" ? JSON.stringify(value) : String(value),
  );
  const boolean = typeof value === "boolean";
  const numeric = typeof value === "number";

  const read = (): unknown => {
    if (boolean) return draft === "true";
    if (numeric) return Number(draft);
    try {
      return JSON.parse(draft);
    } catch {
      // A hostname is not JSON and nobody types quotes around one.
      return draft;
    }
  };

  return (
    <div className="flex items-center gap-3">
      <span className="font-mono text-[11px] text-muted-foreground w-72 shrink-0">{name}</span>
      {boolean ? (
        <select className={input} value={draft} onChange={(e) => setDraft(e.target.value)}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input className={input} type={numeric ? "number" : "text"} value={draft}
               onChange={(e) => setDraft(e.target.value)} />
      )}
      <button className={plain} onClick={() => run(() => admin.putSetting(name, read()), `${name} saved`)}>
        Save
      </button>
    </div>
  );
}

// ── answer cache ─────────────────────────────────────────────────────

function Cache({ run }: { run: Run }) {
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof admin.readAnswerCache>> | null>(null);
  const [squad, setSquad] = useState("");
  const [project, setProject] = useState("");

  useEffect(() => { admin.readAnswerCache().then(setSummary).catch(() => setSummary(null)); }, []);
  if (!summary) return <p className="text-[12px] text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className={`${card} flex gap-8`}>
        {[["Entries", summary.entries], ["Hits", summary.hits], ["Squads", summary.squads.length]].map(
          ([label, n]) => (
            <div key={String(label)}>
              <div className="text-[20px] font-semibold">{n as number}</div>
              <div className="text-[11px] text-muted-foreground">{label as string}</div>
            </div>
          ),
        )}
      </div>

      {!summary.enabled && (
        <p className="text-[11px] text-muted-foreground max-w-xl">
          The cache is off. Turn it on under Settings — answer_cache.enabled — and set
          an embedding model there. It stores synthesised knowledge of a squad's
          source, which is a decision to make rather than inherit.
        </p>
      )}

      <div className={`${card} space-y-3 max-w-xl`}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground">Purge</h3>
        <p className="text-[11px] text-muted-foreground">
          Reindexing already retires stale answers by epoch. This is for the other
          case — a prompt or model change that makes previous answers undesirable
          rather than out of date.
        </p>
        <Field label="Squad"><input className={input} value={squad} placeholder="blank for every squad"
                                    onChange={(e) => setSquad(e.target.value)} /></Field>
        <Field label="Project"><input className={input} value={project} placeholder="blank for every project"
                                      onChange={(e) => setProject(e.target.value)} /></Field>
        <button className={plain}
                onClick={() => {
                  const where = [squad, project].filter(Boolean).join(" / ") || "every squad";
                  if (!confirm(`Drop the cached answers for ${where}?`)) return;
                  void run(async () => {
                    const result = await admin.purgeAnswerCache(squad, project);
                    setSummary(await admin.readAnswerCache());
                    return result;
                  }, "cached answers removed");
                }}>
          Purge
        </button>
      </div>
    </div>
  );
}

// ── audit ────────────────────────────────────────────────────────────

function Audit() {
  const [limit, setLimit] = useState(100);
  const [entries, setEntries] = useState<{ at: string; actor: string; action: string; target?: string }[]>([]);

  useEffect(() => {
    admin.readAudit(limit).then((data) => setEntries(data.entries ?? [])).catch(() => setEntries([]));
  }, [limit]);

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        Every configuration change, whoever made it: an administrator's username from
        here, "cli" from a terminal, "import" from a YAML seed. A secret's value is
        never in here.
      </p>
      <select className={`${input} w-40`} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
        {[25, 100, 250, 500].map((n) => <option key={n} value={n}>{n} entries</option>)}
      </select>
      <div className={card}>
        <Table head={["When", "Who", "What", "Target"]}
               rows={entries.map((e) => [e.at, e.actor, e.action, e.target ?? ""])} />
      </div>
    </div>
  );
}

// ── administrator accounts ───────────────────────────────────────────

function Accounts({ config, run }: { config: admin.Config; run: Run }) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground mb-3">Accounts</h3>
        <Table head={["Username", "Active", "Last sign-in"]}
               rows={(config.admins ?? []).map((a) => [
                 a.username, a.is_active ? "yes" : "no", a.last_login_at ?? "never",
               ])} />
      </div>

      <div className={`${card} space-y-3 max-w-md`}>
        <h3 className="text-[12px] uppercase tracking-wide text-muted-foreground">Change my password</h3>
        <Field label="New password" hint="At least twelve characters.">
          <input className={input} type="password" autoComplete="new-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Repeat">
          <input className={input} type="password" autoComplete="new-password" value={repeat}
                 onChange={(e) => setRepeat(e.target.value)} />
        </Field>
        <button className={primary}
                onClick={() => run(async () => {
                  if (password !== repeat) throw new Error("the two passwords do not match");
                  await admin.changePassword(password);
                  setPassword(""); setRepeat("");
                }, "password changed")}>
          Change
        </button>
      </div>

      <p className="text-[11px] text-muted-foreground/70 max-w-xl">
        Adding or removing an account is a terminal operation: repo-mcp-admin
        create-admin --username &lt;name&gt; --force, and repo-mcp-admin set-password
        &lt;name&gt;. A credential that bypasses the directory is handed out by someone
        with access to the host, not through a browser.
      </p>
    </div>
  );
}
