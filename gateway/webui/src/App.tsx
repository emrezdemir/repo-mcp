import { useCallback, useEffect, useState } from "react";
import { GraphTab } from "./components/GraphTab";
import { StatsTab } from "./components/StatsTab";
import { AdminTab } from "./components/AdminTab";
import { SignIn } from "./components/SignIn";
import { SquadPicker } from "./components/SquadPicker";
import * as auth from "./api/auth";
import { chooseSquad, chosenSquad, loadSession, type Session } from "./api/session";
import type { TabId } from "./lib/types";
import { useUiMessages } from "./lib/i18n";

/* Upstream's third tab was "control": engine processes, logs and a filesystem
 * browser, which are single-machine surfaces and have no place in a
 * multi-tenant deployment. It is replaced by the administrative console. */
const TAB_IDS: TabId[] = ["graph", "stats", "admin"];

interface RouteState {
  tab: TabId;
  project: string | null;
}

/* Read the active tab + selected project from the URL query string so the
 * current view survives refreshes and can be bookmarked or shared. */
function readRoute(): RouteState {
  const params = new URLSearchParams(window.location.search);
  const rawTab = params.get("tab");
  const tab = TAB_IDS.includes(rawTab as TabId) ? (rawTab as TabId) : "stats";
  const project = params.get("project");
  return { tab, project: project ? project : null };
}

/* Build the canonical URL for a route, preserving the path and hash. */
function routeUrl(tab: TabId, project: string | null): string {
  const params = new URLSearchParams();
  params.set("tab", tab);
  if (project) params.set("project", project);
  return `${window.location.pathname}?${params.toString()}${window.location.hash}`;
}

export function App() {
  const t = useUiMessages();
  const [route, setRoute] = useState<RouteState>(readRoute);
  const { tab: activeTab, project: selectedProject } = route;

  /* Sign-in gates everything. Three ways in: the return leg of a provider
   * redirect, a token already in this tab, or the sign-in screen. */
  const [session, setSession] = useState<Session | null>(null);
  const [booting, setBooting] = useState(true);
  const [signInError, setSignInError] = useState("");

  const start = useCallback(async () => {
    const loaded = await loadSession();
    // One squad means nothing to choose; several means the choice cannot be
    // made silently, because it decides which store is read.
    if (!chosenSquad() && loaded.squads.length === 1) chooseSquad(loaded.squads[0]);
    setSession(loaded.squad || loaded.squads.length !== 1 ? loaded : await loadSession());
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const returned = await auth.complete();
        if (returned) {
          await start();
          return;
        }
      } catch (exception) {
        setSignInError((exception as Error).message);
      }
      if (auth.current()) {
        try {
          await start();
        } catch {
          // A token that no longer works is not worth reporting on its own:
          // the sign-in screen is the answer and is about to appear.
          auth.forget();
        }
      }
      setBooting(false);
    })();
  }, [start]);

  const signOut = () => {
    auth.forget();
    sessionStorage.clear();
    location.reload();
  };


  /* Normalize the URL on first load so it always carries the current route. */
  useEffect(() => {
    const initial = readRoute();
    window.history.replaceState(null, "", routeUrl(initial.tab, initial.project));
  }, []);

  /* Sync state when the user navigates with the browser back/forward buttons. */
  useEffect(() => {
    const onPopState = () => setRoute(readRoute());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  /* Change the route and push a history entry (skips no-op navigations). */
  const navigate = useCallback((tab: TabId, project: string | null) => {
    const url = routeUrl(tab, project);
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (url === current) return;
    window.history.pushState(null, "", url);
    setRoute({ tab, project });
  }, []);

  /* Every hook above this line, unconditionally: React counts them per
   * render, and an early return before one of them changes the count. */
  if (booting && !session) {
    return <div className="h-screen bg-background" />;
  }

  if (!session) {
    return (
      <SignIn
        initialError={signInError}
        onSignedIn={() => {
          setBooting(true);
          start()
            .catch((exception) => setSignInError((exception as Error).message))
            .finally(() => setBooting(false));
        }}
      />
    );
  }

  const tabs: { id: TabId; label: string }[] = [
    { id: "graph", label: t.tabs.graph },
    { id: "stats", label: t.tabs.projects },
    { id: "admin", label: "Admin" },
  ];

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      {/* Header */}
      <header className="flex items-center justify-between px-5 h-12 border-b border-border bg-[#0b1920]/80 backdrop-blur-md shrink-0">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="w-[7px] h-[7px] rounded-full bg-primary" />
            <span className="text-[13px] font-semibold text-foreground/90 tracking-tight">
              repo-mcp
            </span>
          </div>

          {/* Tabs inline in header */}
          <nav className="flex items-center gap-0.5">
            {tabs.map((tab) => {
              const disabled = tab.id === "graph" && !selectedProject;
              return (
                <button
                  key={tab.id}
                  onClick={() => navigate(tab.id, tab.id === "stats" ? null : selectedProject)}
                  disabled={disabled}
                  title={disabled ? "Select a project first" : undefined}
                  className={`px-3 py-1 rounded-md text-[12px] font-medium transition-all ${
                    disabled
                      ? "text-muted-foreground/30 cursor-not-allowed"
                      : activeTab === tab.id
                        ? "bg-primary/15 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-white/[0.04]"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {selectedProject && (
            <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-white/[0.04] border border-border/30">
              <span className="text-[10px] text-foreground/30 uppercase tracking-wider">
                {t.graph.selectedLabel}
              </span>
              <span className="text-[11px] text-primary font-mono truncate max-w-[240px]">
                {selectedProject}
              </span>
              <button
                onClick={() => navigate("stats", null)}
                className="text-foreground/20 hover:text-foreground/50 text-[12px] ml-1 transition-colors"
              >
                ×
              </button>
            </div>
          )}

          <SquadPicker
            session={session}
            onChoose={(squad) => {
              // The squad decides which store is read, so the whole view is
              // rebuilt rather than patched.
              chooseSquad(squad);
              location.assign(`${location.pathname}?tab=stats`);
            }}
          />
          <span className="text-[11px] text-muted-foreground">
            {session.username}
            {session.role ? ` · ${session.role}` : ""}
          </span>
          <button
            onClick={signOut}
            className="text-[11px] text-muted-foreground/70 hover:text-foreground underline"
          >
            sign out
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 min-h-0">
        {activeTab === "graph" ? (
          <GraphTab project={selectedProject} />
        ) : activeTab === "admin" ? (
          <AdminTab />
        ) : (
          <StatsTab
            onSelectProject={(p) => navigate("graph", p)}
          />
        )}
      </main>
    </div>
  );
}
