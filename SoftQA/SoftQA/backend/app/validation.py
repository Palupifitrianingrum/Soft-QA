"""Deterministic guards for AI output: line-range / evidence checks and generated-test code validation.

The AST validator is defense in depth only. The Docker sandbox is the real security boundary.
"""
from __future__ import annotations

import ast
import re

ALLOWED_IMPORTS = {
    "pytest", "math", "re", "json", "datetime", "decimal", "fractions", "collections", "itertools", "functools",
    "typing", "string", "random", "statistics", "copy", "dataclasses", "enum", "operator", "textwrap", "unittest",
}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "input", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "breakpoint", "exit", "quit",
}


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def check_range(start, end, total_lines: int) -> tuple[int, int] | None:
    """Return a valid (start, end) or None when the cited lines do not exist in the file."""
    try:
        s, e = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if total_lines < 1 or s < 1 or s > total_lines:
        return None
    return s, max(s, min(e, total_lines))


def evidence_matches(evidence: str, lines: list[str], start: int, end: int, slack: int = 1) -> bool:
    """True if every non-trivial line of the quoted evidence appears in the cited region (+/- slack lines)."""
    region = normalize(" ".join(lines[max(0, start - 1 - slack): min(len(lines), end + slack)]))
    quoted = [normalize(x) for x in evidence.splitlines() if len(normalize(x)) >= 3]
    return bool(quoted) and all(q in region for q in quoted)


def snippet(lines: list[str], start: int, end: int, max_lines: int = 12) -> str:
    return "\n".join(lines[start - 1: min(end, start - 1 + max_lines)])


def validate_test_code(code: str, project_modules: set[str]) -> tuple[list[str], str | None]:
    """Return (problems, test_function_name). Empty problems means the code passed the static checks."""
    if len(code) > 20000:
        return ["test code too long"], None
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg} (line {exc.lineno})"], None
    allowed = ALLOWED_IMPORTS | set(project_modules)
    problems: list[str] = []
    has_assertion = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allowed:
                    problems.append(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level or top not in allowed or any(a.name == "*" for a in node.names):
                problems.append(f"import not allowed: from {'.' * node.level}{node.module or ''} import ...")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"forbidden name: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                problems.append(f"dunder attribute access: {node.attr}")
            if node.attr in ("raises", "approx", "warns"):
                has_assertion = has_assertion or node.attr == "raises"
        elif isinstance(node, ast.Assert):
            has_assertion = True
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    if len(funcs) != 1:
        problems.append("code must define exactly one top-level test_* function")
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            continue
        if isinstance(n, ast.Assign):
            try:
                ast.literal_eval(n.value)
                continue
            except ValueError:
                pass
        problems.append("only imports, literal constants and one test function are allowed at top level")
        break
    if not has_assertion:
        problems.append("test has no assertion or pytest.raises")
    return problems, (funcs[0].name if len(funcs) == 1 else None)
