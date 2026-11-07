"""Deterministic analyzers: Ruff and Semgrep. They only PARSE uploaded code (never import/execute it).

Each runner returns (findings, warning). A missing tool yields a warning, never a silent skip.
JavaScript: add an `eslint` runner and register it in ANALYZERS_BY_LANGUAGE (see README roadmap).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import settings
from .findings import RawFinding
from .validation import snippet

RUFF_SELECT = "E,F,B,SIM"
SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
REMEDIATION = [
    (("sql",), "Use parameterized queries / bound parameters instead of building SQL with string formatting."),
    (("subprocess", "shell", "command", "os-system", "os.system"), "Avoid shell=True; pass an argument list and validate or allow-list all input."),
    (("pickle", "deserial", "yaml.load", "marshal"), "Never deserialize untrusted data; use JSON or yaml.safe_load."),
    (("secret", "password", "token", "credential", "api-key", "hardcoded"), "Remove the secret from source, rotate it, and load it from environment variables or a secret manager."),
    (("eval", "exec"), "Do not evaluate dynamic code; use ast.literal_eval or explicit parsing."),
    (("path", "traversal", "tempfile"), "Validate/normalise file paths and use secure temp-file APIs."),
]


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for cand in (Path(sys.executable).parent / name, Path(sys.executable).parent / f"{name}.exe", Path(sys.executable).parent / "Scripts" / f"{name}.exe"):
        if cand.exists():
            return str(cand)
    return None


def _read_lines(src: Path, rel: str) -> list[str]:
    try:
        return (src / rel).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _rel(path: str, src: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(src.resolve()).as_posix()
        except ValueError:
            return p.name
    return p.as_posix().removeprefix("./")


def run_ruff(src: Path) -> tuple[list[RawFinding], str | None]:
    exe = find_tool("ruff")
    if not exe:
        return [], "Ruff is not installed (pip install ruff); lint results are missing."
    try:
        p = subprocess.run([exe, "check", "--isolated", "--output-format", "json", "--select", RUFF_SELECT, "--no-cache", "."],
                           cwd=src, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [], f"Ruff failed to run: {exc}"
    if p.returncode not in (0, 1):
        return [], f"Ruff error: {p.stderr.strip()[:300]}"
    try:
        items = json.loads(p.stdout or "[]")
    except json.JSONDecodeError:
        return [], "Ruff produced unreadable output."
    out: list[RawFinding] = []
    for it in items:
        code, rel = it.get("code") or "ruff", _rel(it.get("filename", ""), src)
        s, e = it["location"]["row"], it.get("end_location", it["location"])["row"]
        lines = _read_lines(src, rel)
        sev = "high" if code.startswith("E9") or code == "F821" else "medium" if code.startswith(("F", "B")) else "low"
        cat = "runtime" if code.startswith(("F", "E9")) else "logic" if code.startswith("B") else "maintainability"
        out.append(RawFinding("ruff", f"{code}: {it.get('message', '')}", sev, cat, rel, s, max(s, e), it.get("message", ""),
                              snippet(lines, s, max(s, e)), (it.get("url") or "See the Ruff rule documentation."), 0.9, "confirmed", code, True))
    return out, None


def _semgrep_cmd(src: Path, registry: bool) -> tuple[list[str], dict] | None:
    base = ["scan", "--json", "--metrics", "off", "--quiet", "--disable-version-check"]
    exe = find_tool("semgrep")
    if exe:
        cfg = ["--config", str(settings.rules_dir)] + [x for r in (settings.semgrep_registry if registry else ()) for x in ("--config", r)]
        return [exe, *base, *cfg, "."], {"cwd": src}
    docker = shutil.which("docker")
    if docker:  # fallback: official image, source mounted read-only
        cfg = ["--config", "/rules"] + [x for r in (settings.semgrep_registry if registry else ()) for x in ("--config", r)]
        return [docker, "run", "--rm", "-v", f"{src.resolve()}:/src:ro", "-v", f"{settings.rules_dir.resolve()}:/rules:ro",
                "-w", "/src", "semgrep/semgrep", "semgrep", *base, *cfg, "."], {}
    return None


def _remediation(rule_id: str, meta: dict) -> str:
    if meta.get("fix"):
        return str(meta["fix"])
    low = rule_id.lower()
    for keys, text in REMEDIATION:
        if any(k in low for k in keys):
            return text
    return "Review the flagged code against the referenced rule and apply the recommended secure alternative."


def run_semgrep(src: Path) -> tuple[list[RawFinding], str | None]:
    warning = None
    for registry in (True, False):  # registry rulesets need network; fall back to bundled local rules
        built = _semgrep_cmd(src, registry)
        if not built:
            return [], "Semgrep is unavailable (not installed natively and Docker not found); security findings are missing."
        cmd, kw = built
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)
        except (subprocess.TimeoutExpired, OSError) as exc:
            warning = f"Semgrep failed to run: {exc}"
            continue
        if p.returncode not in (0, 1) or not p.stdout.strip():
            warning = f"Semgrep error ({'registry+local' if registry else 'local rules only'}): {(p.stderr or p.stdout).strip()[:300]}"
            continue
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            warning = "Semgrep produced unreadable output."
            continue
        out: list[RawFinding] = []
        for r in data.get("results", []):
            extra, meta = r.get("extra", {}), r.get("extra", {}).get("metadata", {}) or {}
            rel = _rel(r.get("path", ""), src)
            s, e = r["start"]["line"], r["end"]["line"]
            rule = r.get("check_id", "semgrep")
            lines = _read_lines(src, rel)
            refs = ", ".join(str(x) for x in (meta.get("cwe") if isinstance(meta.get("cwe"), list) else [meta.get("cwe")]) if x)
            out.append(RawFinding("semgrep", rule.split(".")[-1].replace("-", " ").capitalize(), SEVERITY_MAP.get(extra.get("severity", "WARNING"), "medium"),
                                  "security", rel, s, max(s, e), extra.get("message", "") + (f"\nReferences: {refs}" if refs else ""),
                                  snippet(lines, s, max(s, e)), _remediation(rule, meta), 0.85, "confirmed", rule, True))
        if registry:
            return out, None
        return out, "Semgrep registry rulesets were unavailable" + (f" ({warning})" if warning else "") + "; used bundled local rules only."
    return [], warning


ANALYZERS_BY_LANGUAGE = {"python": ("ruff", "semgrep")}  # extend: "javascript": ("eslint", "semgrep")
