"""Code Reviewer + Bug Hunter (LLM part): ONE call per file. Deterministic hints from Ruff/AST are
included as context; every returned finding is validated against the real source before being kept."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..findings import RawFinding
from ..validation import check_range, evidence_matches, snippet
from . import llm

MAX_CHARS = 30000

SYSTEM = """You are a senior code reviewer and bug hunter. Review the given Python file.
Look for: logic errors, runtime errors, missing exception handling, wrong conditions, None handling,
unhandled edge cases, boundary problems, division by zero, missing validation, wrong loop conditions,
performance concerns and maintainability problems. Do NOT report security vulnerabilities (a separate scanner does).
Rules: cite exact line numbers from the numbered listing; 'evidence' must quote the cited source lines verbatim;
never invent code that is not shown; if you lack evidence, report nothing for it and say so in
'insufficient_evidence'. Confidence is 0-1. Prefer few, precise findings over many speculative ones."""


class AIFinding(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: Literal["logic", "runtime", "performance", "maintainability"]
    line_start: int
    line_end: int
    description: str
    evidence: str
    recommendation: str
    confidence: float


class AIReview(BaseModel):
    findings: list[AIFinding]
    insufficient_evidence: str


def numbered(source: str) -> str:
    return "\n".join(f"{i:>4}| {line}" for i, line in enumerate(source.splitlines(), 1))


def review_file(path: str, source: str, hints: list[RawFinding]) -> tuple[list[RawFinding], int, str]:
    """Returns (findings, number_dropped_for_invalid_lines, model_note). May raise llm.AIUnavailable."""
    lines = source.splitlines()
    listing = numbered(source)[:MAX_CHARS]
    hint_text = "\n".join(f"- line {h.line_start}: [{h.source}] {h.title}" for h in hints[:30]) or "(none)"
    user = f"File: {path}\n\nAutomated hints (unverified, may be false positives):\n{hint_text}\n\nSource:\n{listing}"
    result = llm.parse(AIReview, SYSTEM, user)
    out, dropped = [], 0
    for f in result.findings:
        rng = check_range(f.line_start, f.line_end, len(lines))
        if rng is None:  # fabricated / impossible line numbers are discarded
            dropped += 1
            continue
        s, e = rng
        verified = evidence_matches(f.evidence, lines, s, e)
        conf = max(0.0, min(1.0, f.confidence))
        desc = f.description
        if not verified:
            conf = min(conf, 0.4)
            desc += "\n\n[Note: the quoted evidence could not be matched to the cited lines; treat with extra caution.]"
        out.append(RawFinding("ai", f.title, f.severity, f.category, path, s, e, desc, snippet(lines, s, e),
                              f.recommendation, conf, "potential", None, verified))
    return out, dropped, result.insufficient_evidence
