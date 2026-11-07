"""Plain data container passed between analyzers/agents before persistence (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass
class RawFinding:
    source: str  # ai | ruff | semgrep | heuristic
    title: str
    severity: str
    category: str  # logic | runtime | performance | maintainability | security | style
    file: str
    line_start: int
    line_end: int
    description: str
    evidence: str
    recommendation: str
    confidence: float
    status: str  # confirmed (tool-backed) | potential
    rule_id: str | None = None
    evidence_verified: bool = False
    corroborated_by: list[str] = field(default_factory=list)
