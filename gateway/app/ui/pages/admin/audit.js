/* The audit trail for configuration changes.
 *
 * Every mutation records who did it, from a terminal or from this interface —
 * the actor is "cli" for one and the administrator's username for the other.
 * A secret's value is never in here.
 */

import { el, table, adminFetch } from '../../core.js';

export async function render() {
  const wrap = el('div');
  const limit = el('select', {},
    ...[25, 100, 250, 500].map((n) =>
      el('option', { value: String(n), textContent: `${n} entries`, selected: n === 100 })));

  const body = el('div');
  const draw = async () => {
    body.replaceChildren(el('p', { className: 'muted', textContent: 'loading…' }));
    const data = await (await adminFetch(`/audit?limit=${limit.value}`)).json();
    body.replaceChildren(data.entries?.length
      ? table(['When', 'Who', 'What', 'Target', 'Detail'],
          data.entries.map((entry) => [
            entry.at, entry.actor, entry.action, entry.target || '',
            entry.detail ? JSON.stringify(entry.detail) : '',
          ]))
      : el('p', { className: 'muted', textContent: 'Nothing recorded yet.' }));
  };

  limit.addEventListener('change', draw);
  wrap.append(el('div', { className: 'toolbar' }, limit), body);
  await draw();
  return wrap;
}
