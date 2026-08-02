/* Overview: what the engine computed about a project as a whole.
 *
 * get_architecture already produces the summary — languages, packages, layers,
 * hotspots — so this page presents that rather than deriving anything of its
 * own. Every section is optional because the engine omits what it has nothing
 * to say about, and a project with no hotspots should show no hotspots table
 * rather than an empty one.
 */

import { $, el, jsonOf, callTool, stats, table, status } from '../core.js';

export function init() {
  $('overview-refresh').addEventListener('click', load);
}

export async function load() {
  const project = $('overview-project').value;
  const body = $('overview-body');
  if (!project) {
    body.replaceChildren(el('p', { className: 'muted',
      textContent: 'Nothing is indexed for this squad yet.' }));
    return;
  }

  body.replaceChildren(el('p', { className: 'muted', textContent: 'Loading…' }));
  try {
    const arch = jsonOf(await callTool('get_architecture', { project }));
    body.replaceChildren();

    body.append(stats([
      ['Nodes', arch.total_nodes],
      ['Edges', arch.total_edges],
      ['Languages', (arch.languages || []).length || null],
      ['Packages', (arch.packages || []).length || null],
    ]));

    if (arch.languages?.length) {
      body.append(el('h3', { textContent: 'Languages' }), table(
        ['Language', 'Files'],
        arch.languages.map((l) => [l.name ?? l.language, l.files ?? l.count]),
      ));
    }
    if (arch.packages?.length) {
      body.append(el('h3', { textContent: `Packages (${arch.packages.length})` }), table(
        ['Package', 'Nodes'],
        arch.packages.slice(0, 40).map((p) => [p.name ?? p.path, p.nodes ?? p.count]),
      ));
    }
    if (arch.layers?.length) {
      body.append(el('h3', { textContent: 'Layers' }), table(
        ['Layer', 'Members'],
        arch.layers.map((l) => [l.name, (l.members || []).length || l.count]),
      ));
    }
    if (arch.hotspots?.length) {
      body.append(el('h3', { textContent: 'Hotspots' }), table(
        ['Symbol', 'Why'],
        arch.hotspots.slice(0, 25).map((h) => [h.qualified_name ?? h.name, describe(h)]),
      ));
    }
    if (!arch.total_nodes) {
      body.append(el('p', { className: 'muted',
        textContent: 'The engine returned no graph for this project.' }));
    }
    status(`${project}: ${arch.total_nodes ?? 0} nodes, ${arch.total_edges ?? 0} edges`);
  } catch (error) {
    body.replaceChildren(el('p', { className: 'error', textContent: error.message }));
  }
}

/* The engine names a hotspot's reason differently depending on why it is one,
 * so anything that is not the identity is shown as it comes. */
const describe = (hotspot) =>
  hotspot.reason
  ?? hotspot.metric
  ?? Object.entries(hotspot)
      .filter(([key]) => !['name', 'qualified_name', 'file_path'].includes(key))
      .map(([key, value]) => `${key}=${value}`)
      .join(' ');
