/* The answer cache: what is stored, and the button that drops it.
 *
 * Reindexing already retires stale answers by epoch, so purging is for the
 * other case — a prompt or a model change that makes previous answers
 * undesirable rather than merely out of date. See
 * docs/adr/0009-answer-cache.md.
 */

import { el, field, panel, stats, adminFetch } from '../../core.js';

export async function render(config, api) {
  const summary = await (await adminFetch('/answer-cache')).json();
  const wrap = el('div');

  wrap.append(stats([
    ['Entries', summary.entries],
    ['Hits', summary.hits],
    ['Squads', summary.squads?.length ?? 0],
  ]));

  if (!summary.enabled) {
    wrap.append(el('p', { className: 'muted' },
      'The cache is off. Turn it on under Settings — answer_cache.enabled — and '
      + 'set an embedding model there. It stores synthesised knowledge of a '
      + "squad's source, which is a decision to make rather than inherit."));
  }

  wrap.append(panel('Configuration', el('dl', { className: 'facts' },
    el('dt', { textContent: 'Enabled' }), el('dd', { textContent: String(summary.enabled) }),
    el('dt', { textContent: 'Embedding model' }),
    el('dd', { textContent: summary.embedding_model || '(none set)' }),
    el('dt', { textContent: 'Similarity threshold' }),
    el('dd', { textContent: String(summary.similarity_threshold) }),
    el('dt', { textContent: 'Time to live' }),
    el('dd', { textContent: `${summary.ttl_seconds} seconds` }))));

  if (summary.squads?.length) {
    wrap.append(panel('Squads with cached answers',
      el('p', { className: 'mono', textContent: summary.squads.join(', ') })));
  }

  wrap.append(panel('Purge', purge(api)));
  return wrap;
}

function purge(api) {
  const squad = field({ label: 'Squad', placeholder: 'blank for every squad' });
  const project = field({ label: 'Project', placeholder: 'blank for every project' });
  const error = el('p', { className: 'error', hidden: true });
  const button = el('button', { textContent: 'Purge' });

  button.addEventListener('click', async () => {
    const where = [squad.read(), project.read()].filter(Boolean).join(' / ') || 'every squad';
    if (!confirm(`Drop the cached answers for ${where}?`)) return;

    error.hidden = true;
    button.disabled = true;
    try {
      const query = new URLSearchParams();
      if (squad.read()) query.set('tenant', squad.read());
      if (project.read()) query.set('project', project.read());
      const result = await api.call(`/answer-cache?${query}`, { method: 'DELETE' });
      await api.saved(`removed ${result.removed} cached answer(s)`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
      button.disabled = false;
    }
  });

  return el('div', { className: 'editor' }, squad.wrap, project.wrap, error, button);
}
