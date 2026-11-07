"""API response/request schemas. The frontend's src/types.ts mirrors these field names exactly."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class FileOut(ORM):
    id: int
    path: str
    language: str
    size_bytes: int
    line_count: int


class FileContent(FileOut):
    content: str


class ProjectOut(BaseModel):
    id: int
    name: str
    kind: str
    created_at: datetime
    file_count: int
    skipped_files: int


class ProjectDetail(ProjectOut):
    files: list[FileOut]


class AnalysisOptions(BaseModel):
    use_ai: bool = True
    run_ruff: bool = True
    run_semgrep: bool = True
    max_ai_files: int = 15


class AnalysisOut(BaseModel):
    id: int
    project_id: int
    project_name: str
    status: str
    stage: str
    options: dict[str, Any]
    warnings: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    findings_count: int


class FindingOut(ORM):
    id: str
    source: str
    title: str
    severity: str
    category: str
    file: str
    line_start: int
    line_end: int
    description: str
    evidence: str
    recommendation: str
    confidence: float
    status: str
    rule_id: str | None
    evidence_verified: bool
    corroborated_by: list[str]


class TestCaseOut(ORM):
    id: int
    test_id: str
    test_name: str
    description: str
    test_type: str
    input: Any = None
    expected_result: str
    priority: str
    target_file: str
    code: str
    validation_status: str
    validation_notes: list[str]
    approved: bool
    last_result: str | None


class ApproveIn(BaseModel):
    approved: bool = True


class TestExecutionOut(ORM):
    id: int
    analysis_id: int
    status: str
    tests_run: int
    passed: int
    failed: int
    errors: int
    duration_seconds: float
    coverage_percent: float | None
    coverage_files: dict[str, Any]
    per_test: dict[str, Any]
    stdout: str
    stderr: str
    message: str
    created_at: datetime


class SystemStatus(BaseModel):
    ai_configured: bool
    ai_provider: str
    ai_message: str
    ai_model: str
    ruff_available: bool
    semgrep_available: bool
    semgrep_mode: str
    docker_available: bool
    docker_message: str
    sandbox_image_ready: bool
    max_upload_mb: int


class StatsOut(BaseModel):
    projects: int
    analyses: int
    bugs_detected: int
    critical_vulnerabilities: int
    tests_executed: int
    severity_distribution: dict[str, int]
    recent_analyses: list[AnalysisOut]
