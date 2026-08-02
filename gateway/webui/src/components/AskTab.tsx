/* Ask a question about a codebase, in words.
 *
 * This is the platform's own tool rather than the engine's: `ask_codebase`
 * runs `get_architecture` and `search_graph` first and answers from what they
 * returned, so the model is never asked to guess the graph. `answer` therefore
 * cites qualified names, and the evidence it used is real.
 *
 * It needs a model backend. Without one the gateway refuses it by name, and
 * this page says that plainly instead of offering a box that fails.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { callTool, RpcError } from "../api/rpc";
import { listProjects, type ProjectSummary } from "../api/platform";
import { useCan } from "../hooks/useCan";

interface Exchange {
  question: string;
  answer?: string;
  error?: string;
  /** Milliseconds the platform took, so a slow model is visible rather than felt. */
  took?: number;
}

const EXAMPLES = [
  "What happens when a request is authorized?",
  "Where is configuration read, and how does a change reach a running service?",
  "Which parts of this project have no tests?",
];

export function AskTab({ project: initial }: { project: string | null }) {
  const mayAsk = useCan("ask_codebase");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState(initial ?? "");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Exchange[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listProjects()
      .then((found) => {
        setProjects(found);
        setProject((current) => current || found[0]?.name || "");
      })
      .catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, busy]);

  const ask = useCallback(
    async (text: string) => {
      const asked = text.trim();
      if (!asked || !project || busy) return;

      setQuestion("");
      setBusy(true);
      const started = performance.now();
      try {
        const answer = await callTool<string>("ask_codebase", { project, question: asked });
        setHistory((past) => [
          ...past,
          { question: asked, answer: String(answer), took: performance.now() - started },
        ]);
      } catch (exception) {
        // The gateway's refusals name the cause — "smart tools are disabled",
        // "role 'viewer' cannot use smart tools" — and that is what to show.
        const message =
          exception instanceof RpcError
            ? exception.message
            : (exception as Error).message || "the question could not be answered";
        setHistory((past) => [...past, { question: asked, error: message }]);
      } finally {
        setBusy(false);
      }
    },
    [project, busy],
  );

  if (!mayAsk) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="max-w-md text-center space-y-3">
          <h2 className="text-[15px] font-semibold">Asking is not available here</h2>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            This needs a model backend and a role that may use it. An
            administrator sets <span className="font-mono text-primary/80">litellm.base_url</span> and{" "}
            <span className="font-mono text-primary/80">smart_tools.enabled</span> under Admin →
            Settings; the role also needs the smart-tools capability.
          </p>
          <p className="text-[11px] text-muted-foreground/60">
            Everything else on this platform works without one.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border/30">
        <label className="text-[11px] text-muted-foreground" htmlFor="ask-project">
          Project
        </label>
        <select
          id="ask-project"
          value={project}
          onChange={(event) => setProject(event.target.value)}
          className="px-2 py-1 rounded-md bg-white/[0.04] border border-border/30 text-[11px] outline-none focus:border-primary/50"
        >
          {projects.length === 0 && <option value="">nothing indexed yet</option>}
          {projects.map((entry) => (
            <option key={entry.name} value={entry.name}>
              {entry.name}
            </option>
          ))}
        </select>
        <span className="text-[11px] text-muted-foreground/50 ml-auto">
          Answered from the graph, with citations — never from the model's memory.
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-auto px-6 py-5">
        <div className="max-w-3xl mx-auto space-y-5">
          {history.length === 0 && !busy && (
            <div className="space-y-3 pt-6">
              <p className="text-[12px] text-muted-foreground">Try one of these:</p>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  onClick={() => ask(example)}
                  disabled={!project}
                  className="block w-full text-left px-4 py-2.5 rounded-lg border border-border/30
                             bg-white/[0.02] hover:bg-white/[0.05] text-[12px] transition-colors
                             disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {example}
                </button>
              ))}
            </div>
          )}

          {history.map((exchange, index) => (
            <div key={index} className="space-y-2">
              <p className="text-[13px] font-medium">{exchange.question}</p>
              {exchange.error ? (
                <p role="alert"
                   className="text-[12px] text-red-400/90 bg-red-500/10 border border-red-500/20
                              rounded-lg px-3 py-2">
                  {exchange.error}
                </p>
              ) : (
                <>
                  <pre className="text-[12px] text-foreground/80 whitespace-pre-wrap font-sans
                                  leading-relaxed bg-white/[0.02] border border-border/30
                                  rounded-lg px-4 py-3">
                    {exchange.answer}
                  </pre>
                  {exchange.took !== undefined && (
                    <p className="text-[10px] text-muted-foreground/40">
                      {(exchange.took / 1000).toFixed(1)}s
                    </p>
                  )}
                </>
              )}
            </div>
          ))}

          {busy && (
            <p className="text-[12px] text-muted-foreground" role="status" aria-live="polite">
              Gathering evidence from the graph…
            </p>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
        className="border-t border-border/30 px-6 py-4"
      >
        <div className="max-w-3xl mx-auto flex gap-2">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={project ? "Ask about this project…" : "Index a project first"}
            disabled={!project || busy}
            aria-label="Question"
            className="flex-1 px-3 py-2 rounded-md bg-black/30 border border-border/40 text-[12px]
                       outline-none focus:border-primary/50 disabled:opacity-40"
          />
          <button
            type="submit"
            disabled={!question.trim() || !project || busy}
            className="px-4 py-2 rounded-md bg-primary/15 text-primary text-[12px] font-medium
                       hover:bg-primary/25 transition-colors disabled:opacity-40
                       disabled:cursor-not-allowed"
          >
            {busy ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>
    </div>
  );
}
