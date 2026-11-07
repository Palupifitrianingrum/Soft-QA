"""QA report assembly (JSON) and PDF rendering."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from .agents.evaluator import SCORE_NOTE, distribution, quality_score, recommendations
from .models import AnalysisRun, QAReport
from .schemas import FindingOut, TestCaseOut, TestExecutionOut


def build_report(db: Session, a: AnalysisRun) -> dict:
    findings = sorted(a.findings, key=lambda f: ("critical high medium low info".split().index(f.severity), f.file, f.line_start))
    fdicts = [FindingOut.model_validate(f).model_dump() for f in findings]
    execs = list(a.executions)
    last = execs[-1] if execs else None
    cases = a.test_cases
    py = [f for f in a.project.files if f.language == "python"]
    ai_used = bool(a.options.get("use_ai")) and not any("AI" in w and "unavailable" in w.lower() for w in a.warnings)
    dist = distribution(findings)
    conf = sum(f.status == "confirmed" for f in findings)
    summary = (f"{len(findings)} finding(s) across {len(py)} Python file(s): {conf} tool-confirmed and {len(findings) - conf} potential "
               f"(AI/heuristic, unconfirmed). Severity: " + ", ".join(f"{v} {k}" for k, v in dist.items() if v) + "." if findings
               else f"No findings were reported across {len(py)} Python file(s) by the enabled analyzers (this is not proof of correctness).")
    data = {
        "analysis_id": a.id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_started_at": a.started_at.isoformat() if a.started_at else None,
        "analysis_finished_at": a.finished_at.isoformat() if a.finished_at else None,
        "status": a.status,
        "project": {"id": a.project.id, "name": a.project.name, "kind": a.project.kind},
        "overview": {"files_total": len(a.project.files), "python_files": len(py),
                     "total_lines": sum(f.line_count for f in a.project.files), "skipped_files": a.project.skipped_files},
        "options": a.options,
        "warnings": a.warnings,
        "ai_used": ai_used,
        "findings_total": len(findings),
        "confirmed_count": conf,
        "potential_count": len(findings) - conf,
        "severity_distribution": dist,
        "security_findings": [f for f in fdicts if f["category"] == "security"],
        "findings": fdicts,
        "tests": {
            "generated": len(cases), "approved": sum(c.approved for c in cases),
            "rejected_by_validation": sum(c.validation_status != "valid" for c in cases),
            "cases": [TestCaseOut.model_validate(c).model_dump() for c in cases],
            "latest_execution": TestExecutionOut.model_validate(last).model_dump(mode="json") if last else None,
        },
        "quality": {"score": quality_score(findings), "note": SCORE_NOTE},
        "summary": summary,
        "recommendations": recommendations(findings, execs),
    }
    row = db.query(QAReport).filter_by(analysis_id=a.id).one_or_none()
    if row:
        row.data = data
    else:
        db.add(QAReport(analysis_id=a.id, data=data))
    db.commit()
    return data


def to_pdf(r: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    p = lambda t, s="BodyText": Paragraph(escape(str(t)), st[s])  # noqa: E731 - all text escaped
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"SOFT QA report #{r['analysis_id']}")
    ov, t = r["overview"], r["tests"]
    s = [p(f"SOFT QA Report - {r['project']['name']}", "Title"), p(f"Generated: {r['generated_at']}  |  Analysis #{r['analysis_id']}"),
         Spacer(1, 10), p("Overview", "Heading2"),
         p(f"Files: {ov['files_total']} ({ov['python_files']} Python), lines: {ov['total_lines']}. AI used: {r['ai_used']}."),
         p(r["summary"]), p(f"Quality score {r['quality']['score']}/100. {r['quality']['note']}"),
         p("Severity distribution", "Heading2"),
         Table([["Severity", "Count"]] + [[k, v] for k, v in r["severity_distribution"].items()],
               style=TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)])),
         p("Tests", "Heading2")]
    ex = t["latest_execution"]
    s.append(p(f"Generated: {t['generated']}, approved: {t['approved']}, rejected by validation: {t['rejected_by_validation']}. " +
               (f"Last run: {ex['passed']} passed, {ex['failed']} failed, {ex['errors']} errors, coverage "
                f"{'n/a' if ex['coverage_percent'] is None else format(ex['coverage_percent'], '.1f') + '%'}." if ex else "No test execution yet.")))
    s.append(p("Recommendations", "Heading2"))
    s += [p(f"- {x}") for x in r["recommendations"]]
    if r["warnings"]:
        s.append(p("Limitations / warnings", "Heading2"))
        s += [p(f"- {w}") for w in r["warnings"]]
    s.append(p(f"Security findings ({len(r['security_findings'])})", "Heading2"))
    for f in r["security_findings"][:50]:
        s += [p(f"[{f['severity']}] {f['title']} - {f['file']}:{f['line_start']} (rule {f['rule_id']})", "Heading4"), p(f["recommendation"])]
    s.append(p(f"All findings ({r['findings_total']})", "Heading2"))
    for f in r["findings"][:150]:
        s += [p(f"[{f['severity']}/{f['status']}] {f['title']} - {f['file']}:{f['line_start']}-{f['line_end']} ({f['source']})", "Heading4"),
              p(f["description"][:600]), p(f"Fix: {f['recommendation'][:300]}")]
    doc.build(s)
    return buf.getvalue()
