/* A symbol the engine found that is not in the drawn graph.
 *
 * The graph is drawn up to a node budget, so a project-wide search can return
 * symbols that have no node on screen. They still have a location and source,
 * and both are worth showing — but their edges are with nodes that were not
 * drawn, so this says that rather than rendering an empty connections list,
 * which would read as "nothing references this" and be false.
 */

import { useState } from "react";
import { callTool } from "../api/rpc";
import type { SearchHit } from "../api/platform";
import { useCan } from "../hooks/useCan";

interface Props {
  hit: SearchHit;
  project: string | null;
  onClose: () => void;
}

export function OffGraphPanel({ hit, project, onClose }: Props) {
  const maySeeSource = useCan("get_code_snippet");
  const [code, setCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const result = await callTool<{ source?: string }>("get_code_snippet", {
        qualified_name: hit.qualified_name,
        project,
      });
      setCode(result.source ?? "(source not available)");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col overflow-auto">
      <div className="px-4 pt-4 pb-3 border-b border-border/30">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-[13px] font-semibold truncate">{hit.name}</h3>
          <button onClick={onClose} aria-label="Close"
                  className="text-foreground/20 hover:text-foreground/50 text-[16px] leading-none p-1">
            ×
          </button>
        </div>
        <p className="text-[10px] uppercase tracking-widest text-foreground/25 mt-1">{hit.label}</p>
        <p className="text-[11px] text-foreground/35 font-mono mt-2 break-all leading-relaxed">
          {hit.file_path}
          {hit.start_line ? (
            <span className="text-foreground/45">
              {" "}:{hit.start_line}
              {hit.end_line && hit.end_line !== hit.start_line ? `-${hit.end_line}` : ""}
            </span>
          ) : null}
        </p>

        <div className="mt-3">
          {maySeeSource ? (
            <button
              onClick={code ? () => setCode(null) : load}
              disabled={loading}
              className="px-2.5 py-1 rounded-md bg-primary/15 text-primary text-[11px] font-medium
                         hover:bg-primary/25 transition-colors disabled:opacity-50"
            >
              {loading ? "Loading…" : code ? "Hide code" : "Show code"}
            </button>
          ) : (
            <p className="text-[11px] text-foreground/30">
              This squad's tool profile does not return source code.
            </p>
          )}
        </div>

        {error && <p role="alert" className="text-[11px] text-red-400/80 mt-2">{error}</p>}
        {code && (
          <pre className="mt-3 text-[11px] font-mono text-foreground/70 whitespace-pre-wrap
                          bg-black/30 border border-border/30 rounded-lg p-3 leading-relaxed">
            {code}
          </pre>
        )}
      </div>

      <div className="px-4 py-4">
        <p className="text-[11px] text-foreground/35 leading-relaxed">
          This symbol is not in the drawn graph, so its connections are not
          shown — they run to nodes that were not drawn. Raise the node budget
          and search again to see it in place.
        </p>
      </div>
    </div>
  );
}
