// @ts-check
// The repo-mcp documentation site.
//
// The content is not here. It is the English markdown under ../docs, which
// stays the single source (AGENTS.md §8). scripts/sync-docs.mjs copies it into
// ./docs before every build and rewrites the links that point outside docs/ —
// ../AGENTS.md, a source file, NOTICE — into GitHub URLs, because there is no
// page for them here. ./docs is generated and git-ignored.
//
// Served under /repo-mcp/docs/. The landing page (the hand-written site/ in the
// repo root) stays at /repo-mcp/ and is assembled beside this build by
// scripts/build-site.sh; the two are one published artifact.

const { themes } = require('prism-react-renderer');

const LANDING = 'https://emrezdemir.github.io/repo-mcp/';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'repo-mcp',
  tagline: 'Every repository you own, as one code graph.',
  favicon: 'favicon.svg',

  url: 'https://emrezdemir.github.io',
  baseUrl: '/repo-mcp/docs/',

  organizationName: 'emrezdemir',
  projectName: 'repo-mcp',

  // The reference docs cross-link by filename; sync-docs.mjs rewrites anything
  // pointing outside docs/ to an absolute GitHub URL, so a broken page link
  // here is a real mistake worth failing the build on. Anchors and markdown
  // links only warn: a heading renamed without updating a deep link should not
  // block publishing the rest.
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',
  markdown: { hooks: { onBrokenMarkdownLinks: 'warn' } },

  i18n: { defaultLocale: 'en', locales: ['en'] },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          path: 'docs',
          routeBasePath: '/',
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: 'https://github.com/emrezdemir/repo-mcp/edit/dev/docs/',
          breadcrumbs: true,
          // Keep the NNNN- prefix on ADR ids and URLs. Without this Docusaurus
          // strips it — 0011-adopt-… becomes adopt-… — which breaks the sidebar
          // ids and changes the ADR URLs the READMEs and site already point at.
          numberPrefixParser: false,
        },
        blog: false,
        theme: { customCss: require.resolve('./src/css/custom.css') },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: { defaultMode: 'dark', respectPrefersColorScheme: true },
      navbar: {
        title: 'repo-mcp',
        logo: { alt: 'repo-mcp', src: 'favicon.svg', href: LANDING, target: '_self' },
        items: [
          { type: 'docSidebar', sidebarId: 'reference', position: 'left', label: 'Docs' },
          { href: LANDING, label: 'Site', position: 'left', target: '_self' },
          {
            href: 'https://github.com/emrezdemir/repo-mcp',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Architecture', to: '/architecture' },
              { label: 'Deployment', to: '/deployment' },
              { label: 'Roadmap', to: '/roadmap' },
            ],
          },
          {
            title: 'Project',
            items: [
              { label: 'Site', href: LANDING },
              { label: 'GitHub', href: 'https://github.com/emrezdemir/repo-mcp' },
              { label: 'Changelog', href: 'https://github.com/emrezdemir/repo-mcp/blob/main/CHANGELOG.md' },
            ],
          },
        ],
        copyright:
          'MIT · repo-mcp. The indexing engine is codebase-memory-mcp (MIT), wrapped rather than forked.',
      },
      prism: {
        theme: themes.oneDark,
        darkTheme: themes.oneDark,
        additionalLanguages: ['bash', 'json', 'yaml', 'python', 'docker'],
      },
    }),
};

module.exports = config;
