# Vendored browser libraries

Three files, committed as they are published. They are served from this
platform's own origin, never from a CDN, so the interface works in an
air-gapped installation and no third party is in the request path of a page
that shows source code.

| File | Package | Version | Licence |
| --- | --- | --- | --- |
| `sigma.min.js` | [sigma](https://www.npmjs.com/package/sigma) | 3.0.3 | MIT |
| `graphology.umd.min.js` | [graphology](https://www.npmjs.com/package/graphology) | 0.26.0 | MIT |
| `graphology-library.min.js` | [graphology-library](https://www.npmjs.com/package/graphology-library) | 0.8.0 | MIT |

Sigma renders the graph with WebGL, graphology is the data model, and the
library bundle supplies ForceAtlas2. Licence texts and attribution are in
[NOTICE](../../../../NOTICE).

## Why these are committed rather than installed

Adding a JavaScript package manager would mean a lockfile, a Node stage in the
image, another CI job and a second dependency ecosystem to keep patched — for
three files that change a few times a year. Committing the published bundles
keeps the repository buildable with nothing but Python and Docker.

They are the published UMD builds, unmodified. Nothing here is a fork.

## Updating

```bash
scripts/update-vendor.sh            # check for newer versions
scripts/update-vendor.sh --apply    # download, verify and replace
```

The script records each file's SHA-256 in `checksums.txt` and refuses to
install a download that does not match what the registry served. After
updating, load `/ui`, draw a graph and check that the layout still runs — a
renderer change is the kind of thing no test here would catch.
