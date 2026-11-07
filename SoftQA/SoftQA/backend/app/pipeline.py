"""Analysis workflow: static analysis -> bug hunter -> security -> AI review -> evaluation.
Runs in a FastAPI background task with its own DB session. Tool failures become warnings, not crashes."""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from .agents import bug_hunter, reviewer
from .agents.evaluator import merge_findings
from .agents.llm import AIUnavailable
from .analyzers import run_ruff, run_semgrep
from .database import SessionLocal
from .models import AnalysisRun, Finding
from .storage import project_src

log = logging.getLogger("aura.pipeline")


def run_pipeline(analysis_id: int) -> None:
    db = SessionLocal()
    a = db.get(AnalysisRun, analysis_id)
    if a is None:
        return
    try:
        a.status, a.started_at = "running", datetime.now(timezone.utc)
        db.commit()
        opts, warnings, raw = a.options, [], []
        src = project_src(a.project_id)
        py = [f for f in a.project.files if f.language == "python"]
        if not py:
            warnings.append("No Python files in this project; only Python analysis is implemented (JS analyzers are on the roadmap).")

        def stage(name: str) -> None:
            a.stage = name
            db.commit()

        if opts.get("run_ruff", True) and py:
            stage("static analysis (ruff)")
            found, warn = run_ruff(src)
            raw += found
            warnings += [warn] if warn else []
        stage("bug hunter (AST heuristics)")
        sources = {f.path: (src / f.path).read_text(encoding="utf-8") for f in py}
        for path, text in sources.items():
            raw += bug_hunter.hunt(path, text)
        if opts.get("run_semgrep", True) and py:
            stage("security analysis (semgrep)")
            found, warn = run_semgrep(src)
            raw += found
            warnings += [warn] if warn else []
        if opts.get("use_ai", True) and py:
            stage("AI code review")
            dropped = 0
            try:
                for path in list(sources)[: int(opts.get("max_ai_files", 15))]:
                    found, d, _note = reviewer.review_file(path, sources[path], [r for r in raw if r.file == path])
                    raw += found
                    dropped += d
                if len(sources) > int(opts.get("max_ai_files", 15)):
                    warnings.append(f"AI review covered only the first {opts.get('max_ai_files', 15)} of {len(sources)} Python files.")
                if dropped:
                    warnings.append(f"{dropped} AI finding(s) were discarded because their line numbers did not exist in the source.")
            except AIUnavailable as exc:
                warnings.append(f"AI analysis unavailable: {exc}")
        elif not opts.get("use_ai", True):
            warnings.append("AI analysis was disabled for this run.")
        stage("evaluation")
        for f in merge_findings(raw):
            db.add(Finding(analysis_id=a.id, **asdict(f)))
        a.warnings, a.status, a.stage = warnings, "completed", "done"
    except Exception as exc:  # noqa: BLE001 - surface any failure on the run record
        log.exception("analysis %s failed", analysis_id)
        db.rollback()
        a = db.get(AnalysisRun, analysis_id)
        a.status, a.error, a.stage = "failed", f"{type(exc).__name__}: {exc}", "failed"
    finally:
        a.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()
