#!/usr/bin/env python3
"""Render docs/ onto the project site.

The reference documentation is markdown in the repository — that is where it
is written, reviewed and versioned, and it stays there. But reading it meant
going to GitHub, so the site linked out to thirteen files and stopped being
the place the documentation lives. This renders the same files into the site,
in the site's own shell, so one source produces both.

Two things it has to get right:

* **Links.** A document links to its neighbours as `architecture.md` and to
  decisions as `adr/0001-….md`. Those become pages here, so the hrefs are
  rewritten. Anything pointing outside `docs/` — `../AGENTS.md`, a source
  file — cannot become a page and becomes a GitHub link instead.
* **Depth.** `docs/adr/0001-….html` sits one level deeper than
  `docs/architecture.html`, so every asset reference is resolved relative to
  the page rather than assumed.

Called by scripts/build-site.sh; not meant to be run by hand.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import markdown

REPO_BLOB = "https://github.com/emrezdemir/repo-mcp/blob/main"

#: The order the sidebar lists them in, and the short line under each. Written
#: here rather than pulled from the documents themselves because a sidebar
#: wants six words and a first paragraph is never six words.
ORDER: list[tuple[str, str, str]] = [
    ("architecture.md", "Architecture", "Two services, one engine, a shared graph directory"),
    ("web-interface.md", "Web interface", "How it is built, how sign-in works"),
    ("administration.md", "Administration", "The terminal and the console, side by side"),
    ("roles-and-permissions.md", "Roles and permissions", "What a role may do, what a squad may reach"),
    ("deployment.md", "Deployment", "Compose, Kubernetes, Keycloak and LDAP"),
    ("environments.md", "Environments", "Branches produce artifacts, artifacts promote"),
    ("scaling.md", "Scaling", "Replicas, the queue and storage"),
    ("engine.md", "The engine", "What codebase-memory-mcp does, and how it is driven"),
    ("branching.md", "Branching", "Branch names, the merge gate, releases"),
    ("code-standards.md", "Code standards", "What the code is expected to look like"),
    ("development.md", "Development", "Local setup, the tests, the contribution flow"),
    ("roadmap.md", "Roadmap", "What is built, what is designed, what is not"),
]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — repo-mcp</title>
<meta name="description" content="{description}">
<link rel="icon" href="{root}favicon.svg">
<link rel="stylesheet" href="{root}style.css">
</head>
<body>

<header>
  <div class="wrap">
    <a class="brand" href="{root}"><span class="dot"></span> repo-mcp</a>
    <nav class="top">
      <a href="{root}#ne">Ne işe yarar</a>
      <a href="{root}#senaryolar">Senaryolar</a>
      <a href="{root}#kurulum">Kurulum</a>
      <a href="{root}docs/">Belgeler</a>
    </nav>
    <span class="spacer"></span>
    <a class="lang" href="{root}en.html">English</a>
  </div>
</header>

<div class="doc-layout wrap">
  <aside class="doc-nav">
    <p class="eyebrow">Belgeler</p>
    <a href="{root}docs/">Hepsi</a>
{sidebar}
    <p class="eyebrow" style="margin-top:22px">ADR</p>
{adr_nav}
  </aside>
  <main class="doc">
{body}
{source_note}
  </main>
</div>

<footer>
  <div class="wrap">
    <span>MIT · <a href="https://github.com/emrezdemir/repo-mcp">github.com/emrezdemir/repo-mcp</a></span>
    <span class="spacer"></span>
    <span>İndeksleme motoru <a href="https://github.com/DeusData/codebase-memory-mcp">codebase-memory-mcp</a> (MIT).</span>
  </div>
</footer>

</body>
</html>
"""


def adr_title(path: Path) -> str:
    """`0003-rbac-model.md` → `ADR-0003 · Rbac model`, unless it says better."""
    first = path.read_text(encoding="utf-8").lstrip().splitlines()[0]
    if first.startswith("# "):
        return first[2:].strip()
    return path.stem


