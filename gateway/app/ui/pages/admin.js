/* Admin: a form in front of the administrative API.
 *
 * This is the one page that does not go through /mcp. Administrator accounts
 * are local and separate from OIDC on purpose — they reach configuration and
 * nothing else, never a graph or source — so they have their own session, and
 * signing in here does not sign anyone in there.
 */

import { $, el, state, stats, table, status, adminFetch } from '../core.js';

export function init() {
  $('admin-form').addEventListener('submit', signIn);
}

async function signIn(event) {
  event.preventDefault();
  try {
    const response = await fetch('/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: $('admin-user').value,
        password: $('admin-pass').value,
      }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || 'sign-in failed');

    state.adminToken = body.token;
    sessionStorage.setItem('repo-mcp-admin', body.token);
    $('admin-error').hidden = true;
    $('admin-pass').value = '';
    await load();
    if (body.must_change_password) {
      status('this administrator still has its generated password', true);
    }
  } catch (error) {
    $('admin-error').textContent = error.message;
    $('admin-error').hidden = false;
  }
}

export async function load() {
  if (!state.adminToken) return;
  const body = $('admin-body');
  const response = await adminFetch('/config');

  if (response.status === 401) {
    state.adminToken = '';
    sessionStorage.removeItem('repo-mcp-admin');
    $('admin-signin').hidden = false;
    body.hidden = true;
    return;
  }

  const config = await response.json();
  $('admin-signin').hidden = true;
  body.hidden = false;
  body.replaceChildren();

  body.append(stats([
    ['Generation', config.generation],
    ['Squads', config.tenants.length],
    ['Connectors', config.connectors.length],
    ['Secrets', config.secrets.length],
  ]));

  body.append(el('h3', { textContent: 'Squads' }), config.tenants.length
    ? table(['Name', 'Profile', 'Enabled', 'LDAP groups', 'Projects'],
        config.tenants.map((t) => [t.name, t.tool_profile, t.enabled ? 'yes' : 'no',
          t.ldap_groups.join(', '), t.projects.join(', ')]))
    : el('p', { className: 'muted',
        textContent: 'None. Every request will be refused for want of a squad.' }));

  body.append(el('h3', { textContent: 'Connectors' }), config.connectors.length
    ? table(['Name', 'Provider', 'Squad', 'Mode', 'Enabled'],
        config.connectors.map((c) => [c.name, c.provider, c.tenant, c.mode,
          c.enabled ? 'yes' : 'no']))
    : el('p', { className: 'muted',
        textContent: 'None. Nothing will be discovered or indexed.' }));

  body.append(el('h3', { textContent: 'Settings' }), settingsEditor(config.settings));

  const audit = await (await adminFetch('/audit?limit=25')).json();
  body.append(el('h3', { textContent: 'Recent configuration changes' }),
    audit.entries?.length
      ? table(['When', 'Who', 'What', 'Target'],
          audit.entries.map((e) => [e.at, e.actor, e.action, e.target || '']))
      : el('p', { className: 'muted', textContent: 'Nothing recorded yet.' }));
}

function settingsEditor(settings) {
  const wrap = el('div', { className: 'settings' });

  for (const [key, value] of Object.entries(settings).sort()) {
    const input = el('input', {
      value: typeof value === 'object' ? JSON.stringify(value) : String(value),
    });
    const save = el('button', { textContent: 'Save' });

    save.addEventListener('click', async () => {
      // A setting is JSON, but nobody types quotes around a hostname. Try to
      // parse, and fall back to the bare string.
      let parsed = input.value;
      try {
        parsed = JSON.parse(input.value);
      } catch {
        /* a bare string is a valid value */
      }
      save.disabled = true;
      const response = await adminFetch(`/settings/${encodeURIComponent(key)}`, {
        method: 'PUT', body: JSON.stringify({ value: parsed }),
      });
      const result = await response.json();
      save.disabled = false;
      status(response.ok ? `${key} saved` : (result.detail || 'save failed'), !response.ok);
      if (response.ok) load();
    });

    wrap.append(el('div', { className: 'setting' },
      el('span', { className: 'mono key', textContent: key }), input, save));
  }
  return wrap;
}
