/* Admin: a form in front of the administrative API.
 *
 * This is the one page that does not go through /mcp. Administrator accounts
 * are local and separate from OIDC on purpose — they reach configuration and
 * nothing else, never a graph or source — so they have their own session, and
 * signing in here does not sign anyone in there.
 *
 * Everything `repo-mcp-admin` can do is here, and the other way round: both
 * call the same routes, which call the same functions. A gap between the two
 * is a bug, and common/tests/test_cli_config.py fails when one appears.
 *
 * Each section is its own module under admin/. They receive the configuration
 * and a way to reload it, and return a DOM node; none of them know about each
 * other.
 */

import { $, el, state, status, adminFetch } from '../core.js';
import * as squads from './admin/squads.js';
import * as roles from './admin/roles.js';
import * as connectors from './admin/connectors.js';
import * as secrets from './admin/secrets.js';
import * as settings from './admin/settings.js';
import * as cache from './admin/cache.js';
import * as audit from './admin/audit.js';
import * as accounts from './admin/accounts.js';

const SECTIONS = [
  ['squads', 'Squads', squads],
  ['roles', 'Roles', roles],
  ['connectors', 'Connectors', connectors],
  ['secrets', 'Secrets', secrets],
  ['settings', 'Settings', settings],
  ['cache', 'Answer cache', cache],
  ['audit', 'Audit', audit],
  ['accounts', 'Administrators', accounts],
];

let section = 'squads';

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
      section = 'accounts';
      await load();
      status('this administrator still has its generated password', true);
    }
  } catch (error) {
    $('admin-error').textContent = error.message;
    $('admin-error').hidden = false;
  }
}

/* Every write goes through here, so a refusal reads the same everywhere: the
 * platform's own words, which say what to do about it. */
export async function call(path, { method = 'PUT', body } = {}) {
  const response = await adminFetch(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    /* 204 and friends have no body */
  }
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(
      typeof detail === 'string' ? detail : JSON.stringify(detail || 'the change was refused'),
    );
  }
  return payload;
}

/* What a section calls after a successful write: report it, redraw from the
 * server rather than from what we hoped we wrote. */
export async function saved(message) {
  status(message);
  await load();
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
  body.replaceChildren(navigation(), await current(config));
}

function navigation() {
  const nav = el('nav', { className: 'subnav' });
  for (const [id, label] of SECTIONS) {
    const button = el('button', { textContent: label });
    button.setAttribute('aria-current', String(id === section));
    button.addEventListener('click', () => {
      section = id;
      load();
    });
    nav.append(button);
  }
  return nav;
}

async function current(config) {
  const [, , module] = SECTIONS.find(([id]) => id === section) || SECTIONS[0];
  try {
    return await module.render(config, { call, saved, load });
  } catch (error) {
    return el('p', { className: 'error', textContent: error.message });
  }
}
