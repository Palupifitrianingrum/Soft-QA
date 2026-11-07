"""SQLAlchemy 2.0 models. Only portable types (JSON, Text, ...) so PostgreSQL migration is straightforward."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))  # "file" | "zip"
    skipped_files: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    files: Mapped[list["UploadedFile"]] = relationship(cascade="all, delete-orphan", order_by="UploadedFile.path")
    analyses: Mapped[list["AnalysisRun"]] = relationship(cascade="all, delete-orphan")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer)
    line_count: Mapped[int] = mapped_column(Integer)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|completed|failed
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    project: Mapped[Project] = relationship(back_populates="analyses")
    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan")
    test_cases: Mapped[list["TestCase"]] = relationship(cascade="all, delete-orphan", order_by="TestCase.id")
    executions: Mapped[list["TestExecution"]] = relationship(cascade="all, delete-orphan", order_by="TestExecution.id")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    source: Mapped[str] = mapped_column(String(24))  # ai | ruff | semgrep | heuristic
    title: Mapped[str] = mapped_column(String(512))
    severity: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    file: Mapped[str] = mapped_column(String(1024))
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))  # confirmed (tool-backed) | potential
    rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    corroborated_by: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False  # not a pytest class
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    test_id: Mapped[str] = mapped_column(String(16))
    test_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    test_type: Mapped[str] = mapped_column(String(16))
    input: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    expected_result: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(8))
    target_file: Mapped[str] = mapped_column(String(1024), default="")
    code: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(16))  # valid | rejected
    validation_notes: Mapped[list] = mapped_column(JSON, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    last_result: Mapped[str | None] = mapped_column(String(16), nullable=True)  # passed|failed|error|skipped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestExecution(Base):
    __tablename__ = "test_executions"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # completed | timeout | error
    tests_run: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    coverage_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_files: Mapped[dict] = mapped_column(JSON, default=dict)
    per_test: Mapped[dict] = mapped_column(JSON, default=dict)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QAReport(Base):
    __tablename__ = "qa_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
