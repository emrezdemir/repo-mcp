/* Signing in through the identity provider.
 *
 * Authorization Code with PKCE, in the browser, against the same issuer the
 * gateway verifies tokens from. There is no client secret — a public client
 * cannot keep one — and the code the provider hands back is worthless without
 * the verifier that never left this tab.
 *
 * The gateway is not in the flow. It publishes the issuer and the client id at
 * GET /api/auth and then verifies whatever token arrives on /mcp, exactly as
 * it does for an MCP client: a browser session and an agent session are the
 * same kind of session, authorized by the same code.
 *
 * What is stored, and where: the access token, the refresh token and the
 * expiry go in sessionStorage and nowhere else — not localStorage, not a
 * cookie. Closing the tab ends the session and nothing reaches disk.
 */

const KEYS = {
  token: "repo-mcp-token",
  refresh: "repo-mcp-refresh",
  expires: "repo-mcp-expires",
  verifier: "repo-mcp-pkce",
  state: "repo-mcp-state",
  target: "repo-mcp-return",
} as const;

/* Renew this long before the token actually expires, so a request already in
 * flight when the clock runs out does not fail. */
const REFRESH_MARGIN_SECONDS = 60;

export interface AuthInfo {
  mode: "oidc" | "token" | "development";
  issuer?: string;
  client_id?: string;
  audience?: string;
  scopes?: string;
  reason?: string;
}

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
}

let described: AuthInfo | null = null;
let discovered: Discovery | null = null;

export async function describe(): Promise<AuthInfo> {
  if (described) return described;
  const response = await fetch("/api/auth");
  described = response.ok
    ? ((await response.json()) as AuthInfo)
    : { mode: "token", reason: "the platform did not answer" };
  return described;
}

/* OIDC discovery, once per page: the document names the endpoints, so a realm
 * that moves them does not need this file changed. */
async function metadata(issuer: string): Promise<Discovery> {
  if (discovered) return discovered;
  const response = await fetch(`${issuer}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error(
      `the provider at ${issuer} did not answer discovery (${response.status}). ` +
        "Check the issuer, and that this origin is allowed to reach it.",
    );
  }
  discovered = (await response.json()) as Discovery;
  return discovered;
}

// ── PKCE ─────────────────────────────────────────────────────────────

function base64url(buffer: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(buffer));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const randomString = () =>
  base64url(crypto.getRandomValues(new Uint8Array(32)).buffer);

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64url(digest);
}

/* Where the provider sends the browser back. Fixed rather than taken from the
 * current URL, so the value registered with the provider is one string. */
const redirectUri = () => `${location.origin}/ui`;

// ── the flow ─────────────────────────────────────────────────────────

export async function begin(): Promise<void> {
  const info = await describe();
  if (info.mode !== "oidc" || !info.issuer || !info.client_id) {
    throw new Error("this platform has no browser sign-in configured");
  }

  const meta = await metadata(info.issuer);
  const verifier = randomString();
  const state = randomString();

  sessionStorage.setItem(KEYS.verifier, verifier);
  sessionStorage.setItem(KEYS.state, state);
  // Come back to whatever was being looked at, not always the first tab.
  sessionStorage.setItem(KEYS.target, location.search + location.hash);

  const url = new URL(meta.authorization_endpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", info.client_id);
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("scope", info.scopes ?? "openid profile");
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", await challengeFor(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  location.assign(url.toString());
}

/* Called on every load. Returns a token when this load is the return leg of a
 * sign-in, and null otherwise. */
export async function complete(): Promise<string | null> {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  const failure = params.get("error");

  if (failure) {
    clean();
    throw new Error(params.get("error_description") ?? failure);
  }
  if (!code) return null;

  const expected = sessionStorage.getItem(KEYS.state);
  sessionStorage.removeItem(KEYS.state);
  // A code arriving with the wrong state is not this tab's sign-in.
  if (!expected || params.get("state") !== expected) {
    clean();
    throw new Error("the sign-in did not match this tab; try again");
  }

  const verifier = sessionStorage.getItem(KEYS.verifier);
  sessionStorage.removeItem(KEYS.verifier);
  if (!verifier) {
    clean();
    throw new Error("the sign-in could not be completed; try again");
  }

  const info = await describe();
  const meta = await metadata(info.issuer!);
  const response = await fetch(meta.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: info.client_id!,
      code_verifier: verifier,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  clean();

  if (!response.ok) {
    throw new Error(
      payload.error_description ?? payload.error ?? "the provider refused the code",
    );
  }

  keep(payload);
  return payload.access_token as string;
}

interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
}

function keep(payload: TokenResponse): void {
  sessionStorage.setItem(KEYS.token, payload.access_token);
  if (payload.refresh_token) {
    sessionStorage.setItem(KEYS.refresh, payload.refresh_token);
  }
  if (payload.expires_in) {
    sessionStorage.setItem(
      KEYS.expires,
      String(Date.now() + payload.expires_in * 1000),
    );
  }
}

/* Take the code out of the address bar. It is single-use and already spent,
 * but leaving it in the history serves nobody. The stored return route is
 * restored at the same time. */
function clean(): void {
  const target = sessionStorage.getItem(KEYS.target) ?? "";
  sessionStorage.removeItem(KEYS.target);
  history.replaceState(null, "", location.pathname + target);
}

/** A token entered by hand, for a platform with no browser client. */
export function useToken(token: string): void {
  sessionStorage.setItem(KEYS.token, token);
  sessionStorage.removeItem(KEYS.expires);
  sessionStorage.removeItem(KEYS.refresh);
}

/* The token to use now, renewed if it is about to expire. Null means the
 * session cannot be extended and a sign-in is needed. */
export async function fresh(): Promise<string | null> {
  const token = sessionStorage.getItem(KEYS.token);
  const expires = Number(sessionStorage.getItem(KEYS.expires) ?? 0);
  if (!token) return null;
  if (!expires || Date.now() < expires - REFRESH_MARGIN_SECONDS * 1000) {
    return token;
  }

  const refresh = sessionStorage.getItem(KEYS.refresh);
  const info = await describe();
  if (!refresh || info.mode !== "oidc") return null;

  try {
    const meta = await metadata(info.issuer!);
    const response = await fetch(meta.token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refresh,
        client_id: info.client_id!,
      }),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as TokenResponse;
    keep(payload);
    return payload.access_token;
  } catch {
    // An unreachable provider is not a reason to throw: the caller handles a
    // null by asking for a sign-in.
    return null;
  }
}

export const current = () => sessionStorage.getItem(KEYS.token);

export function forget(): void {
  for (const key of Object.values(KEYS)) sessionStorage.removeItem(key);
}
