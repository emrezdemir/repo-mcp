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
    for (const cell of row) {
      // A cell is usually text, but an actions column is a couple of buttons.
      tr.append(cell instanceof Node
        ? el('td', {}, cell)
        : el('td', { className: 'mono', textContent: cell ?? '' }));
    }
    body.append(tr);
  }
  return el('table', {}, el('thead', {}, head), body);
};

/* A labelled control. `spec.kind` picks the element; everything else is set
 * on it directly, so a caller can pass `value`, `placeholder`, `checked` or
 * anything else an input takes without this having to know about it. */
export function field(spec) {
  const { label, kind = 'text', options, hint, ...rest } = spec;
  let input;
  if (kind === 'select') {
    input = el('select', rest);
    for (const option of options || []) {
      const [value, text] = Array.isArray(option) ? option : [option, option];
      input.append(el('option', { value, textContent: text, selected: value === rest.value }));
    }
  } else if (kind === 'checkbox') {
    input = el('input', { type: 'checkbox', ...rest });
  } else {
    input = el('input', { type: kind, ...rest });
  }

  const wrap = kind === 'checkbox'
    ? el('label', { className: 'filter' }, input, el('span', { textContent: label }))
    : el('label', { className: 'field' }, el('span', { textContent: label }), input);
  if (hint) wrap.append(el('span', { className: 'muted small', textContent: hint }));
  return { wrap, input, read: () => (kind === 'checkbox' ? input.checked : input.value) };
}

/* A comma-or-newline separated list. Squads, groups and globs are all lists,
 * and a text box people can paste into beats a widget nobody asked for. */
export const asList = (text) =>
  String(text || '').split(/[\n,]/).map((item) => item.trim()).filter(Boolean);

export function panel(title, ...children) {
  return el('section', { className: 'panel' }, el('h3', { textContent: title }), ...children);
}

// ── talking to the platform ──────────────────────────────────────────

function headers(extra = {}) {
  const sent = { 'Content-Type': 'application/json', ...extra };
  if (state.token) sent['Authorization'] = `Bearer ${state.token}`;
  if (state.squad) sent['X-Tenant'] = state.squad;
  return sent;
}

/* An access token from a provider expires, usually in minutes. Renewing it
 * just before a request keeps a session that is being used alive without a
 * timer, and without the user discovering the expiry as a failed search.
 *
 * auth.js is imported lazily so that this module stays usable — and testable —
 * without it. */
async function currentToken() {
  const { fresh } = await import('./auth.js');
  const token = await fresh();
  if (token) state.token = token;
  return state.token;
}

/* One MCP tool call, over the same endpoint an MCP client uses. A refusal is
 * thrown with the platform's own words: "no access to project 'x' (allowed:
 * …)" tells a user what to do, and "something went wrong" does not. */
export async function callTool(name, args) {
  await currentToken();
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
  await currentToken();
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
