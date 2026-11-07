"""REST API. See /docs (Swagger UI) when the server runs."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import sandbox
from .agents import test_engineer
from .agents.evaluator import distribution
from .agents.llm import AIUnavailable, ai_status
from .agents.llm import check as ai_check
from .analyzers import find_tool
from .archive import Limits, UploadError, detect_kind, extract_zip, save_single_file
from .config import settings
from .database import get_db
from .models import AnalysisRun, Finding, Project, TestCase, TestExecution, UploadedFile
from .pipeline import run_pipeline
from .reports import build_report, to_pdf
from .schemas import (AnalysisOptions, AnalysisOut, ApproveIn, FileContent, FindingOut, ProjectDetail, ProjectOut, StatsOut,
                      SystemStatus, TestCaseOut, TestExecutionOut)
from .storage import project_dir, project_src
from .validation import validate_test_code

log = logging.getLogger("aura.api")
router = APIRouter(prefix="/api")
LIMITS = Limits(max_upload_bytes=settings.max_upload_mb * 1024 * 1024)


def _project_out(p: Project) -> dict:
    return dict(id=p.id, name=p.name, kind=p.kind, created_at=p.created_at, file_count=len(p.files), skipped_files=p.skipped_files)


def _analysis_out(a: AnalysisRun) -> AnalysisOut:
    return AnalysisOut(id=a.id, project_id=a.project_id, project_name=a.project.name, status=a.status, stage=a.stage, options=a.options,
                       warnings=a.warnings or [], error=a.error, created_at=a.created_at, started_at=a.started_at,
                       finished_at=a.finished_at, findings_count=len(a.findings))


def _get(db: Session, model, id_, what: str):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{what} {id_} not found")
    return obj


# ---------- system ----------
@router.get("/system/status", response_model=SystemStatus, tags=["system"])
def system_status() -> SystemStatus:
    docker_ok, msg = sandbox.docker_status()
    semgrep_native = find_tool("semgrep") is not None
    ai = ai_status()
    return SystemStatus(ai_configured=ai["configured"], ai_provider=ai["provider"], ai_model=ai["model"], ai_message=ai["message"], ruff_available=find_tool("ruff") is not None,
                        semgrep_available=semgrep_native or docker_ok, semgrep_mode="native" if semgrep_native else "docker" if docker_ok else "unavailable",
                        docker_available=docker_ok, docker_message=msg, sandbox_image_ready=docker_ok and sandbox.image_ready(),
                        max_upload_mb=settings.max_upload_mb)


@router.post("/system/ai-check", tags=["system"])
def ai_connectivity_check() -> dict:
    """Makes ONE tiny real Gemini request (uses a little quota) to prove the key/model/network work."""
    return ai_check()


@router.post("/system/sandbox/build", tags=["system"])
def build_sandbox() -> dict:
    ok, log_tail = sandbox.build_image()
    if not ok:
        raise HTTPException(503, log_tail)
    return {"ok": True}


@router.get("/stats", response_model=StatsOut, tags=["system"])
def stats(db: Session = Depends(get_db)) -> StatsOut:
    findings = db.query(Finding).all()
    recent = db.query(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(8).all()
    return StatsOut(projects=db.query(Project).count(), analyses=db.query(AnalysisRun).count(),
                    bugs_detected=sum(f.category != "security" for f in findings),
                    critical_vulnerabilities=sum(f.category == "security" and f.severity in ("critical", "high") for f in findings),
                    tests_executed=db.query(func.coalesce(func.sum(TestExecution.tests_run), 0)).scalar() or 0,
                    severity_distribution=distribution(findings), recent_analyses=[_analysis_out(a) for a in recent])


# ---------- projects ----------
@router.post("/projects/upload", response_model=ProjectDetail, status_code=201, tags=["projects"])
async def upload_project(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    name = Path(file.filename or "upload").name
    data = await file.read(LIMITS.max_upload_bytes + 1)
    try:
        kind = detect_kind(name, data, LIMITS)
    except UploadError as exc:
        raise HTTPException(413 if "limit" in str(exc) else 400, str(exc)) from exc
    project = Project(name=name, kind=kind)
    db.add(project)
    db.flush()
    try:
        res = save_single_file(name, data, project_src(project.id), LIMITS) if kind == "file" else extract_zip(data, project_src(project.id), LIMITS)
    except UploadError as exc:
        db.rollback()
        shutil.rmtree(project_dir(project.id), ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    project.skipped_files = res.skipped
    db.add_all(UploadedFile(project_id=project.id, path=f.path, language=f.language, size_bytes=f.size_bytes, line_count=f.line_count) for f in res.files)
    db.commit()
    db.refresh(project)
    log.info("project %s uploaded (%s files)", project.id, len(res.files))
    return {**_project_out(project), "files": project.files}


@router.get("/projects", response_model=list[ProjectOut], tags=["projects"])
def list_projects(db: Session = Depends(get_db)) -> list[dict]:
    return [_project_out(p) for p in db.query(Project).order_by(Project.id.desc()).all()]


@router.get("/projects/{project_id}", response_model=ProjectDetail, tags=["projects"])
def get_project(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _get(db, Project, project_id, "Project")
    return {**_project_out(p), "files": p.files}


@router.get("/projects/{project_id}/files/{file_id}", response_model=FileContent, tags=["projects"])
def get_file(project_id: int, file_id: int, db: Session = Depends(get_db)) -> dict:
    f = _get(db, UploadedFile, file_id, "File")
    if f.project_id != project_id:
        raise HTTPException(404, "File not found in this project")
    content = (project_src(project_id) / f.path).read_text(encoding="utf-8", errors="replace")
    return {"id": f.id, "path": f.path, "language": f.language, "size_bytes": f.size_bytes, "line_count": f.line_count, "content": content}


# ---------- analysis ----------
@router.post("/analysis/{project_id}/start", response_model=AnalysisOut, status_code=202, tags=["analysis"])
def start_analysis(project_id: int, bg: BackgroundTasks, opts: AnalysisOptions = AnalysisOptions(), db: Session = Depends(get_db)) -> AnalysisOut:
    _get(db, Project, project_id, "Project")
    a = AnalysisRun(project_id=project_id, options=opts.model_dump())
    db.add(a)
    db.commit()
    bg.add_task(run_pipeline, a.id)
    return _analysis_out(a)


@router.get("/analysis", response_model=list[AnalysisOut], tags=["analysis"])
def list_analyses(project_id: int | None = Query(None), db: Session = Depends(get_db)) -> list[AnalysisOut]:
    q = db.query(AnalysisRun).order_by(AnalysisRun.id.desc())
    if project_id:
        q = q.filter(AnalysisRun.project_id == project_id)
    return [_analysis_out(a) for a in q.limit(100).all()]


@router.get("/analysis/{analysis_id}", response_model=AnalysisOut, tags=["analysis"])
def get_analysis(analysis_id: int, db: Session = Depends(get_db)) -> AnalysisOut:
    return _analysis_out(_get(db, AnalysisRun, analysis_id, "Analysis"))


@router.get("/analysis/{analysis_id}/findings", response_model=list[FindingOut], tags=["analysis"])
def get_findings(analysis_id: int, severity: str | None = None, category: str | None = None, db: Session = Depends(get_db)):
    a = _get(db, AnalysisRun, analysis_id, "Analysis")
    return [f for f in a.findings if (not severity or f.severity == severity) and (not category or f.category == category)]


# ---------- tests ----------
@router.get("/tests/{analysis_id}", response_model=list[TestCaseOut], tags=["tests"])
def list_tests(analysis_id: int, db: Session = Depends(get_db)):
    return _get(db, AnalysisRun, analysis_id, "Analysis").test_cases


@router.post("/tests/{analysis_id}/generate", response_model=list[TestCaseOut], tags=["tests"])
def generate_tests(analysis_id: int, db: Session = Depends(get_db)):
    a = _get(db, AnalysisRun, analysis_id, "Analysis")
    src = project_src(a.project_id)
    py = [(f.path, (src / f.path).read_text(encoding="utf-8")) for f in a.project.files if f.language == "python" and not f.path.split("/")[-1].startswith("test_")]
    if not py:
        raise HTTPException(400, "No Python source files to generate tests for.")
    try:
        ai_tests = test_engineer.generate(py[:8], [f.title for f in a.findings])
    except AIUnavailable as exc:
        raise HTTPException(429 if exc.kind in ("rate_limited", "quota_exceeded") else 503, f"AI test generation unavailable: {exc}") from exc
    modules = {test_engineer.module_name(p).split(".")[0] for p, _ in py}
    db.query(TestCase).filter_by(analysis_id=a.id).delete()
    seen: set[str] = set()
    for i, t in enumerate(ai_tests, 1):
        problems, fn = validate_test_code(t.code, modules)
        if fn and fn in seen:
            problems.append(f"duplicate test function name {fn}")
        seen.add(fn or "")
        db.add(TestCase(analysis_id=a.id, test_id=f"TC-{i:03d}", test_name=t.test_name, description=t.description, test_type=t.test_type,
                        input=test_engineer.parse_input(t.input_json), expected_result=t.expected_result, priority=t.priority,
                        target_file=t.target_file, code=t.code, validation_status="rejected" if problems else "valid",
                        validation_notes=problems))
    db.commit()
    db.refresh(a)
    return a.test_cases


@router.post("/tests/{test_id}/approve", response_model=TestCaseOut, tags=["tests"])
def approve_test(test_id: int, body: ApproveIn = ApproveIn(), db: Session = Depends(get_db)):
    """`test_id` here is the numeric database id of the test case (TestCaseOut.id)."""
    t = _get(db, TestCase, test_id, "Test case")
    if body.approved and t.validation_status != "valid":
        raise HTTPException(400, "Test failed static validation and cannot be approved: " + "; ".join(t.validation_notes))
    t.approved = body.approved
    db.commit()
    return t


@router.post("/tests/{analysis_id}/execute", response_model=TestExecutionOut, tags=["tests"])
def execute_tests(analysis_id: int, db: Session = Depends(get_db)):
    a = _get(db, AnalysisRun, analysis_id, "Analysis")
    approved = [t for t in a.test_cases if t.approved and t.validation_status == "valid"]
    if not approved:
        raise HTTPException(400, "No approved tests. Approve at least one validated test first.")
    # Re-validate right before execution (never trust stored state blindly).
    modules = {test_engineer.module_name(f.path).split(".")[0] for f in a.project.files if f.language == "python"}
    approved = [t for t in approved if not validate_test_code(t.code, modules)[0]]
    code = "\n\n".join(t.code for t in approved)
    try:
        res = sandbox.run_tests(project_src(a.project_id), code)
    except sandbox.SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    row = TestExecution(analysis_id=a.id, status=res.status, tests_run=res.passed + res.failed + res.errors, passed=res.passed, failed=res.failed,
                        errors=res.errors, duration_seconds=res.duration, coverage_percent=res.coverage_percent, coverage_files=res.coverage_files,
                        per_test=res.per_test, stdout=res.stdout, stderr=res.stderr, message=res.message)
    for t in approved:
        fn = (validate_test_code(t.code, modules)[1] or "")
        t.last_result = res.per_test.get(fn)
    db.add(row)
    db.commit()
    return row


@router.get("/tests/{analysis_id}/executions", response_model=list[TestExecutionOut], tags=["tests"])
def list_executions(analysis_id: int, db: Session = Depends(get_db)):
    return _get(db, AnalysisRun, analysis_id, "Analysis").executions


# ---------- reports ----------
@router.get("/reports/{analysis_id}", tags=["reports"])
def get_report(analysis_id: int, db: Session = Depends(get_db)) -> dict:
    return build_report(db, _get(db, AnalysisRun, analysis_id, "Analysis"))


@router.get("/reports/{analysis_id}/export", tags=["reports"])
def export_report(analysis_id: int, format: str = Query("json", pattern="^(json|pdf)$"), db: Session = Depends(get_db)) -> Response:
    report = build_report(db, _get(db, AnalysisRun, analysis_id, "Analysis"))
    fname = f"soft-qa-report-{analysis_id}.{format}"
    if format == "pdf":
        try:
            body, mt = to_pdf(report), "application/pdf"
        except ImportError as exc:
            raise HTTPException(503, "PDF export needs reportlab (pip install reportlab).") from exc
    else:
        body, mt = json.dumps(report, indent=2, default=str).encode(), "application/json"
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
