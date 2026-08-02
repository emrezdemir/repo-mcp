import { useCan } from "../hooks/useCan";
import { useDismiss } from "../hooks/useDismiss";
import { callTool } from "../api/rpc";
import {
  projectHealth,
  readAdr,
  writeAdr,
  deleteProject as removeProject,
} from "../api/platform";
import { useMemo, useState, useCallback, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useProjects } from "../hooks/useProjects";
import { colorForLabel } from "../lib/colors";
import { useUiMessages } from "../lib/i18n";

interface StatsTabProps {
  onSelectProject: (project: string) => void;
}

/* ── Glowy health dot ───────────────────────────────────── */

function HealthDot({ name }: { name: string }) {
  const t = useUiMessages();
  const [status, setStatus] = useState<"loading" | "healthy" | "corrupt" | "missing">("loading");
  const [info, setInfo] = useState("");

  useEffect(() => {
    projectHealth(name)
      .then((d) => {
        setStatus(d.status ?? "corrupt");
        if (d.nodes !== undefined) {
          setInfo(`${d.nodes.toLocaleString()} nodes, ${(d.edges ?? 0).toLocaleString()} edges`);
        } else if (d.reason) {
          setInfo(d.reason);
        }
      })
      .catch(() => setStatus("corrupt"));
  }, [name]);

  const dotColor =
    status === "healthy" ? "#34d399" :
    status === "missing" ? "#fbbf24" :
    status === "corrupt" ? "#f87171" : "#555";

  const label =
    status === "healthy" ? t.projects.healthHealthy :
    status === "missing" ? t.projects.healthMissing :
    status === "corrupt" ? t.projects.healthCorrupt : t.projects.healthChecking;

  return (
    <div className="group relative inline-flex items-center">
      {/* Glow layer */}
      <span
        className="absolute w-3 h-3 rounded-full animate-pulse opacity-40 blur-[3px]"
        style={{ backgroundColor: dotColor }}
      />
      {/* Dot */}
      <span
        className="relative w-[8px] h-[8px] rounded-full"
        style={{ backgroundColor: dotColor, boxShadow: `0 0 6px ${dotColor}80` }}
      />
      {/* Tooltip */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-3 hidden group-hover:block z-20 pointer-events-none">
        <div className="bg-[#0b1920] border border-border/50 rounded-lg px-3 py-2 text-[11px] whitespace-nowrap shadow-xl">
          <p className="font-medium" style={{ color: dotColor }}>{label}</p>
          {info && <p className="text-foreground/35 text-[10px] mt-0.5">{info}</p>}
        </div>
      </div>
    </div>
  );
}

/* ── ADR button + modal ─────────────────────────────────── */

function AdrButton({ project }: { project: string }) {
  const t = useUiMessages();
  const [hasAdr, setHasAdr] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  // What the platform will let this caller do. Offering a control that is
  // certain to be refused is not helpful; the refusal below is what enforces
  // it either way.
  const mayManage = useCan("manage_adr");

  const fetchAdr = useCallback(async () => {
    try {
      const data = await readAdr(project);
      setHasAdr(data.has_adr ?? false);
      setError(null);
      if (data.content) setContent(data.content);
      if (data.updated_at) setUpdatedAt(data.updated_at);
    } catch (exception) {
      // The platform's own words: "'manage_adr' is not available in this
      // session (role: lead, squad: payments)" says what to do about it, and
      // an empty editor does not.
      setHasAdr(false);
      setError((exception as Error).message);
    }
  }, [project]);

  useEffect(() => {
    // Without the capability there is nothing to read, but the control still
    // renders — disabled, with the reason on it. A button that vanishes
    // leaves an administrator debugging permissions with nothing to go on.
    if (mayManage) void fetchAdr();
    else setHasAdr(false);
  }, [fetchAdr, mayManage]);
  useDismiss(open, () => setOpen(false));

  const save = async (nextContent = content) => {
    setSaving(true);
    try {
      await writeAdr(project, nextContent);
      await fetchAdr();
      setOpen(false);
    } catch (exception) {
      // A save that silently does nothing is worse than one that fails.
      setError((exception as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (hasAdr === null) return null;

  return (
    <>
      <button
        onClick={() => { setOpen(true); fetchAdr(); }}
        disabled={!mayManage}
        title={mayManage ? undefined
          : "This squad's tool profile does not include manage_adr"}
        className={`px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all ${
          hasAdr
            ? "bg-accent/15 text-accent hover:bg-accent/25"
            : "bg-white/[0.03] text-foreground/25 hover:text-foreground/40 hover:bg-white/[0.06]"
        } disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-white/[0.03]`}
      >
        {hasAdr ? "ADR" : "+ ADR"}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
             role="dialog" aria-modal="true" aria-label={t.adr.title}
             onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <div className="relative bg-[#0e2028] border border-border/40 rounded-2xl p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-[15px] font-semibold text-foreground/90">{t.adr.title}</h3>
                <p className="text-[11px] text-foreground/30 font-mono mt-0.5">{project}</p>
              </div>
              <button onClick={() => setOpen(false)} className="text-foreground/20 hover:text-foreground/50 text-[16px] p-1">×</button>
            </div>
            {updatedAt && (
              <p className="text-[10px] text-foreground/20 mb-3">{t.adr.lastUpdated}: {updatedAt}</p>
            )}
            {error && (
              <p role="alert" className="text-[11px] text-red-400/90 bg-red-500/10 border border-red-500/20
                                         rounded-lg px-3 py-2 mb-3">
                {error}
              </p>
            )}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={"# Architecture Decision Record\n\n## Context\n...\n\n## Decision\n...\n\n## Consequences\n..."}
              className="flex-1 min-h-[300px] bg-white/[0.03] border border-white/[0.06] rounded-xl px-4 py-3 text-[12px] text-foreground font-mono placeholder-foreground/15 outline-none focus:border-primary/30 resize-none leading-relaxed"
            />
            <div className="flex justify-end gap-2 mt-4">
              {hasAdr && (
                <button
                  onClick={async () => {
                    setContent(""); await save("");
                  }}
                  className="px-3 py-2 rounded-lg text-[12px] text-destructive/60 hover:text-destructive hover:bg-destructive/10 font-medium transition-all"
                >
                  {t.common.delete}
                </button>
              )}
              <button onClick={() => setOpen(false)} className="px-4 py-2 rounded-lg text-[12px] text-foreground/40 hover:bg-white/[0.04] font-medium transition-all">{t.common.cancel}</button>
              <button onClick={() => save()} disabled={saving} className="px-4 py-2 rounded-lg bg-primary/20 hover:bg-primary/30 text-primary text-[12px] font-medium transition-all disabled:opacity-30">
                {saving ? t.common.saving : t.common.save}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/* ── Adding a project ───────────────────────────────────── */

/* Upstream this was a filesystem browser: pick a directory, index it. On a
 * shared platform there is no directory a person should be choosing by hand —
 * a repository is discovered by a connector and cloned by the indexer under
 * the squad's own root, and the gateway refuses any path outside it. So this
 * says where projects come from instead of offering a picker that would be
 * refused. See docs/adr/0002-tenancy-model.md. */

function CreateIndexModal({ onClose }: { onClose: () => void; onCreated: () => void }) {
  useDismiss(true, onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
         role="dialog" aria-modal="true" aria-label="Where projects come from"
         onClick={onClose}>
      <div className="w-full max-w-md rounded-lg border border-border/40 bg-[#0b1920] p-5"
           onClick={(event) => event.stopPropagation()}>
        <h3 className="text-[14px] font-semibold mb-2">Where projects come from</h3>
        <p className="text-[12px] text-muted-foreground leading-relaxed">
          Repositories are discovered by a connector — a GitHub organisation, a
          GitLab group or a Bitbucket workspace — and indexed by the indexer under
          this squad's own root. Adding a repository to that organisation is enough
          for it to appear on the next scan; no configuration change is needed.
        </p>
        <p className="text-[12px] text-muted-foreground leading-relaxed mt-3">
          Connectors are configured under <span className="text-primary">Admin →
          Connectors</span>, or with{" "}
          <span className="font-mono text-[11px]">repo-mcp-admin connector set</span>.
        </p>
        <button onClick={onClose}
                className="mt-4 px-3 py-1.5 rounded-md bg-white/[0.06] text-[12px] hover:bg-white/[0.1]">
          Close
        </button>
      </div>
    </div>
  );
}


/* ── Index Progress ─────────────────────────────────────── */

export function IndexProgress({ onDone }: { onDone: () => void }) {
  const t = useUiMessages();
  const [jobs, setJobs] = useState<{ slot: number; status: string; path: string; error?: string }[]>([]);
  const [hasActive, setHasActive] = useState(true);
  useEffect(() => {
    if (!hasActive) return;
    const poll = setInterval(async () => {
      try {
        // index_status is the engine's own tool, so this poll is authorized
        // like every other call. It answers per project rather than per
        // worker slot, which is the shape a shared platform has anyway.
        const status = await callTool<Record<string, unknown>>("index_status", {});
        const data = (Array.isArray(status) ? status : (status.jobs ?? [])) as {
          slot: number; status: string; path: string; error?: string;
        }[];
        setJobs(data);
        const stillIndexing = data.some((j) => j.status === "indexing");
        /* Empty list = job not visible: the backend keeps finished jobs listed
           as "done"/"error", so [] mid-index only happens on transient state
           loss (e.g. server restart) — keep polling, don't treat as done. */
        if (data.length > 0 && !stillIndexing) {
          setHasActive(false);
          const hasErrors = data.some((j) => j.status === "error");
          if (!hasErrors) {
            onDone();
          }
        }
      } catch (error) {
        console.error("[IndexProgress] Poll failed:", error);
      }
    }, 2000);
    return () => clearInterval(poll);
  }, [onDone, hasActive]);

  const active = jobs.filter((j) => j.status === "indexing");
  const errors = jobs.filter((j) => j.status === "error");

  if (active.length === 0 && errors.length === 0) return null;

  return (
    <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 mb-6">
      {active.map((j) => (
        <div key={j.slot} className="flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin shrink-0" />
          <div>
            <p className="text-[12px] text-primary font-medium">{t.projects.indexingInProgress}</p>
            <p className="text-[11px] text-foreground/30 font-mono">{j.path}</p>
          </div>
        </div>
      ))}
      {errors.map((j) => (
        <div key={j.slot} className="flex items-start gap-3 mt-3 first:mt-0 p-3 rounded-lg border border-destructive/20 bg-destructive/5 text-destructive">
          <span className="text-[14px]">⚠️</span>
          <div className="flex-1 min-w-0">
            <p className="text-[12px] font-semibold">{t.projects.indexingFailed}</p>
            <p className="text-[11px] font-mono truncate">{j.path}</p>
            {j.error && <p className="text-[10px] opacity-75 mt-1 font-mono">{j.error}</p>}
          </div>
        </div>
      ))}
      {errors.length > 0 && (
        <div className="flex justify-end mt-3">
          <button
            onClick={onDone}
            className="px-3 py-1 rounded bg-destructive/10 hover:bg-destructive/20 text-destructive text-[11px] font-medium transition-all"
          >
            {t.common.dismiss}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Main Stats Tab ─────────────────────────────────────── */

export function StatsTab({ onSelectProject }: StatsTabProps) {
  const t = useUiMessages();
  const { projects, loading, error, refresh } = useProjects();
  const [showModal, setShowModal] = useState(false);
  const [indexing, setIndexing] = useState(false);
  /* Whatever the platform said last, in its own words. */
  const [notice, setNotice] = useState<string | null>(null);

  const aggregate = useMemo(() => {
    let totalNodes = 0, totalEdges = 0;
    for (const p of projects) {
      totalNodes += p.schema?.node_labels?.reduce((s, l) => s + l.count, 0) ?? 0;
      totalEdges += p.schema?.edge_types?.reduce((s, t) => s + t.count, 0) ?? 0;
    }
    return { projects: projects.length, nodes: totalNodes, edges: totalEdges };
  }, [projects]);

  const deleteProject = useCallback(async (name: string) => {
    if (!confirm(t.projects.deleteConfirm(name))) return;
    try {
      await removeProject(name);
      setNotice(null);
      refresh();
    } catch (exception) {
      // Deleting a graph is not a thing to fail quietly at.
      setNotice((exception as Error).message);
    }
  }, [refresh, t.projects]);

  return (
    <ScrollArea className="h-full">
      <div className="p-8 max-w-3xl mx-auto">
        {projects.length > 0 && (
          <div className="flex gap-4 mb-8">
            {[
              { label: t.tabs.projects, value: aggregate.projects, color: "text-primary" },
              { label: t.projects.nodes, value: aggregate.nodes, color: "text-foreground/80" },
              { label: t.projects.edges, value: aggregate.edges, color: "text-foreground/80" },
            ].map((s) => (
              <div key={s.label} className="flex-1 rounded-xl border border-border/30 bg-white/[0.02] p-4">
                <p className="text-[10px] text-foreground/25 uppercase tracking-widest mb-1">{s.label}</p>
                <p className={`text-[22px] font-semibold tabular-nums ${s.color}`}>{s.value.toLocaleString()}</p>
              </div>
            ))}
          </div>
        )}

        {notice && (
          <div role="alert"
               className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 mb-6 flex items-start gap-3">
            <p className="text-destructive text-[12px] flex-1">{notice}</p>
            <button onClick={() => setNotice(null)}
                    className="text-destructive/50 hover:text-destructive text-[14px] leading-none">×</button>
          </div>
        )}

        {indexing && <IndexProgress onDone={() => { setIndexing(false); refresh(); }} />}

        <div className="flex items-center justify-between mb-6">
          <h2 className="text-[15px] font-semibold text-foreground/80">{t.projects.indexedProjects}</h2>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowModal(true)} className="px-3 py-1.5 rounded-lg bg-primary/15 hover:bg-primary/25 text-primary text-[12px] font-medium transition-all">+ {t.index.newIndex}</button>
            <button onClick={refresh} disabled={loading} className="px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.07] text-[12px] text-foreground/40 font-medium transition-all disabled:opacity-30">{loading ? "..." : t.common.refresh}</button>
          </div>
        </div>

        {error && <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 mb-6"><p className="text-destructive text-[13px]">{error}</p></div>}

        {!loading && projects.length === 0 && !error && (
          <div className="text-center py-20">
            <p className="text-foreground/25 text-[13px] mb-2">{t.projects.noIndexedProjects}</p>
            <button onClick={() => setShowModal(true)} className="px-4 py-2 rounded-lg bg-primary/15 hover:bg-primary/25 text-primary text-[12px] font-medium transition-all">{t.projects.indexFirstRepository}</button>
          </div>
        )}

        <div className="space-y-3">
          {projects.map((p) => {
            const totalNodes = p.schema?.node_labels?.reduce((s, l) => s + l.count, 0) ?? 0;
            const totalEdges = p.schema?.edge_types?.reduce((s, t) => s + t.count, 0) ?? 0;
            return (
              <div key={p.project.name} className="rounded-xl border border-border/30 bg-white/[0.02] hover:bg-white/[0.035] transition-all p-5">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="min-w-0 flex items-start gap-2.5">
                    <div className="mt-1.5"><HealthDot name={p.project.name} /></div>
                    <div className="min-w-0">
                      <h3 className="text-[14px] font-semibold text-foreground/90 mb-0.5">{p.project.name}</h3>
                      <p className="text-[11px] text-foreground/20 font-mono truncate">{p.project.root_path}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <AdrButton project={p.project.name} />
                    <button onClick={() => onSelectProject(p.project.name)} className="px-3 py-1.5 rounded-lg bg-primary/15 hover:bg-primary/25 text-primary text-[12px] font-medium transition-all">{t.projects.viewGraph}</button>
                    <button onClick={() => deleteProject(p.project.name)} className="px-2 py-1.5 rounded-lg hover:bg-destructive/10 text-foreground/20 hover:text-destructive text-[12px] transition-all" title={t.projects.deleteTitle}>✕</button>
                  </div>
                </div>
                {p.schema && (
                  <>
                    <div className="flex gap-6 text-[12px] text-foreground/30 mb-3">
                      <span><strong className="text-foreground/55 tabular-nums">{totalNodes.toLocaleString()}</strong> {t.projects.nodes}</span>
                      <span><strong className="text-foreground/55 tabular-nums">{totalEdges.toLocaleString()}</strong> {t.projects.edges}</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {p.schema.node_labels?.map((l) => (
                        <span key={l.label} className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-medium" style={{ backgroundColor: colorForLabel(l.label) + "10", color: colorForLabel(l.label) + "bb" }}>
                          <span className="w-[4px] h-[4px] rounded-full" style={{ backgroundColor: colorForLabel(l.label) }} />
                          {l.label} {l.count.toLocaleString()}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {showModal && <CreateIndexModal onClose={() => setShowModal(false)} onCreated={() => { setIndexing(true); refresh(); }} />}
    </ScrollArea>
  );
}
