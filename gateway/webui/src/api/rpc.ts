/* JSON-RPC client, pointed at the gateway.
 *
 * Upstream this file talked to the engine's own loopback server at POST /rpc.
 * Here it talks to POST /mcp — the same JSON-RPC protocol and the same tool
 * names, but through the gateway, so every call carries the signed-in user's
 * token and their squad and is checked against role capabilities, the project
 * allowlist and the engine's tool profile before it reaches a graph.
 *
 * That is why this interface has no API of its own: anything the browser can
 * do, an MCP client can do, authorized and audited by exactly the same code. A
 * second read path would be a second place for the tenancy rules to be wrong.
 */

import { authHeaders } from "./session";

let _nextId = 1;

export class RpcError extends Error {
  constructor(
    public code: number,
    message: string,
  ) {
    super(message);
    this.name = "RpcError";
  }
}

/** The token is gone or rejected, so the application can offer sign-in again. */
export class Unauthenticated extends RpcError {
  constructor(message = "the session has expired") {
    super(401, message);
    this.name = "Unauthenticated";
  }
}

export async function callTool<T = unknown>(
  name: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  const res = await fetch("/mcp", {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: _nextId++,
      method: "tools/call",
      params: { name, arguments: args },
    }),
  });

  if (res.status === 401) throw new Unauthenticated();

  if (res.status === 403) {
    // The gateway's refusals name what is missing — "no access to project 'x'
    // (allowed: …)" tells someone what to do, and "forbidden" does not.
    const body = await res.json().catch(() => ({}));
    throw new RpcError(403, body.error ?? "refused");
  }

  if (!res.ok) {
    throw new RpcError(-1, `HTTP ${res.status}: ${res.statusText}`);
  }

  const json = await res.json();

  if (json.error) {
    throw new RpcError(json.error.code ?? -1, json.error.message ?? "unknown");
  }

  /* MCP tool results are wrapped: { result: { content: [{ text: "..." }] } } */
  const text = json?.result?.content?.[0]?.text;
  if (text === undefined) {
    return json.result as T;
  }

  // An engine tool reporting a problem still answers 200, with isError set and
  // the message as the text. That message is usually the actionable one.
  if (json.result?.isError) {
    throw new RpcError(-1, text);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    return text as T; // not every tool answers with JSON
  }
}

/** Which tools this caller may use, so a tab can explain rather than fail. */
export async function listTools(): Promise<string[]> {
  const res = await fetch("/mcp", {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ jsonrpc: "2.0", id: _nextId++, method: "tools/list" }),
  });
  if (res.status === 401) throw new Unauthenticated();
  if (!res.ok) throw new RpcError(-1, `HTTP ${res.status}`);
  const json = await res.json();
  return (json?.result?.tools ?? []).map((tool: { name: string }) => tool.name);
}
