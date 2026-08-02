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

/* The last session read, so any component can ask what this caller may do
 * without threading it through every prop. It is a convenience only: the
 * gateway decides on every request, and a stale answer here costs a button
 * that then fails with a clear refusal. */
let current: Session | null = null;
const listeners = new Set<(session: Session | null) => void>();

export const currentSession = () => current;

export function onSession(listener: (session: Session | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether this caller may call a tool at all — role and squad profile both. */
export const canCall = (tool: string) => Boolean(current?.tools?.includes(tool));

export async function loadSession(): Promise<Session> {
  const response = await fetch("/api/session", { headers: await authHeaders() });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error ?? "sign-in failed");
  }
  current = (await response.json()) as Session;
  for (const listener of listeners) listener(current);
  return current;
}
