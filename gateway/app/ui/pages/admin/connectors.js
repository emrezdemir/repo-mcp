/* Connectors: where repositories come from.
 *
 * A connector is a provider, the squad its repositories belong to, and the
 * filters deciding which of them are indexed. The access token is not stored
 * here — it is a secret, referenced by name, so this page never holds one.
 */

import { el, field, asList, panel, table } from '../../core.js';

const PROVIDERS = ['github', 'gitlab', 'bitbucket'];
const MODES = [
  ['moderate', 'moderate — filtered files, with similarity edges'],
  ['fast', 'fast — filtered files, no similarity edges'],
  ['full', 'full — every file'],
  ['cross-repo-intelligence', 'cross-repo — match routes across projects'],
];

/* The settings each provider needs, so the form asks for the right things
 * instead of offering a free-form key/value box. providers.py is where these
 * are read. */
const SETTINGS = {
  github: [['org', 'Organisation', 'acme'], ['base_url', 'API base URL (Enterprise only)', '']],
  gitlab: [['group', 'Group', 'acme/backend'], ['base_url', 'Base URL', 'https://gitlab.example.com']],
  bitbucket: [
    ['workspace', 'Workspace', 'acme'],
    ['project_key', 'Project key', 'PAY'],
    ['username', 'Username', 'ci-bot'],
  ],
};

export function render(config, api) {
  const wrap = el('div');

  wrap.append(panel('Connectors', config.connectors.length
    ? listing(config, api)
    : el('p', { className: 'muted',
        textContent: 'None. Nothing is discovered or indexed until one exists.' })));

  wrap.append(panel('Add or replace a connector', editor(null, config, api)));
  return wrap;
}

function listing(config, api) {
  const rows = config.connectors.map((connector) => {
    const edit = el('button', { className: 'link', textContent: 'edit' });
    const remove = el('button', { className: 'link', textContent: 'delete' });

    edit.addEventListener('click', (event) => {
      const holder = event.target.closest('tr');
      const existing = holder.nextElementSibling;
      if (existing?.classList.contains('inline')) {
        existing.remove();
        return;
      }
      holder.after(el('tr', { className: 'inline' },
        el('td', { colSpan: 7 }, editor(connector, config, api))));
    });

    remove.addEventListener('click', async () => {
      if (!confirm(`Delete the connector ${connector.name}? Indexed graphs are kept.`)) return;
      try {
        await api.call(`/connectors/${encodeURIComponent(connector.name)}`, { method: 'DELETE' });
        await api.saved(`connector ${connector.name} deleted`);
      } catch (error) {
        await api.saved(error.message);
      }
    });

    return [
      connector.name, connector.provider, connector.tenant, connector.mode,
      connector.enabled ? 'yes' : 'no', connector.token_secret || '—',
      el('span', {}, edit, ' ', remove),
    ];
  });

  return table(
    ['Name', 'Provider', 'Squad', 'Mode', 'Enabled', 'Token secret', ''], rows,
  );
}

function editor(connector, config, api) {
  const name = field({
    label: 'Name', value: connector?.name || '', disabled: Boolean(connector),
    placeholder: 'acme-github',
  });
  const provider = field({
    label: 'Provider', kind: 'select', options: PROVIDERS,
    value: connector?.provider || 'github',
  });
  const squad = field({
    label: 'Squad', kind: 'select',
    options: config.tenants.map((t) => t.name),
    value: connector?.tenant || config.tenants[0]?.name || '',
    hint: 'Where discovered repositories are indexed. Create the squad first.',
  });
  const token = field({
    label: 'Token secret', kind: 'select',
    options: [['', '(none)'], ...config.secrets.map((s) => s.name)],
    value: connector?.token_secret || '',
    hint: 'The name of a stored secret. Add it under Secrets first.',
  });
  const include = field({
    label: 'Include', value: (connector?.include || ['*']).join(', '), placeholder: '*',
  });
  const exclude = field({
    label: 'Exclude', value: (connector?.exclude || []).join(', '), placeholder: 'legacy-*',
  });
  const mode = field({
    label: 'Index mode', kind: 'select', options: MODES, value: connector?.mode || 'moderate',
  });
  const persistence = field({
    label: 'Write a shareable graph artifact', kind: 'checkbox',
    checked: connector ? connector.persistence !== false : true,
  });
  const enabled = field({
    label: 'Enabled', kind: 'checkbox', checked: connector ? connector.enabled : true,
  });

  // Provider settings are rebuilt when the provider changes, because what
  // GitHub needs and what Bitbucket needs are not the same three boxes.
  const settingsHolder = el('div');
  let settingFields = [];

  const buildSettings = () => {
    settingFields = (SETTINGS[provider.read()] || []).map(([key, label, placeholder]) =>
      [key, field({ label, placeholder, value: connector?.settings?.[key] ?? '' })]);
    settingsHolder.replaceChildren(...settingFields.map(([, f]) => f.wrap));
  };
  provider.input.addEventListener('change', buildSettings);
  buildSettings();

  const error = el('p', { className: 'error', hidden: true });
  const save = el('button', { className: 'primary', textContent: connector ? 'Save' : 'Create' });

  save.addEventListener('click', async () => {
    error.hidden = true;
    save.disabled = true;
    try {
      const target = (connector?.name || name.read()).trim();
      if (!target) throw new Error('a connector needs a name');
      const settings = {};
      for (const [key, control] of settingFields) {
        const value = control.read().trim();
        if (value) settings[key] = value;
      }
      await api.call(`/connectors/${encodeURIComponent(target)}`, {
        body: {
          provider: provider.read(),
          tenant: squad.read(),
          settings,
          token_secret: token.read() || null,
          include: asList(include.read()),
          exclude: asList(exclude.read()),
          mode: mode.read(),
          persistence: persistence.read(),
          enabled: enabled.read(),
        },
      });
      await api.saved(`connector ${target} saved`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  return el('div', { className: 'editor' },
    name.wrap, provider.wrap, settingsHolder, squad.wrap, token.wrap,
    include.wrap, exclude.wrap, mode.wrap, persistence.wrap, enabled.wrap, error, save);
}
