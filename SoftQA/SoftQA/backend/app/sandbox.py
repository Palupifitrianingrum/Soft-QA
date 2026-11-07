"""Docker sandbox for running generated pytest tests against untrusted uploaded code.

If Docker is unavailable, execution is DISABLED (SandboxUnavailable) - there is deliberately no host fallback.
Isolation: no network, non-root user, all capabilities dropped, read-only root FS, read-only source/test mounts,
CPU/memory/pids limits and a wall-clock timeout.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings

MARKER = "===AURA_COVERAGE==="
MAX_OUT = 20000


class SandboxUnavailable(Exception):
    pass


@dataclass
class SandboxResult:
    status: str  # completed | timeout | error
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration: float = 0.0
    stdout: str = ""
    stderr: str = ""
    coverage_percent: float | None = None
    coverage_files: dict = field(default_factory=dict)
    per_test: dict = field(default_factory=dict)
    message: str = ""


def docker_status() -> tuple[bool, str]:
    docker = shutil.which("docker")
    if not docker:
        return False, "Docker CLI not found. Install Docker Desktop (Windows) and restart the backend."
    try:
        p = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return False, "Docker did not respond. Is Docker Desktop running?"
    if p.returncode != 0:
        return False, "Docker daemon is not running. Start Docker Desktop and retry."
    return True, f"Docker {p.stdout.strip()}"


def image_ready() -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        return subprocess.run([docker, "image", "inspect", settings.sandbox_image], capture_output=True, timeout=15).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def build_image() -> tuple[bool, str]:
    """Build the sandbox image (needs network once, to pip install pytest/coverage)."""
    ok, reason = docker_status()
    if not ok:
        return False, reason
    p = subprocess.run(["docker", "build", "-t", settings.sandbox_image, str(settings.sandbox_dir)], capture_output=True, text=True, timeout=600)
    return p.returncode == 0, (p.stdout + p.stderr)[-1500:]


def run_tests(src_dir: Path, test_code: str) -> SandboxResult:
    ok, reason = docker_status()
    if not ok:
        raise SandboxUnavailable(f"Test execution is disabled: {reason}")
    if not image_ready():
        built, log = build_image()
        if not built:
            raise SandboxUnavailable(f"Sandbox image '{settings.sandbox_image}' is missing and could not be built: {log}")
    name = f"aura-{uuid.uuid4().hex[:10]}"
    runs = settings.data_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runs) as tmp:
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_generated.py").write_text(test_code, encoding="utf-8")
        inner = (f"python -m coverage run --source=/work/src -m pytest /work/tests -v -p no:cacheprovider --rootdir=/work/tests; "
                 f"echo {MARKER}; python -m coverage json -o - 2>/dev/null")
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--cpus", settings.sandbox_cpus,
               "--memory", settings.sandbox_memory, "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp:rw,size=64m",
               "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "-e", "PYTHONPATH=/work/src", "-e", "COVERAGE_FILE=/tmp/.coverage", "-e", "HOME=/tmp",
               "-v", f"{src_dir.resolve()}:/work/src:ro", "-v", f"{tests_dir.resolve()}:/work/tests:ro",
               "-w", "/tmp", settings.sandbox_image, "sh", "-c", inner]
        start = time.monotonic()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.sandbox_timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            return SandboxResult("timeout", duration=time.monotonic() - start,
                                 message=f"Execution exceeded {settings.sandbox_timeout}s and was killed.")
        duration = time.monotonic() - start
    out, _, cov_raw = p.stdout.partition(MARKER)
    per_test = {m.group(1): m.group(2).lower() for m in re.finditer(r"::(\w+)\s+(PASSED|FAILED|ERROR|SKIPPED)", out)}
    res = SandboxResult("completed", duration=duration, stdout=out[-MAX_OUT:], stderr=p.stderr[-MAX_OUT:], per_test=per_test,
                        passed=sum(v == "passed" for v in per_test.values()), failed=sum(v == "failed" for v in per_test.values()),
                        errors=sum(v == "error" for v in per_test.values()))
    try:
        cov = json.loads(cov_raw.strip())
        res.coverage_percent = float(cov["totals"]["percent_covered"])
        res.coverage_files = {k.removeprefix("/work/src/"): round(v["summary"]["percent_covered"], 1) for k, v in cov.get("files", {}).items()}
    except (ValueError, KeyError):
        res.message = "Coverage data was not produced (tests may have failed to import the project)."
    if not per_test:
        res.status = "error"
        res.message = (res.message + " No test results were parsed; see stdout/stderr.").strip()
    return res
