#!/usr/bin/env bash
#
# Structural checks on the Helm chart that do not need a cluster, and do not
# need helm itself.
#
# CI runs `helm lint` and `helm template`, which is the real gate. This runs
# everywhere — including on a machine that cannot reach get.helm.sh — and
# catches the mistake helm cannot: a template that reads .Values.something
# which no longer exists in values.yaml. That renders as an empty string
# rather than an error, and shows up much later as a pod with a blank
# environment variable.
#
# Usage: scripts/check-chart.sh

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

case "${1:-}" in
  -h|--help) sed -n '2,14p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
esac

CHART="$REPO_ROOT/deploy/helm/repo-mcp"
[[ -d "$CHART" ]] || die "no chart at $CHART"

"$(py_for common)" - "$CHART" <<'PY'
import re
import sys
from pathlib import Path

import yaml

chart = Path(sys.argv[1])
values = yaml.safe_load((chart / "values.yaml").read_text()) or {}
problems: list[str] = []


MISSING = object()


def at(path: str) -> object:
    """The value at a dotted path in values.yaml, or MISSING."""
    node = values
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


def defined(path: str) -> bool:
    """Is this dotted path present in values.yaml?

    A key whose value is empty still counts: `tag: ""` is a deliberate empty
    default, not a missing key.
    """
    return at(path) is not MISSING


# Paths the chart reads from a scope other than the root ($.Values), or that a
# range/with block rebinds. Listing them is cheaper than parsing Go templates.
SCOPED = {"image.pullSecrets"}

templates = sorted((chart / "templates").glob("*"))
if not templates:
    problems.append("templates/ is empty")

for template in templates:
    text = template.read_text()
    name = f"templates/{template.name}"

    for match in re.finditer(r"\.Values\.([A-Za-z0-9_.]+)", text):
        path = match.group(1).rstrip(".")
        if path in SCOPED or defined(path):
            continue
        line = text[: match.start()].count("\n") + 1
        problems.append(f"{name}:{line}: .Values.{path} is not in values.yaml")

    opens = len(re.findall(r"{{-?\s*(if|range|with|define|block)\b", text))
    closes = len(re.findall(r"{{-?\s*end\s*-?}}", text))
    if opens != closes:
        problems.append(f"{name}: {opens} block(s) opened, {closes} closed")

# Every example must be a subset of values.yaml: an example that sets a key the
# chart does not read is a silent no-op, which is worse than a typo.
for example in sorted((chart.parent).glob("values-*.example.yaml")):
    override = yaml.safe_load(example.read_text()) or {}

    def walk(node: object, prefix: str = "") -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            path = f"{prefix}{key}"
            target = at(path)
            if target is MISSING:
                problems.append(f"{example.name}: sets {path}, which values.yaml does not define")
                continue
            # An empty map in values.yaml is a free-form hole — annotations,
            # labels, nodeSelector. Its keys are the user's, not the chart's.
            if isinstance(target, dict) and target:
                walk(value, f"{path}.")

    walk(override)

if problems:
    for problem in problems:
        print(f"  {problem}")
    print(f"\n{len(problems)} problem(s) in the chart")
    raise SystemExit(1)

print(f"  {len(templates)} template(s), values.yaml consistent")
PY

ok "the Helm chart is structurally consistent"
