/* Administrator accounts, and the password of the one signed in.
 *
 * These are local accounts, deliberately outside the directory: they exist so
 * a platform whose OIDC provider is down can still be configured. That is the
 * whole reason they are acceptable, and it is why they reach configuration
 * only — never a graph, never source. See
 * docs/adr/0007-break-glass-administrator.md.
 *
 * Creating an account is not offered here on purpose. A break-glass credential
 * should be handed out from a terminal by someone with access to the host,
 * not minted through a browser session:
 *
 *     repo-mcp-admin create-admin --username <name> --force
 */

import { el, field, panel, table } from '../../core.js';

export function render(config, api) {
  const wrap = el('div');

  wrap.append(panel('Accounts', table(['Username', 'Active', 'Last sign-in'],
    (config.admins || []).map((admin) => [
      admin.username,
      admin.is_active ? 'yes' : 'no',
      admin.last_login_at || 'never',
    ]))));

  wrap.append(panel('Change my password', password(api)));

  wrap.append(el('p', { className: 'muted small' },
    'Add or remove an account from a terminal: repo-mcp-admin create-admin '
    + '--username <name> --force, and repo-mcp-admin set-password <name>. '
    + 'A credential that bypasses the directory is handed out by someone with '
    + 'access to the host, not through a browser.'));
  return wrap;
}

function password(api) {
  const value = field({
    label: 'New password', kind: 'password', autocomplete: 'new-password',
    hint: 'At least twelve characters.',
  });
  const repeat = field({ label: 'Repeat', kind: 'password', autocomplete: 'new-password' });
  const error = el('p', { className: 'error', hidden: true });
  const save = el('button', { className: 'primary', textContent: 'Change' });

  save.addEventListener('click', async () => {
    error.hidden = true;
    save.disabled = true;
    try {
      if (value.read() !== repeat.read()) throw new Error('the two passwords do not match');
      await api.call('/password', { method: 'POST', body: { password: value.read() } });
      await api.saved('password changed');
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      save.disabled = false;
    }
  });

  return el('div', { className: 'editor' }, value.wrap, repeat.wrap, error, save);
}
