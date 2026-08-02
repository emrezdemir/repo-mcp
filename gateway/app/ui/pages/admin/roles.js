/* Roles: what a person may do, as opposed to which data they may do it to.
 *
 * The two axes are independent. A lead in the payments squad and a lead in
 * checkout have the same capabilities over different repositories, which is
 * why roles are edited here and squads are edited next door.
 *
 * The role list is fixed — the gateway maps each one to a capability set in
 * roles.py — so this page edits the groups behind them, not the roles.
 */

import { el, field, asList, panel, table } from '../../core.js';

const ROLES = [
  ['admin', 'everything, including configuration'],
  ['lead', 'read, analyse, trigger indexing, write ADRs'],
  ['developer', 'read the graph and the source, analyse changes'],
  ['qa', 'read the graph and the source, ingest traces'],
  ['devops', 'read, trigger indexing, ingest traces'],
  ['viewer', 'read the graph, not the source'],
];

export function render(config, api) {
  const wrap = el('div');
  const assigned = config.roles || {};

  wrap.append(el('p', { className: 'muted' },
    'A person holding groups from several roles gets the most privileged one. '
    + 'Roles and squads are independent: this decides what, the squad decides which.'));

  for (const [role, what] of ROLES) {
    wrap.append(panel(role, editor(role, what, assigned[role] || [], api)));
  }

  const unknown = Object.keys(assigned).filter((r) => !ROLES.some(([name]) => name === r));
  if (unknown.length) {
    // A role the gateway does not know grants nothing. Saying so beats leaving
    // an administrator to wonder why a group has no effect.
    wrap.append(panel('Not recognised', table(['Role', 'Groups'],
      unknown.map((role) => [role, assigned[role].join(', ')]))));
  }
  return wrap;
}

function editor(role, what, groups, api) {
  const input = field({
    label: what, value: groups.join(', '),
    placeholder: 'ldap-group-one, ldap-group-two',
    hint: 'Comma separated. Saving an empty box removes the role entirely.',
  });
  const error = el('p', { className: 'error', hidden: true });
  const save = el('button', { textContent: 'Save' });

  save.addEventListener('click', async () => {
    error.hidden = true;
    save.disabled = true;
    try {
      await api.call(`/roles/${encodeURIComponent(role)}`, { body: { groups: asList(input.read()) } });
      await api.saved(`role ${role} saved`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  return el('div', { className: 'editor' }, input.wrap, error, save);
}
