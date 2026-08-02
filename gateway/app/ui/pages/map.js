/* Map: the whole graph, rendered with WebGL.
 *
 * query_graph is the only tool that returns edges, so how much arrives is
 * decided by the LIMIT in the query rather than by anything clever here. The
 * bound is stated in the interface when it bites: a partial graph that says so
 * is useful, and one that does not is misleading.
 *
 * Drawing and layout live in graph.js. This module is the page around them.
 */

import { $, el, jsonOf, callTool, state, table } from '../core.js';

let view = null;

export function init() {
  $('map-go').addEventListener('click', draw);
  $('map-reset').addEventListener('click', () => view?.resetCamera());
  $('map-find').addEventListener('input', (event) => {
    const name = event.target.value.trim();
    if (name && view?.focusByName(name)) {
      $('map-status').textContent = `focused ${name}`;
    }
  });
}

/* Used by the search page: draw first if nothing is drawn, then focus. */
export async function focusOn(name) {
  if (!view) await draw();
  view?.focusByName(name);
}

export async function draw() {
  const project = $('map-project').value;
  if (!project) return;

  if (!state.session?.can?.raw_query) {
    $('map-status').textContent =
      'the map needs the raw query capability, which this role does not have';
    return;
  }

  $('map-status').textContent = 'fetching…';
  const query =
    'MATCH (a)-[r]->(b) '
    + 'RETURN a.name, labels(a), type(r), b.name, labels(b) '
    + `LIMIT ${window.GraphView.MAX_EDGES}`;

  try {
    const answer = jsonOf(await callTool('query_graph', { project, query }));
    const rows = (answer.rows || []).map(([from, fromLabel, kind, to, toLabel]) =>
      [from, first(fromLabel), kind, to, first(toLabel)]);

    if (!rows.length) {
      $('map-status').textContent = 'the query returned no edges';
      return;
    }

    view?.destroy();
    view = new window.GraphView($('map-canvas'), { onSelect: showNode });
    const loaded = view.load(rows);
    buildFilters(view);

    const summary = `${loaded.nodes} nodes / ${loaded.edges} edges`
      + (loaded.truncated ? ` — capped at ${window.GraphView.MAX_EDGES}, this is part of the graph` : '');

    view.runLayout((progress) => {
      $('map-status').textContent = progress >= 1
        ? summary
        : `${summary} · laying out ${Math.round(progress * 100)}%`;
    });
  } catch (error) {
    $('map-status').textContent = error.message;
  }
}

/* labels(x) is a list, and query_graph serialises a list cell as JSON text —
 * so the value arriving here is the string `["Class"]`, not an array. A node
 * carries one label in practice, so the first is the one. */
function first(value) {
  if (Array.isArray(value)) return value[0] || 'Other';
  if (typeof value === 'string' && value.startsWith('[')) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed[0] || 'Other';
    } catch {
      // Not JSON after all; fall through and use it as it came.
    }
  }
  return value || 'Other';
}

function buildFilters(graphView) {
  const rail = $('map-filters');
  rail.replaceChildren();

  const section = (title, counts, kind) => {
    rail.append(el('h3', { textContent: title }));
    for (const [name, count] of [...counts.entries()].sort((a, b) => b[1] - a[1])) {
      const box = el('input', { type: 'checkbox', checked: true, id: `f-${kind}-${name}` });
      box.addEventListener('change', () => graphView.setHidden(kind, name, !box.checked));
      rail.append(el('label', { className: 'filter', htmlFor: box.id },
        box,
        el('span', { className: 'swatch',
          style: `background:${kind === 'label' ? window.GraphView.colourFor(name) : '#3a4048'}` }),
        el('span', { className: 'grow', textContent: name }),
        el('span', { className: 'count', textContent: count })));
    }
  };

  section('Nodes', graphView.counts.labels, 'label');
  section('Edges', graphView.counts.kinds, 'kind');

  const all = el('button', { className: 'link', textContent: 'show all' });
  all.addEventListener('click', () => {
    for (const box of rail.querySelectorAll('input[type=checkbox]')) {
      if (!box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event('change'));
      }
    }
  });
  rail.append(all);
}

function showNode(node) {
  const detail = $('map-detail');
  if (!node) {
    detail.replaceChildren();
    return;
  }

  detail.replaceChildren(
    el('div', { className: 'mono', textContent: node.name }),
    el('div', { className: 'muted small' },
      el('span', { className: 'tag', textContent: node.label }),
      ` degree ${node.degree}`),
  );

  if (node.out.length) {
    detail.append(el('h3', { textContent: `Outgoing (${node.out.length})` }),
      table(['Kind', 'To'], node.out.slice(0, 60).map((e) => [e.kind, e.to])));
  }
  if (node.in.length) {
    detail.append(el('h3', { textContent: `Incoming (${node.in.length})` }),
      table(['Kind', 'From'], node.in.slice(0, 60).map((e) => [e.kind, e.from])));
  }

  if (!state.session?.can?.read_source) return;

  const button = el('button', { textContent: 'Show source' });
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const snippet = jsonOf(await callTool('get_code_snippet', {
        project: $('map-project').value, qualified_name: node.name,
      }));
      button.replaceWith(el('pre', {
        textContent: snippet.source || snippet._text || '(not found)',
      }));
    } catch (error) {
      button.replaceWith(el('p', { className: 'error', textContent: error.message }));
    }
  });
  detail.append(button);
}
