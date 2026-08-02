/* Who the caller is here, and which squad they are looking through.
 *
 * MCP can answer questions about a codebase but not "who am I on this
 * platform": which squad, which role, which tools. GET /api/session exists for
 * that and nothing else. What it reports is a convenience — the authorization
 * decision is made on every request in the gateway — so a stale answer costs a
 * button that then fails with a clear refusal, not an access mistake.
 */

import { fresh } from "./auth";

export interface Session {
  username: string;
  squads: string[];
  squad: string | null;
  role?: string;
  capabilities?: string[];
  tools?: string[];
  can?: {
    search: boolean;
    read_source: boolean;
    raw_query: boolean;
    architecture: boolean;
  };
  projects?: string[];
  tool_profile?: string;
  /** Present when the caller belongs to several squads and has chosen none. */
  reason?: string;
}

const SQUAD_KEY = "repo-mcp-squad";

export const chosenSquad = () => sessionStorage.getItem(SQUAD_KEY) ?? "";

export function chooseSquad(name: string): void {
  if (name) sessionStorage.setItem(SQUAD_KEY, name);
  else sessionStorage.removeItem(SQUAD_KEY);
}

/* Every request to the gateway carries these. The token is renewed here rather
 * than on a timer, so a session in use never expires under someone. */
export async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = await fresh();
  if (token) headers.Authorization = `Bearer ${token}`;
  const squad = chosenSquad();
  if (squad) headers["X-Tenant"] = squad;
  return headers;
}

export async function loadSession(): Promise<Session> {
  const response = await fetch("/api/session", { headers: await authHeaders() });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error ?? "sign-in failed");
  }
  return (await response.json()) as Session;
}
