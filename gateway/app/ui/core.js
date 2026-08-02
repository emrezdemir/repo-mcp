/* Shared state, DOM helpers, and the one way this interface talks to the
 * platform.
 *
 * Native ES modules: the browser resolves the imports, so the interface is
 * split into real files with explicit dependencies and there is still no build
 * step. The three vendored libraries are UMD and load as classic scripts
 * before this, so they arrive as globals — noted where they are used.
 */

export const state = {
  token: sessionStorage.getItem('repo-mcp-token') || '',
  adminToken: sessionStorage.getItem('repo-mcp-admin') || '',
  session: null,
  squad: sessionStorage.getItem('repo-mcp-squad') || '',
  page: 'overview',
};

export const $ = (id) => document.getElementById(id);

export const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
};

export function status(message, bad = false) {
  const footer = $('footer-status');
  footer.textContent = message;
  footer.className = bad ? 'error' : 'muted';
}

export const stats = (pairs) => {
  const wrap = el('div', { className: 'stats' });
  for (const [label, value] of pairs) {
    wrap.append(el('div', { className: 'stat' }, el('b', { textContent: value ?? '—' }), label));
  }
  return wrap;
};

export const table = (columns, rows) => {
  const head = el('tr');
  for (const column of columns) head.append(el('th', { textContent: column }));
  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const cell of row) tr.append(el('td', { className: 'mono', textContent: cell ?? '' }));
    body.append(tr);
  }
  return el('table', {}, el('thead', {}, head), body);
};

// ── talking to the platform ──────────────────────────────────────────

function headers(extra = {}) {
  const sent = { 'Content-Type': 'application/json', ...extra };
  if (state.token) sent['Authorization'] = `Bearer ${state.token}`;
  if (state.squad) sent['X-Tenant'] = state.squad;
  return sent;
}

/* One MCP tool call, over the same endpoint an MCP client uses. A refusal is
 * thrown with the platform's own words: "no access to project 'x' (allowed:
 * …)" tells a user what to do, and "something went wrong" does not. */
export async function callTool(name, args) {
  const response = await fetch('/mcp', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      jsonrpc: '2.0', id: Date.now(), method: 'tools/call',
      params: { name, arguments: args },
    }),
  });

  if (response.status === 401) throw new Error('token rejected — sign in again');
  if (response.status === 403) throw new Error((await response.json()).error || 'refused');
  const body = await response.json();
  if (body.error) throw new Error(body.error.message || String(body.error));
  if (body.result?.isError) throw new Error(textOf(body.result) || 'the tool reported an error');
  return body.result;
}

export const textOf = (result) =>
  (result?.content || []).filter((c) => c.type === 'text').map((c) => c.text).join('\n');

/* Engine tools answer with text that happens to be JSON. Parsing it here keeps
 * every caller from having to know that, and keeps the raw text reachable when
 * a tool answers with prose instead. */
export function jsonOf(result) {
  const text = textOf(result);
  try {
    return JSON.parse(text);
  } catch {
    return { _text: text };
  }
}

export async function loadSession() {
  const response = await fetch('/api/session', { headers: headers() });
  if (!response.ok) throw new Error((await response.json()).error || 'sign-in failed');
  return response.json();
}

export const adminFetch = (path, options = {}) =>
  fetch(`/admin${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${state.adminToken}`,
      ...(options.headers || {}),
    },
  });
