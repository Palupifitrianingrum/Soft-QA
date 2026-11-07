"""QA Evaluator: merge/dedupe findings, summarise quality. Deterministic (no LLM call needed)."""
from __future__ import annotations

from ..findings import SEVERITY_ORDER, RawFinding

# INTERNAL HEURISTIC (not an industry standard): score = max(0, 100 - sum(weights)).
# Tool-backed ("confirmed") findings count fully; "potential" findings count half.
SEVERITY_WEIGHT = {"critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0}
SCORE_NOTE = ("Internal heuristic, not an industry-standard metric: 100 minus severity weights "
              "(critical 15, high 8, medium 3, low 1; potential findings count half), floored at 0.")


def _overlap(a: RawFinding, b: RawFinding, pad: int = 1) -> bool:
    return a.file == b.file and a.line_start <= b.line_end + pad and b.line_start <= a.line_end + pad


def merge_findings(raw: list[RawFinding]) -> list[RawFinding]:
    """Merge duplicates. An AI/heuristic finding that overlaps a tool finding of the same category is
    folded into the tool finding (which is already confirmed) and recorded as corroboration."""
    tools = [f for f in raw if f.source in ("ruff", "semgrep")]
    soft = [f for f in raw if f.source not in ("ruff", "semgrep")]
    kept_soft: list[RawFinding] = []
    for f in soft:
        match = next((t for t in tools if t.category == f.category and _overlap(t, f)), None)
        if match:
            if f.source not in match.corroborated_by:
                match.corroborated_by.append(f.source)
            if f.source == "ai" and f.description not in match.description:
                match.description += f"\n\nAI analysis: {f.description}"
            continue
        dup = next((k for k in kept_soft if k.file == f.file and k.category == f.category and _overlap(k, f, 0)
                    and (k.title.lower() == f.title.lower() or k.line_start == f.line_start)), None)
        if dup:
            if f.source not in dup.corroborated_by and f.source != dup.source:
                dup.corroborated_by.append(f.source)
            dup.confidence = max(dup.confidence, f.confidence)
            continue
        kept_soft.append(f)
    # Two different tools reporting the same thing (e.g. ruff + semgrep) -> keep the first.
    out: list[RawFinding] = []
    for t in tools:
        d = next((o for o in out if o.source != t.source and o.category == t.category and _overlap(o, t, 0)
                  and o.line_start == t.line_start), None)
        if d:
            d.corroborated_by.append(t.source)
        else:
            out.append(t)
    out += kept_soft
    return sorted(out, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.file, f.line_start))


def quality_score(findings: list) -> int:
    total = 0.0
    for f in findings:
        w = SEVERITY_WEIGHT.get(f.severity, 0)
        total += w if f.status == "confirmed" else w / 2
    return max(0, round(100 - total))


def distribution(findings: list) -> dict[str, int]:
    d = {k: 0 for k in SEVERITY_ORDER}
    for f in findings:
        d[f.severity] = d.get(f.severity, 0) + 1
    return d


def recommendations(findings: list, executions: list) -> list[str]:
    recs: list[str] = []
    dist = distribution(findings)
    sec = [f for f in findings if f.category == "security"]
    if sec:
        recs.append(f"Address the {len(sec)} security finding(s) first; each is backed by a Semgrep rule match.")
    if dist["critical"] or dist["high"]:
        recs.append(f"Fix {dist['critical']} critical and {dist['high']} high severity finding(s) before release.")
    if any(f.status == "potential" for f in findings):
        recs.append("Manually review 'potential' findings: they come from AI/heuristics and are not confirmed by a tool or test.")
    if executions:
        last = executions[-1]
        if last.failed or last.errors:
            recs.append("Investigate failing generated tests: they may reveal real bugs or be incorrect AI-written tests.")
        if last.coverage_percent is not None and last.coverage_percent < 80:
            recs.append(f"Coverage from generated tests is {last.coverage_percent:.0f}%; add tests for uncovered code.")
    else:
        recs.append("No tests have been executed yet; generate, review, approve and run tests to add runtime evidence.")
    return recs or ["No actionable issues were found by the enabled analyzers."]
