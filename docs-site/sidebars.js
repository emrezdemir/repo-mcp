// @ts-check
// The reading order of the reference documentation. It mirrors the order the
// old renderer used: the documents are read in sequence, not scanned, so the
// sidebar is authored rather than sorted alphabetically. The ADRs follow as a
// group — historical record, newest decisions worth seeing first would be a
// different list, so they stay in number order.

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  reference: [
    'intro',
    'architecture',
    'web-interface',
    'administration',
    'roles-and-permissions',
    'deployment',
    'environments',
    'scaling',
    'engine',
    'branching',
    'code-standards',
    'development',
    'roadmap',
    {
      type: 'category',
      label: 'Decisions (ADR)',
      collapsed: false,
      items: [
        'adr/0001-wrap-dont-fork',
        'adr/0002-tenancy-model',
        'adr/0003-rbac-model',
        'adr/0004-graph-history',
        'adr/0005-storage-topology',
        'adr/0006-configuration-in-the-database',
        'adr/0007-break-glass-administrator',
        'adr/0008-environments-and-promotion',
        'adr/0009-answer-cache',
        'adr/0010-headroom-plugin',
        'adr/0011-adopt-the-upstream-interface',
      ],
    },
  ],
};

module.exports = sidebars;
