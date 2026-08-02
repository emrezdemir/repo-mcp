"""Structured audit log.

`get_code_snippet` and `search_code` return raw source text. Recording who
read what is not a compliance checkbox — it is what makes an incident
investigable afterwards.

One JSON object per line on stdout, so any log shipper can consume it as-is.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field

_logger = logging.getLogger("audit")


@dataclass
class AuditEvent:
    event: str
    principal: str
    tenant: str | None = None
    tool: str | None = None
    project: str | None = None
    outcome: str = "ok"
    reason: str | None = None
    duration_ms: int | None = None
    llm_model: str | None = None
    extra: dict = field(default_factory=dict)


def emit(event: AuditEvent) -> None:
    record = {k: v for k, v in asdict(event).items() if v not in (None, {}, "")}
    record["ts"] = time.time()
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
    print(line, file=sys.stdout, flush=True)
    if event.outcome != "ok":
        _logger.warning("audit %s", line)


class Timer:
    """Context manager exposing elapsed milliseconds as ``.ms``."""

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *_exc) -> None:
        self.ms = int((time.perf_counter() - self._start) * 1000)
