/* Signing in through the identity provider.
 *
 * Authorization Code with PKCE, in the browser, against the same issuer the
 * gateway verifies tokens from. No client secret exists — a public client
 * cannot keep one — and the code the provider hands back is worthless without
 * the verifier that never left this tab.
 *
 * The gateway is not in the flow. It publishes the issuer and the client id at
 * GET /api/auth and then verifies whatever token arrives on /mcp, exactly as
 * it does for an MCP client. That is deliberate: a browser session and an
 * agent session are the same kind of session, authorized by the same code.
 *
 * What is stored, and where:
 *   - the access token and its expiry, in sessionStorage, so a reload does
 *     not bounce through the provider again; the tab closing ends it
 *   - the refresh token, likewise, when the provider issues one
 *   - the PKCE verifier and state, only between the redirect out and back
 * Nothing is written to localStorage or to a cookie, so nothing survives the
 * browser being closed and nothing is sent to another origin.
 */

const KEYS = {
  token: 'repo-mcp-token',
  refresh: 'repo-mcp-refresh',
  expires: 'repo-mcp-expires',
  verifier: 'repo-mcp-pkce',
  state: 'repo-mcp-state',
  target: 'repo-mcp-return',
};

/* Refresh this long before the token actually expires, so a request that is
 * already in flight when the clock runs out does not fail. */
const REFRESH_MARGIN_SECONDS = 60;

let discovered = null;
let mode = null;

export async function describe() {
  if (mode) return mode;
  const response = await fetch('/api/auth');
  mode = response.ok
    ? await response.json()
    : { mode: 'token', reason: (await response.json().catch(() => ({}))).error };
  return mode;
}

/* OIDC discovery. One request, cached for the life of the page: the document
 * names the authorization and token endpoints, so a realm that moves them
 * does not need this file changed. */
async function metadata(issuer) {
  if (discovered) return discovered;
  const response = await fetch(`${issuer}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error(
      `the provider at ${issuer} did not answer discovery (${response.status}). `
      + 'Check the issuer, and that this origin is allowed to reach it.',
    );
  }
  discovered = await response.json();
  return discovered;
}

// ── PKCE ─────────────────────────────────────────────────────────────

const randomString = () => {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return base64url(bytes.buffer);
};

function base64url(buffer) {
  const binary = String.fromCharCode(...new Uint8Array(buffer));
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function challengeFor(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return base64url(digest);
}

/* Where the provider sends the browser back. The path is fixed rather than
 * taken from the current URL, so the value registered with the provider is one
 * string and not one per page. */
const redirectUri = () => `${location.origin}/ui`;

// ── the flow ─────────────────────────────────────────────────────────

export async function begin() {
  const info = await describe();
  if (info.mode !== 'oidc') throw new Error('this platform has no browser sign-in configured');

  const meta = await metadata(info.issuer);
  const verifier = randomString();
  const state = randomString();

  sessionStorage.setItem(KEYS.verifier, verifier);
  sessionStorage.setItem(KEYS.state, state);
  // Come back to whatever page was being looked at, not always the first one.
  sessionStorage.setItem(KEYS.target, location.hash || '#overview');

  const url = new URL(meta.authorization_endpoint);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('client_id', info.client_id);
  url.searchParams.set('redirect_uri', redirectUri());
  url.searchParams.set('scope', info.scopes);
  url.searchParams.set('state', state);
  url.searchParams.set('code_challenge', await challengeFor(verifier));
  url.searchParams.set('code_challenge_method', 'S256');
  location.assign(url.toString());
}

/* Called on every load. Returns a token when this load is the return leg of a
 * sign-in, and null otherwise. */
export async function complete() {
  const params = new URLSearchParams(location.search);
  const code = params.get('code');
  const error = params.get('error');

  if (error) {
    clean();
    throw new Error(params.get('error_description') || error);
  }
  if (!code) return null;

  const expected = sessionStorage.getItem(KEYS.state);
  sessionStorage.removeItem(KEYS.state);
  // A code arriving with the wrong state is not this tab's sign-in.
  if (!expected || params.get('state') !== expected) {
    clean();
    throw new Error('the sign-in did not match this tab; try again');
  }

  const verifier = sessionStorage.getItem(KEYS.verifier);
  sessionStorage.removeItem(KEYS.verifier);
  if (!verifier) {
    clean();
    throw new Error('the sign-in could not be completed; try again');
  }

  const info = await describe();
  const meta = await metadata(info.issuer);
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri(),
    client_id: info.client_id,
    code_verifier: verifier,
  });

  const response = await fetch(meta.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const payload = await response.json().catch(() => ({}));
  clean();

  if (!response.ok) {
    throw new Error(payload.error_description || payload.error || 'the provider refused the code');
  }

  keep(payload);
  return payload.access_token;
}

function keep(payload) {
  sessionStorage.setItem(KEYS.token, payload.access_token);
  if (payload.refresh_token) sessionStorage.setItem(KEYS.refresh, payload.refresh_token);
  if (payload.expires_in) {
    sessionStorage.setItem(KEYS.expires, String(Date.now() + payload.expires_in * 1000));
  }
}

/* Take the code out of the address bar. It is single-use and already spent,
 * but leaving it in the history serves nobody. */
function clean() {
  history.replaceState(null, '', location.pathname + (location.hash || ''));
}

/* Called before a request when a token is about to expire. Returns the token
 * to use, refreshing it if the provider gave a refresh token, and null when
 * the session cannot be extended and the user has to sign in again. */
export async function fresh() {
  const token = sessionStorage.getItem(KEYS.token);
  const expires = Number(sessionStorage.getItem(KEYS.expires) || 0);
  if (!token) return null;
  if (!expires || Date.now() < expires - REFRESH_MARGIN_SECONDS * 1000) return token;

  const refresh = sessionStorage.getItem(KEYS.refresh);
  const info = await describe();
  if (!refresh || info.mode !== 'oidc') return null;

  try {
    const meta = await metadata(info.issuer);
    const response = await fetch(meta.token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: refresh,
        client_id: info.client_id,
      }),
    });
    if (!response.ok) return null;
    const payload = await response.json();
    keep(payload);
    return payload.access_token;
  } catch {
    // An unreachable provider is not a reason to throw here; the caller
    // handles a null by asking for a sign-in.
    return null;
  }
}

export function forget() {
  for (const key of Object.values(KEYS)) sessionStorage.removeItem(key);
}

export const returnTo = () => sessionStorage.getItem(KEYS.target) || '#overview';
