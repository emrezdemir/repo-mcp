/* The sign-in screen.
 *
 * What it offers depends on how the platform is configured, which only the
 * platform knows — GET /api/auth is asked rather than guessed at build time.
 * Three cases: the provider redirect, a pasted token, and development mode,
 * which says plainly that tokens are not being verified. A screen that looked
 * the same in development as in production would be actively misleading.
 */

import { useEffect, useState } from "react";
import * as auth from "../api/auth";

interface Props {
  /** Called once a token is in hand, so the application can start. */
  onSignedIn: () => void;
  /** Set when a previous attempt failed, so the reason survives a redirect. */
  initialError?: string;
}

export function SignIn({ onSignedIn, initialError }: Props) {
  const [info, setInfo] = useState<auth.AuthInfo | null>(null);
  const [error, setError] = useState(initialError ?? "");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    auth
      .describe()
      .then(setInfo)
      .catch(() => setInfo({ mode: "token", reason: "the platform did not answer" }));
  }, []);

  const redirect = async () => {
    setError("");
    setBusy(true);
    try {
      await auth.begin();
    } catch (exception) {
      setError((exception as Error).message);
      setBusy(false);
    }
  };

  const submitToken = (event: React.FormEvent) => {
    event.preventDefault();
    if (!token.trim()) return;
    auth.useToken(token.trim());
    onSignedIn();
  };

  const oidc = info?.mode === "oidc";
  const development = info?.mode === "development";

  return (
    <div className="h-screen flex items-center justify-center bg-background text-foreground p-6">
      <div className="w-full max-w-md rounded-xl border border-border/40 bg-white/[0.03] p-7">
        <div className="flex items-center gap-2.5 mb-5">
          <div className="w-[7px] h-[7px] rounded-full bg-primary" />
          <span className="text-[15px] font-semibold tracking-tight">repo-mcp</span>
        </div>

        {!info && (
          <p className="text-[12px] text-muted-foreground">
            Checking how this platform signs people in…
          </p>
        )}

        {oidc && (
          <>
            <p className="text-[12px] text-muted-foreground mb-4">
              Sign in with your organisation account.
            </p>
            <button
              onClick={redirect}
              disabled={busy}
              className="w-full px-3 py-2 rounded-md bg-primary/15 text-primary text-[13px]
                         font-medium hover:bg-primary/25 transition-colors disabled:opacity-50"
            >
              {busy ? "Redirecting…" : "Sign in"}
            </button>
            <p className="text-[11px] text-muted-foreground/70 mt-3 leading-relaxed">
              You will be sent to your identity provider and back. Group membership
              comes from the directory, so access is whatever it already grants —
              this platform keeps no user list of its own.
            </p>
          </>
        )}

        {development && (
          <p className="text-[12px] text-muted-foreground mb-4">
            This platform is in development mode. {info?.reason}. The token{" "}
            <code className="text-primary/80">make dev</code> prints is the one to use.
          </p>
        )}

        {info && !oidc && !development && info.reason && (
          <p className="text-[12px] text-muted-foreground mb-4">{info.reason}</p>
        )}

        {info && (!oidc || showToken) && (
          <form onSubmit={submitToken} className="mt-4 space-y-2">
            <label className="block text-[11px] text-muted-foreground">Bearer token</label>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="eyJhbGciOi… or your development token"
              className="w-full px-3 py-2 rounded-md bg-black/30 border border-border/40
                         text-[12px] font-mono outline-none focus:border-primary/50"
            />
            <button
              type="submit"
              className="w-full px-3 py-2 rounded-md bg-white/[0.06] text-[13px]
                         hover:bg-white/[0.1] transition-colors"
            >
              Sign in
            </button>
          </form>
        )}

        {oidc && !showToken && (
          <button
            onClick={() => setShowToken(true)}
            className="text-[11px] text-muted-foreground/70 hover:text-foreground/80 mt-3 underline"
          >
            use a token instead
          </button>
        )}

        {error && <p className="text-[12px] text-red-400 mt-4">{error}</p>}

        <p className="text-[11px] text-muted-foreground/50 mt-5 leading-relaxed">
          Nothing is written to disk: the token lives in this tab and goes when it closes.
        </p>
      </div>
    </div>
  );
}
