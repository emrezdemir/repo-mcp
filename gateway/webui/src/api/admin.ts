/* The administrative API.
 *
 * The one part of this interface that does not go through /mcp. Administrator
 * accounts are local and separate from the directory on purpose — they reach
 * configuration and nothing else, never a graph and never source — so they
 * have their own short-lived session, and signing in here signs nobody in
 * there. See docs/adr/0007-break-glass-administrator.md.
 *
 * Every route here is one the `repo-mcp-admin` command also calls, through the
 * same functions, so a squad created from a terminal and one created from a
 * browser are the same row with the same validation and the same audit entry.
 */

const TOKEN_KEY = "repo-mcp-admin";

export const adminToken = () => sessionStorage.getItem(TOKEN_KEY) ?? "";
export const forgetAdmin = () => sessionStorage.removeItem(TOKEN_KEY);

export class AdminUnauthenticated extends Error {}

export interface Config {
  generation: number;
  tenants: Squad[];
  roles: Record<string, string[]>;
  connectors: Connector[];
  settings: Record<string, unknown>;
  secrets: { name: string; description?: string }[];
  admins: { username: string; is_active: boolean; last_login_at?: string }[];
}

export interface Squad {
  name: string;
  tool_profile: string;
  structural_only: boolean;
  enabled: boolean;
  ldap_groups: string[];
  projects: string[];
}

export interface Connector {
  name: string;
  provider: string;
  tenant: string;
  mode: string;
  enabled: boolean;
  persistence?: boolean;
  include?: string[];
  exclude?: string[];
  settings?: Record<string, string>;
  token_secret?: string | null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/admin${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken()}`,
      ...(init.headers ?? {}),
    },
  });

  if (response.status === 401) {
    forgetAdmin();
    throw new AdminUnauthenticated("the administrative session has expired");
  }

  let payload: Record<string, unknown> = {};
  try {
    payload = await response.json();
  } catch {
    /* 204 and friends carry no body */
  }

  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail ?? "the change was refused"),
    );
  }
  return payload as T;
}

export async function signIn(username: string, password: string): Promise<{ must_change_password: boolean }> {
  const response = await fetch("/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "sign-in failed");
  sessionStorage.setItem(TOKEN_KEY, body.token);
  return { must_change_password: Boolean(body.must_change_password) };
}

export const readConfig = () => request<Config>("/config");

export const readAudit = (limit = 100) =>
  request<{ entries: { at: string; actor: string; action: string; target?: string }[] }>(
    `/audit?limit=${limit}`,
  );

export const readAnswerCache = () =>
  request<{
    enabled: boolean;
    entries: number;
    hits: number;
    squads: string[];
    embedding_model: string;
    similarity_threshold: number;
    ttl_seconds: number;
  }>("/answer-cache");

export const purgeAnswerCache = (squad?: string, project?: string) => {
  const query = new URLSearchParams();
  if (squad) query.set("tenant", squad);
  if (project) query.set("project", project);
  return request<{ removed: number }>(`/answer-cache?${query}`, { method: "DELETE" });
};

export const putSquad = (name: string, body: unknown) =>
  request(`/tenants/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(body) });

export const deleteSquad = (name: string) =>
  request(`/tenants/${encodeURIComponent(name)}`, { method: "DELETE" });

export const putRole = (role: string, groups: string[]) =>
  request(`/roles/${encodeURIComponent(role)}`, {
    method: "PUT",
    body: JSON.stringify({ groups }),
  });

export const putConnector = (name: string, body: unknown) =>
  request(`/connectors/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(body) });

export const deleteConnector = (name: string) =>
  request(`/connectors/${encodeURIComponent(name)}`, { method: "DELETE" });

export const putSecret = (name: string, value: string, description?: string) =>
  request(`/secrets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ value, description: description || null }),
  });

export const deleteSecret = (name: string) =>
  request(`/secrets/${encodeURIComponent(name)}`, { method: "DELETE" });

export const putSetting = (key: string, value: unknown) =>
  request(`/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  });

export const changePassword = (password: string) =>
  request("/password", { method: "POST", body: JSON.stringify({ password }) });