def rewrite_links(body: str, page_dir: Path, docs: Path, root: str) -> str:
    """Point every href and src at something that exists on the site."""

    def target(raw: str) -> str:
        if raw.startswith(("http://", "https://", "mailto:", "#", "//")):
            return raw
        anchor = ""
        if "#" in raw:
            raw, _, anchor = raw.partition("#")
            anchor = "#" + anchor
        if not raw:
            return anchor
        resolved = (page_dir / raw).resolve()
        try:
            inside = resolved.relative_to(docs.resolve())
        except ValueError:
            # Outside docs/ — a source file, AGENTS.md, NOTICE. There is no
            # page for it here, so send the reader to the repository.
            repo_root = docs.resolve().parent
            try:
                return f"{REPO_BLOB}/{resolved.relative_to(repo_root)}{anchor}"
            except ValueError:
                return raw + anchor
        if inside.suffix == ".md":
            return f"{root}docs/{inside.with_suffix('.html').as_posix()}{anchor}"
        if inside.parts[:1] == ("images",):
            # The site keeps one copy of the screenshots, at its root.
            return f"{root}images/{inside.name}{anchor}"
        return f"{root}docs/{inside.as_posix()}{anchor}"

    return re.sub(
        r'(href|src)="([^"]+)"',
        lambda m: f'{m.group(1)}="{html.escape(target(html.unescape(m.group(2))), quote=True)}"',
        body,
    )


def nav_links(entries: list[tuple[str, str]], root: str, current: str) -> str:
    out = []
    for href, label in entries:
        here = ' class="here"' if href == current else ""
        out.append(f'    <a href="{root}docs/{href}"{here}>{html.escape(label)}</a>')
    return "\n".join(out)


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    docs = repo / "docs"
    out = Path(sys.argv[1]) / "docs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "adr").mkdir(exist_ok=True)

    known = {name for name, _, _ in ORDER}
    stray = sorted(
        p.name for p in docs.glob("*.md") if p.name not in known
    )
    if stray:
        # A new document that nobody added to ORDER would be published with no
        # way to navigate to it, which is the same as not publishing it.
        print(f"error: docs/ has files missing from ORDER in {Path(__file__).name}: "
              f"{', '.join(stray)}", file=sys.stderr)
        return 1

    adrs = sorted(docs.glob("adr/*.md"))
    sidebar_entries = [(name.replace(".md", ".html"), label) for name, label, _ in ORDER]
    adr_entries = [(f"adr/{p.stem}.html", adr_title(p)) for p in adrs]

    renderer = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"]
    )

    pages = [(docs / name, label, blurb) for name, label, blurb in ORDER]
    pages += [(p, adr_title(p), "Architecture decision record") for p in adrs]

    for source, label, blurb in pages:
        rel = source.relative_to(docs)
        depth = len(rel.parts)  # docs/x.md → 1, docs/adr/x.md → 2
        root = "../" * depth
        renderer.reset()
        body = renderer.convert(source.read_text(encoding="utf-8"))
        body = rewrite_links(body, source.parent, docs, root)

        current = rel.with_suffix(".html").as_posix()
        target = out / current
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            PAGE.format(
                title=html.escape(label),
                description=html.escape(blurb),
                root=root,
                sidebar=nav_links(sidebar_entries, root, current),
                adr_nav=nav_links(adr_entries, root, current),
                body=body,
                source_note=(
                    '    <p class="doc-source">Bu sayfa '
                    f'<a href="{REPO_BLOB}/docs/{rel.as_posix()}">docs/{rel.as_posix()}</a> '
                    "dosyasından üretildi; düzeltme için repository'ye pull request "
                    "açabilirsiniz.</p>"
                ),
            ),
            encoding="utf-8",
        )

    index(out, sidebar_entries, adr_entries, ORDER, adrs)
    print(f"  ok rendered {len(pages)} documents into _site/docs/")
    return 0


