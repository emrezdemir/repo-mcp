"""LLM-backed composite tools.

The raw CBM tools are proxied unchanged; these exist only where synthesis is
genuinely needed. Each one runs the deterministic graph query first and hands
the result to the model — the model is never asked to guess the graph.
"""

from __future__ import annotations

import json

from .cbm import CbmSession
from .llm import LlmClient
from .tenants import Tenant

SMART_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "explain_change_impact",
        "description": (
            "Compute the blast radius of a change and explain it in prose. "
            "Runs detect_changes to find the affected symbols, then summarises "
            "the risk. Suitable for generating pull request comments."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Indexed project name"},
                "base_branch": {"type": "string", "default": "main"},
                "depth": {"type": "integer", "default": 2},
                "direction": {
                    "type": "string",
                    "enum": ["inbound", "outbound", "both"],
                    "default": "inbound",
                },
            },
            "required": ["project"],
        },
    },
    {
        "name": "ask_codebase",
        "description": (
            "Answer a natural-language question about a codebase. Gathers "
            "evidence from the knowledge graph and answers with references to "
            "concrete symbols."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["project", "question"],
        },
    },
]

SMART_TOOL_NAMES = frozenset(t["name"] for t in SMART_TOOL_DEFINITIONS)

#: Underlying CBM tools each composite tool depends on. A tenant that cannot
#: call the primitives cannot reach them through the composite tool either.
SMART_TOOL_REQUIREMENTS: dict[str, frozenset[str]] = {
    "explain_change_impact": frozenset({"detect_changes"}),
    "ask_codebase": frozenset({"search_graph", "get_architecture"}),
}

_IMPACT_SYSTEM = (
    "You are a senior software architect. You are given the graph-computed "
    "impact set of a change. Rely only on the supplied data; never invent "
    "files, functions or risks that are not present. Answer with: (1) a "
    "one-sentence summary, (2) the three to five riskiest affected areas and "
    "why, (3) what should be tested. Be concise."
)

_ASK_SYSTEM = (
    "You are a codebase assistant. You are given graph evidence collected to "
    "answer a question. Answer only from that evidence. If it is insufficient, "
    "say so plainly and state which additional query would help. Cite the "
    "qualified name of every symbol you mention."
)


async def explain_change_impact(
    *, session: CbmSession, llm: LlmClient, tenant: Tenant, username: str, args: dict
) -> str:
    changes = await session.call_tool(
        "detect_changes",
        {
            "project": args["project"],
            "scope": "impact",
            "direction": args.get("direction", "inbound"),
            "depth": args.get("depth", 2),
            "base_branch": args.get("base_branch", "main"),
            "format": "json",
        },
    )
    if changes.is_error:
        return f"detect_changes failed:\n{changes.text()}"

    evidence = changes.text()
    if not evidence.strip():
        return "No changes detected."

    return await llm.complete(
        tenant=tenant,
        username=username,
        system=_IMPACT_SYSTEM,
        user=f"Project: {args['project']}\n\nImpact set:\n{_clip(evidence)}",
    )


async def ask_codebase(
    *, session: CbmSession, llm: LlmClient, tenant: Tenant, username: str, args: dict
) -> str:
    project = args["project"]
    question = args["question"]

    architecture = await session.call_tool("get_architecture", {"project": project})
    search = await session.call_tool(
        "search_graph", {"project": project, "query": question, "limit": 25}
    )

    evidence = json.dumps(
        {
            "architecture": _clip(architecture.text(), 8000),
            "search_results": _clip(search.text(), 12000),
        },
        ensure_ascii=False,
    )
    return await llm.complete(
        tenant=tenant,
        username=username,
        system=_ASK_SYSTEM,
        user=f"Question: {question}\nProject: {project}\n\nEvidence:\n{evidence}",
        max_tokens=2000,
    )


HANDLERS = {
    "explain_change_impact": explain_change_impact,
    "ask_codebase": ask_codebase,
}


def _clip(text: str, limit: int = 20000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} characters truncated]"
