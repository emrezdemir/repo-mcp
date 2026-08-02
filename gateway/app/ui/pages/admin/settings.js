/* Settings: the tunables, grouped by the thing they tune.
 *
 * The keys are the ones in DEFAULT_SETTINGS; the gateway refuses anything
 * else, so this page cannot invent one. A change reaches both services within
 * one poll of the generation counter — no restart.
 */

import { el, panel, status } from '../../core.js';

const GROUPS = [
  ['Identity', 'oidc.'],
  ['Model access', 'litellm.'],
  ['Smart tools', 'smart_tools.'],
  ['Engine', 'engine.'],
  ['Indexer', 'indexer.'],
  ['Answer cache', 'answer_cache.'],
  ['Prompt compression', 'headroom.'],
];

/* Booleans get a checkbox and numbers get a number box, because a text field
 * that silently accepts "ture" is a support ticket waiting to happen. */
function control(value) {
  if (typeof value === 'boolean') {
    const input = el('input', { type: 'checkbox', checked: value });
    return { input, read: () => input.checked };
  }
  if (typeof value === 'number') {
    const input = el('input', { type: 'number', value: String(value), step: 'any' });
    return { input, read: () => Number(input.value) };
  }
  const input = el('input', { value: typeof value === 'object' ? JSON.stringify(value) : String(value) });
  return {
    input,
    read: () => {
      // A hostname is not JSON and nobody types quotes around one; a list is
      // JSON and typing one should work. Try, then fall back.
      try {
        return JSON.parse(input.value);
      } catch {
        return input.value;
      }
    },
  };
}

export function render(config, api) {
  const wrap = el('div');
  const entries = Object.entries(config.settings).sort();
  const shown = new Set();

  for (const [title, prefix] of GROUPS) {
    const mine = entries.filter(([key]) => key.startsWith(prefix));
    if (!mine.length) continue;
    mine.forEach(([key]) => shown.add(key));
    wrap.append(panel(title, ...mine.map(([key, value]) => row(key, value, api))));
  }

  const rest = entries.filter(([key]) => !shown.has(key));
  if (rest.length) {
    wrap.append(panel('Other', ...rest.map(([key, value]) => row(key, value, api))));
  }
  return wrap;
}

function row(key, value, api) {
  const { input, read } = control(value);
  const save = el('button', { textContent: 'Save' });

  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api.call(`/settings/${encodeURIComponent(key)}`, { body: { value: read() } });
      status(`${key} saved`);
    } catch (error) {
      status(error.message, true);
    }
    save.disabled = false;
  });

  return el('div', { className: 'setting' },
    el('span', { className: 'mono key', textContent: key }), input, save);
}
