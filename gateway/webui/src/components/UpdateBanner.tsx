import { useEffect, useState } from "react";

/* A thin bar that appears when the gateway reports a newer release than the one
 * running. The gateway does the check (GET /api/version, cached, and off when
 * UPDATE_CHECK is set); this only shows what it found and points at the upgrade.
 * It renders nothing when there is no update, when the check is off, or once the
 * operator dismisses it for that version. */

interface VersionInfo {
  version: string;
  latest: string | null;
  update_available: boolean;
}

const DISMISS_KEY = "repo-mcp:update-dismissed";

export function UpdateBanner() {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/version")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: VersionInfo | null) => {
        if (alive) setInfo(data);
      })
      .catch(() => {
        /* A failed version check is not worth surfacing; the banner just
         * stays hidden. */
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!info?.update_available || !info.latest) return null;
  const latest = info.latest;
  const current = info.version;
  if (dismissed || sessionStorage.getItem(DISMISS_KEY) === latest) return null;

  return (
    <div className="flex items-center justify-center gap-3 px-4 py-1.5 text-[12px] bg-primary/15 text-primary border-b border-primary/20 shrink-0">
      <span>
        repo-mcp <span className="font-mono">v{latest}</span> is available — you
        are on <span className="font-mono">v{current}</span>.
      </span>
      <a
        href={`https://github.com/emrezdemir/repo-mcp/releases/tag/v${latest}`}
        target="_blank"
        rel="noreferrer"
        className="underline hover:text-foreground"
      >
        Release notes
      </a>
      <span className="text-primary/40">·</span>
      <span className="text-muted-foreground">
        upgrade with <span className="font-mono">make upgrade</span>
      </span>
      <button
        onClick={() => {
          sessionStorage.setItem(DISMISS_KEY, latest);
          setDismissed(true);
        }}
        className="ml-1 text-primary/50 hover:text-foreground"
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  );
}
