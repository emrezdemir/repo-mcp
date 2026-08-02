/* Squads: the isolation boundary, so this is the page that matters most.
 *
 * A squad is an LDAP group set plus a project allowlist plus an engine tool
 * profile. The gateway refuses a group that already belongs to another squad,
 * because a person in two squads at once would make the boundary ambiguous —
 * that refusal arrives here as an ordinary message.
 */

import { el, field, asList, panel, table } from '../../core.js';

const PROFILES = [
  ['analysis', 'analysis — read-only inspection'],
  ['scout', 'scout — structure only, no source'],
  ['all', 'all — every tool the engine has'],
];

export function render(config, api) {
  const wrap = el('div');

  wrap.append(panel('Squads', config.tenants.length
    ? listing(config, api)
    : el('p', { className: 'muted',
        textContent: 'None yet. Until one exists every request is refused for want of a squad.' })));

  wrap.append(panel('Add or replace a squad', editor(null, api)));
  return wrap;
}

function listing(config, api) {
  const rows = config.tenants.map((tenant) => {
    const edit = el('button', { className: 'link', textContent: 'edit' });
    const remove = el('button', { className: 'link', textContent: 'delete' });
    const actions = el('span', {}, edit, ' ', remove);

    edit.addEventListener('click', (event) => {
      const holder = event.target.closest('tr');
      // The editor opens under the row it belongs to, so it is obvious which
      // squad is being changed.
      const existing = holder.nextElementSibling;
      if (existing?.classList.contains('inline')) {
        existing.remove();
        return;
      }
      const cell = el('td', { colSpan: 6 }, editor(tenant, api));
      holder.after(el('tr', { className: 'inline' }, cell));
    });

    remove.addEventListener('click', async () => {
      if (!confirm(`Delete the squad ${tenant.name}? Its members lose access at once.`)) return;
      try {
        await api.call(`/tenants/${encodeURIComponent(tenant.name)}`, { method: 'DELETE' });
        await api.saved(`squad ${tenant.name} deleted`);
      } catch (error) {
        await api.saved(error.message);
      }
    });

    return [
      tenant.name,
      tenant.tool_profile,
      tenant.enabled ? 'yes' : 'no',
      tenant.ldap_groups.join(', '),
      tenant.projects.join(', '),
      actions,
    ];
  });

  return table(['Name', 'Profile', 'Enabled', 'LDAP groups', 'Projects', ''], rows);
}

function editor(tenant, api) {
  const name = field({
    label: 'Name', value: tenant?.name || '', disabled: Boolean(tenant),
    placeholder: 'payments',
  });
  const groups = field({
    label: 'LDAP groups', value: (tenant?.ldap_groups || []).join(', '),
    placeholder: 'squad-payments, squad-payments-leads',
    hint: 'Comma separated. A group may belong to one squad only.',
  });
  const projects = field({
    label: 'Projects', value: (tenant?.projects || []).join(', '),
    placeholder: 'acme-payments-*, acme-ledger',
    hint: 'Names or globs. Anything outside this list is refused.',
  });
  const profile = field({
    label: 'Tool profile', kind: 'select', options: PROFILES,
    value: tenant?.tool_profile || 'analysis',
  });
  const structural = field({
    label: 'Structure only — refuse the tools that return source',
    kind: 'checkbox', checked: Boolean(tenant?.structural_only),
  });
  const enabled = field({
    label: 'Enabled', kind: 'checkbox', checked: tenant ? tenant.enabled : true,
  });

  const error = el('p', { className: 'error', hidden: true });
  const save = el('button', { className: 'primary', textContent: tenant ? 'Save' : 'Create' });

  save.addEventListener('click', async () => {
    error.hidden = true;
    save.disabled = true;
    try {
      const target = (tenant?.name || name.read()).trim();
      if (!target) throw new Error('a squad needs a name');
      await api.call(`/tenants/${encodeURIComponent(target)}`, {
        body: {
          ldap_groups: asList(groups.read()),
          projects: asList(projects.read()),
          tool_profile: profile.read(),
          structural_only: structural.read(),
          enabled: enabled.read(),
        },
      });
      await api.saved(`squad ${target} saved`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  return el('div', { className: 'editor' },
    name.wrap, groups.wrap, projects.wrap, profile.wrap,
    structural.wrap, enabled.wrap, error, save);
}
