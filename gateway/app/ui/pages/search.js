/* Search: find a symbol by name, then look at it.
 *
 * search_graph needs only the read-graph capability, so every role can use
 * this page. Reading the source behind a result needs read-source, which the
 * devops role deliberately lacks — the result is still shown, without the
 * body, rather than the row disappearing.
 */

import { $, el, jsonOf, callTool, state } from '../core.js';
import * as map from './map.js';
import { show } from '../app.js';

export function init() {
  $('search-go').addEventListener('click', run);
  $('search-query').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') run();
  });
}

async function run() {
  const project = $('search-project').value;
  const query = $('search-query').value.trim();
  const results = $('search-results');
  if (!project || !query) return;

  results.replaceChildren(el('p', { className: 'muted', textContent: 'Searching…' }));
  $('search-detail').replaceChildren();

  try {
    const found = jsonOf(await callTool('search_graph', { project, query, limit: 50 }));
    const hits = found.results || [];
    results.replaceChildren();

    if (!hits.length) {
      results.append(el('p', { className: 'muted', textContent: 'No match.' }));
      return;
    }

    results.append(el('p', { className: 'muted small', textContent:
      `${found.total} match${found.total === 1 ? '' : 'es'}`
      + (found.has_more ? ', showing the first 50' : '')
      + (found.search_mode ? ` · ${found.search_mode}` : '') }));

    for (const hit of hits) {
      const row = el('div', { className: 'hit' },
        el('div', {},
          el('span', { className: 'mono', textContent: hit.name }), ' ',
          el('span', { className: 'tag', textContent: hit.label || '' })),
        el('div', { className: 'where mono',
          textContent: `${hit.file_path}:${hit.start_line}` }));
      row.addEventListener('click', () => {
        for (const other of results.querySelectorAll('.hit')) {
          other.setAttribute('aria-selected', 'false');
        }
        row.setAttribute('aria-selected', 'true');
        showSymbol(project, hit);
      });
      results.append(row);
    }
  } catch (error) {
    results.replaceChildren(el('p', { className: 'error', textContent: error.message }));
  }
}

async function showSymbol(project, hit) {
  const detail = $('search-detail');
  detail.replaceChildren(
    el('div', { className: 'mono', textContent: hit.qualified_name || hit.name }),
    el('div', { className: 'muted small mono',
      textContent: `${hit.file_path}:${hit.start_line}-${hit.end_line}` }),
  );

  if (state.session?.can?.raw_query) {
    const toMap = el('button', { textContent: 'Show on the map' });
    toMap.addEventListener('click', async () => {
      $('map-project').value = project;
      show('map');
      await map.focusOn(hit.name);
    });
    detail.append(toMap);
  }

  if (!state.session?.can?.read_source) {
    detail.append(el('p', { className: 'muted',
      textContent: 'Your role cannot read source; the graph position is above.' }));
    return;
  }

  const loading = el('p', { className: 'muted', textContent: 'Loading source…' });
  detail.append(loading);
  try {
    const snippet = jsonOf(await callTool('get_code_snippet', {
      project, qualified_name: hit.qualified_name || hit.name,
    }));
    loading.replaceWith(el('pre', {
      textContent: snippet.source || snippet._text || '(no source returned)',
    }));
  } catch (error) {
    loading.replaceWith(el('p', { className: 'error', textContent: error.message }));
  }
}
