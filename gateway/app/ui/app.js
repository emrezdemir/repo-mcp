/* Entry point: sign-in, the squad selector, and which page is showing.
 *
 * Each page is its own module and owns its own DOM. They share `core.js` and
 * nothing else, so a page can be rewritten — or replaced with a framework
 * component — without touching the others.
 */

import { $, el, state, status, loadSession, callTool, jsonOf } from './core.js';
import * as overview from './pages/overview.js';
import * as search from './pages/search.js';
import * as map from './pages/map.js';
import * as admin from './pages/admin.js';

const PAGES = { overview, search, map, admin };

// ── sign in and out ──────────────────────────────────────────────────

$('signin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const token = $('token').value.trim();
  if (!token) return;

  state.token = token;
  try {
    await start();
    sessionStorage.setItem('repo-mcp-token', token);
  } catch (error) {
    state.token = '';
    $('signin-error').textContent = error.message;
    $('signin-error').hidden = false;
  }
});

$('signout').addEventListener('click', () => {
  sessionStorage.clear();
  location.reload();
});

async function start() {
  const session = await loadSession();
  state.session = session;

  // One squad means nothing to choose; several means the choice cannot be
  // made silently, because it decides which store is read.
  if (!state.squad && session.squad) state.squad = session.squad;
  if (!state.squad && session.squads.length === 1) [state.squad] = session.squads;

  const squad = $('squad');
  squad.replaceChildren();
  if (session.squads.length > 1) {
    squad.append(el('option', { value: '', textContent: 'choose a squad…' }));
  }
  for (const name of session.squads) {
    squad.append(el('option', {
      value: name, textContent: name, selected: name === state.squad,
    }));
  }
  squad.hidden = session.squads.length <= 1;

  $('identity').textContent = session.username + (session.role ? ` · ${session.role}` : '');
  $('signin').hidden = true;
  $('app').hidden = false;

  for (const page of Object.values(PAGES)) page.init?.();
  await fillProjects();
  show(location.hash.slice(1) || 'overview');
}

$('squad').addEventListener('change', async (event) => {
  state.squad = event.target.value;
  sessionStorage.setItem('repo-mcp-squad', state.squad);
  state.session = await loadSession();
  await fillProjects();
  show(state.page);
});

/* A squad's allowlist may be a pattern rather than a name, so the engine is
 * asked what exists rather than the pattern being displayed as if it were a
 * project. */
async function fillProjects() {
  const selects = ['overview-project', 'search-project', 'map-project'].map($);
  let names = [];
  try {
    names = (jsonOf(await callTool('list_projects', {})).projects || []).map((p) => p.name);
  } catch (error) {
    status(error.message, true);
  }

  for (const select of selects) {
    const previous = select.value;
    select.replaceChildren();
    if (!names.length) {
      select.append(el('option', { value: '', textContent: 'no indexed project' }));
      continue;
    }
    for (const name of names) {
      select.append(el('option', { value: name, textContent: name }));
    }
    if (names.includes(previous)) select.value = previous;
  }
}

// ── pages ────────────────────────────────────────────────────────────

for (const button of document.querySelectorAll('nav button')) {
  button.addEventListener('click', () => show(button.dataset.page));
}

export function show(page) {
  state.page = page;
  location.hash = page;

  for (const section of document.querySelectorAll('.page')) {
    section.hidden = section.id !== `page-${page}`;
  }
  for (const button of document.querySelectorAll('nav button')) {
    button.setAttribute('aria-current', String(button.dataset.page === page));
  }

  // Pages that are cheap to (re)load do so on arrival; the map does not,
  // because drawing a graph is a deliberate act, not a side effect of
  // clicking a tab.
  if (page === 'overview') overview.load();
  if (page === 'admin') admin.load();
}

// ── start ────────────────────────────────────────────────────────────

if (state.token) {
  start().catch(() => {
    sessionStorage.removeItem('repo-mcp-token');
    state.token = '';
  });
}
