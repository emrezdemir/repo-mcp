// Copy ../docs into ./docs for Docusaurus, rewriting the links that cannot be
// pages here.
//
// The reference documentation is the markdown under repo/docs — that is where
// it is written, reviewed and versioned, and it stays there (AGENTS.md §8).
// Docusaurus needs the files inside its own docs folder, so this copies them in
// before every build. ./docs is generated and git-ignored; never edit it.
//
// Two things it has to get right, the same two the previous Python renderer did:
//
//   * Links out of docs/. A document links to a neighbour as `engine.md` and to
//     a decision as `adr/0001-….md`; Docusaurus resolves those itself, so they
//     are left alone. But `../AGENTS.md`, a source file, `NOTICE` — there is no
//     page for them here, so they are rewritten to GitHub URLs.
//   * Images. docs/images is copied in beside the pages so a relative
//     `images/ui-graph.png` in a document still resolves and gets bundled.

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..', '..');
const docsSrc = path.join(repoRoot, 'docs');
const outDir = path.join(scriptDir, '..', 'docs');

const REPO_BLOB = 'https://github.com/emrezdemir/repo-mcp/blob/main';

// The documentation home, served at the docs root. Written on every sync.
const INTRO = `---
slug: /
title: Documentation
sidebar_label: Overview
description: Reference documentation for repo-mcp — architecture, deployment, roles, scaling and the decisions behind them.
---

# repo-mcp documentation

repo-mcp turns a company's repositories into a shared, queryable code graph,
exposed over MCP with LDAP-backed identity and squad-level isolation. This is
the reference documentation: every page is generated from the markdown under
\`docs/\` in the repository, so what you are reading is the running version's own
documentation, not a copy.

## Start here

- **[Architecture](./architecture.md)** — two services, one engine, a shared graph directory.
- **[Deployment](./deployment.md)** — Compose, Kubernetes, Keycloak and LDAP.
- **[Roles and permissions](./roles-and-permissions.md)** — what a role may do, what a squad may reach.
- **[The engine](./engine.md)** — what the indexing engine does, and how it is driven.

## Why it is built this way

The decisions — including the alternatives that were rejected — are recorded as
ADRs, from [wrapping the engine rather than forking it](./adr/0001-wrap-dont-fork.md)
to [adopting the upstream interface](./adr/0011-adopt-the-upstream-interface.md).

The reference documentation is English. The landing pages — the
[project site](https://emrezdemir.github.io/repo-mcp/) and the README — are
Turkish.
`;

/** Point one link target at something that exists on the site. */
function rewriteTarget(raw, mdDir) {
  const trimmed = raw.trim();
  if (
    trimmed === '' ||
    trimmed.startsWith('#') ||
    /^(https?:|mailto:|tel:|\/\/)/.test(trimmed)
  ) {
    return raw;
  }

  // Strip a markdown link title — `](url "Title")` — and the anchor, keeping
  // both to re-attach.
  const [urlPart, ...titleParts] = trimmed.split(/\s+/);
  const title = titleParts.length ? ' ' + titleParts.join(' ') : '';
  const hashIndex = urlPart.indexOf('#');
  const pathPart = hashIndex === -1 ? urlPart : urlPart.slice(0, hashIndex);
  const anchor = hashIndex === -1 ? '' : urlPart.slice(hashIndex);
  if (pathPart === '') {
    return raw; // bare anchor
  }

  const resolved = path.resolve(mdDir, pathPart);
  const relToDocs = path.relative(docsSrc, resolved);
  const insideDocs = relToDocs !== '' && !relToDocs.startsWith('..') && !path.isAbsolute(relToDocs);
  if (insideDocs) {
    // A neighbour page or a copied image — Docusaurus handles it. Leave it.
    return raw;
  }

  // Outside docs/. There is no page here, so send the reader to the repository.
  const relToRepo = path.relative(repoRoot, resolved).split(path.sep).join('/');
  return `${REPO_BLOB}/${relToRepo}${anchor}${title}`;
}

function rewriteLinks(body, mdDir) {
  // Markdown inline links and images: [text](target) and ![alt](target).
  body = body.replace(
    /(!?\[[^\]]*\]\()([^)]+)(\))/g,
    (_m, open, target, close) => `${open}${rewriteTarget(target, mdDir)}${close}`,
  );
  // Any raw HTML the markdown embeds.
  body = body.replace(
    /((?:href|src)=")([^"]+)(")/g,
    (_m, open, target, close) => `${open}${rewriteTarget(target, mdDir)}${close}`,
  );
  return body;
}

async function copyDir(from, to) {
  await fs.mkdir(to, { recursive: true });
  for (const entry of await fs.readdir(from, { withFileTypes: true })) {
    const src = path.join(from, entry.name);
    const dst = path.join(to, entry.name);
    if (entry.isDirectory()) {
      await copyDir(src, dst);
    } else {
      await fs.copyFile(src, dst);
    }
  }
}

async function collectMarkdown(dir, base = dir) {
  const out = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'images') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await collectMarkdown(full, base)));
    } else if (entry.name.endsWith('.md')) {
      out.push(path.relative(base, full));
    }
  }
  return out;
}

/** Every doc id the sidebar references, flattened out of its categories. */
function sidebarDocIds(items, acc = new Set()) {
  for (const item of items) {
    if (typeof item === 'string') acc.add(item);
    else if (item && item.type === 'doc' && item.id) acc.add(item.id);
    else if (item && Array.isArray(item.items)) sidebarDocIds(item.items, acc);
  }
  return acc;
}

/** Fail if a document is not in the sidebar — publishing a page nothing links
 *  to is the same as not publishing it. This is the guarantee the old renderer
 *  gave through its ORDER list. `intro` is generated, so it is exempt. */
async function assertSidebarCoverage(files) {
  const mod = await import(pathToFileURL(path.join(scriptDir, '..', 'sidebars.js')).href);
  const listed = sidebarDocIds(mod.default.reference);
  const orphans = files
    .map((rel) => rel.split(path.sep).join('/').replace(/\.md$/, ''))
    .filter((id) => id !== 'intro' && !listed.has(id));
  if (orphans.length) {
    console.error(
      `error: docs missing from docs-site/sidebars.js: ${orphans.join(', ')}\n` +
        '       add each to the "reference" sidebar, or the page is published with nothing linking to it.',
    );
    process.exit(1);
  }
}

async function main() {
  await fs.rm(outDir, { recursive: true, force: true });
  await fs.mkdir(outDir, { recursive: true });

  // Screenshots, copied in so a relative image link in a document resolves.
  const imagesSrc = path.join(docsSrc, 'images');
  if (await fs.stat(imagesSrc).then((s) => s.isDirectory(), () => false)) {
    await copyDir(imagesSrc, path.join(outDir, 'images'));
  }

  const files = await collectMarkdown(docsSrc);
  await assertSidebarCoverage(files);
  for (const rel of files) {
    const src = path.join(docsSrc, rel);
    const dst = path.join(outDir, rel);
    const body = await fs.readFile(src, 'utf8');
    await fs.mkdir(path.dirname(dst), { recursive: true });
    await fs.writeFile(dst, rewriteLinks(body, path.dirname(src)), 'utf8');
  }

  // The documentation home. routeBasePath is '/', so the docs need a page at
  // the root or /repo-mcp/docs/ is a 404. This is site chrome, not reference
  // content, so it is generated here rather than kept in ../docs.
  await fs.writeFile(path.join(outDir, 'intro.md'), INTRO, 'utf8');

  console.log(`  synced ${files.length} documents into docs-site/docs/`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