def index(out: Path, sidebar_entries, adr_entries, order, adrs) -> None:
    """The documentation home: everything, with a line each."""
    rows = "\n".join(
        f'      <a href="{name.replace(".md", ".html")}">'
        f"<strong>{html.escape(label)}</strong><span>{html.escape(blurb)}</span></a>"
        for name, label, blurb in order
    )
    decisions = "\n".join(
        f'      <a href="adr/{p.stem}.html"><strong>{html.escape(adr_title(p))}</strong>'
        f"<span>{html.escape(adr_summary(p))}</span></a>"
        for p in adrs
    )
    body = f"""    <p class="eyebrow">Belgeler</p>
    <h1>Sistemin bütün belgeleri</h1>
    <p>
      Mimarisinden kurulumuna, rollerden ölçeklemeye kadar her şey burada.
      Belgeler repository'deki markdown dosyalarından üretiliyor, yani
      okuduğunuz sayfa çalışan sürümün belgesi. Referans belgeleri İngilizce
      yazıldı; tanıtım sayfaları Türkçe.
    </p>

    <div class="links">
{rows}
    </div>

    <h2 style="margin-top:38px">Kararlar</h2>
    <p>
      Bir kararın neden öyle alındığı, hangi seçeneklerin elendiği ve karşılığında
      neyin kabul edildiği. Bunlar tarihî kayıt: sonradan değişen bir karar
      eskisini silmez, yerine yenisi yazılır.
    </p>

    <div class="links">
{decisions}
    </div>
"""
    (out / "index.html").write_text(
        PAGE.format(
            title="Belgeler",
            description=(
                "repo-mcp'nin bütün belgeleri: mimari, kurulum, yönetim, roller, "
                "ölçekleme ve kararlar."
            ),
            root="../",
            sidebar=nav_links(sidebar_entries, "../", ""),
            adr_nav=nav_links(adr_entries, "../", ""),
            body=body,
            source_note="",
        ),
        encoding="utf-8",
    )


def adr_summary(path: Path) -> str:
    """Status, plus the first line of the decision itself.

    The status alone would put "Accepted" on ten of eleven cards, which tells
    a reader nothing; the decision alone would lose the one that is still only
    proposed. Together they are the two things worth knowing before clicking.
    """
    text = path.read_text(encoding="utf-8")
    status = ""
    match = re.search(r"^-?\s*\*\*Status:\*\*\s*(.+)$", text, re.MULTILINE)
    if match:
        status = match.group(1).strip().rstrip(".")

    decision = ""
    section = re.search(r"^## Decision\s*$(.+?)^## ", text, re.MULTILINE | re.DOTALL)
    if section:
        # The markdown is hard-wrapped, so the first *line* is half a sentence.
        # Join the first paragraph, then take the sentence.
        paragraph: list[str] = []
        for line in section.group(1).strip().splitlines():
            stripped = line.strip().lstrip("*->").strip()
            if not stripped:
                if paragraph:
                    break
                continue
            if stripped.startswith(("#", "|", "```")):
                if paragraph:
                    break
                continue
            paragraph.append(stripped)
        joined = " ".join(paragraph)
        joined = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", joined)
        joined = re.sub(r"[*`]", "", joined).strip()
        # "Wrap." is a fine decision and a useless subtitle, so keep taking
        # sentences until there is enough of one to be worth reading.
        taken: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s", joined):
            taken.append(sentence)
            if len(" ".join(taken)) >= 46:
                break
        decision = " ".join(taken).rstrip(":").strip()

    if not decision:
        return status or "Architecture decision record"
    # A card subtitle that stops mid-clause reads as a bug rather than a
    # summary, so cut on a word and say that it was cut.
    if len(decision) > 96:
        decision = decision[:96].rsplit(" ", 1)[0].rstrip(",;") + "…"
    return f"{status} · {decision}" if status else decision


if __name__ == "__main__":
    raise SystemExit(main())
