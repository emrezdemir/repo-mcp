/* Secrets: access tokens and API keys, encrypted with SECRETS_KEY.
 *
 * A stored value is never sent back — not to this page and not to any other
 * caller — so the list is names and descriptions. Replacing one means typing
 * it again, which is the correct trade for never having it on a screen.
 */

import { el, field, panel, table } from '../../core.js';

export function render(config, api) {
  const wrap = el('div');

  wrap.append(panel('Secrets', config.secrets.length
    ? listing(config, api)
    : el('p', { className: 'muted', textContent: 'None stored.' })));

  wrap.append(panel('Store a secret', editor(api)));
  wrap.append(el('p', { className: 'muted small' },
    'Values are encrypted with SECRETS_KEY and decrypted only in memory, by the '
    + 'service that needs them. Losing that key makes every stored value '
    + 'unreadable; there is no recovery path, by design.'));
  return wrap;
}

function listing(config, api) {
  const rows = config.secrets.map((secret) => {
    const remove = el('button', { className: 'link', textContent: 'delete' });
    remove.addEventListener('click', async () => {
      if (!confirm(`Delete the secret ${secret.name}? Anything referencing it stops working.`)) {
        return;
      }
      try {
        await api.call(`/secrets/${encodeURIComponent(secret.name)}`, { method: 'DELETE' });
        await api.saved(`secret ${secret.name} deleted`);
      } catch (error) {
        await api.saved(error.message);
      }
    });
    return [secret.name, secret.description || '', remove];
  });
  return table(['Name', 'Description', ''], rows);
}

function editor(api) {
  const name = field({
    label: 'Name', placeholder: 'connector.acme-github.token',
    hint: 'Referenced by this name from a connector or a squad.',
  });
  const value = field({ label: 'Value', kind: 'password', autocomplete: 'off' });
  const description = field({ label: 'Description', placeholder: 'GitHub token for the acme org' });

  const error = el('p', { className: 'error', hidden: true });
  const save = el('button', { className: 'primary', textContent: 'Store' });

  save.addEventListener('click', async () => {
    error.hidden = true;
    save.disabled = true;
    try {
      const target = name.read().trim();
      if (!target) throw new Error('a secret needs a name');
      if (!value.read()) throw new Error('a secret needs a value');
      await api.call(`/secrets/${encodeURIComponent(target)}`, {
        body: { value: value.read(), description: description.read() || null },
      });
      await api.saved(`secret ${target} stored`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  return el('div', { className: 'editor' }, name.wrap, value.wrap, description.wrap, error, save);
}
