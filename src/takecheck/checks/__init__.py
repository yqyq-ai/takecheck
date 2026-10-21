"""Individual checks. Each check inspects one aspect of a take."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"


@dataclass
class CheckResult:
    """Outcome of a single check."""

    name: str
    status: str
    detail: str
    measured: dict[str, Any] = field(default_factory=dict)
