"""Bug Hunter (deterministic part): AST heuristics for common defect patterns.

Results are *potential* findings (pattern matches, not proof) and are also fed to the LLM as hints.
"""
from __future__ import annotations

import ast

from ..findings import RawFinding
from ..validation import snippet


def _f(path, lines, node, title, sev, cat, desc, rec, rule):
    end = getattr(node, "end_lineno", node.lineno) or node.lineno
    return RawFinding("heuristic", title, sev, cat, path, node.lineno, end, desc, snippet(lines, node.lineno, end), rec, 0.5,
                      "potential", rule, True)


def hunt(path: str, source: str) -> list[RawFinding]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        ln = exc.lineno or 1
        lines = source.splitlines()
        return [RawFinding("heuristic", "Syntax error", "high", "runtime", path, ln, ln, f"File does not parse: {exc.msg}",
                           snippet(lines, ln, ln), "Fix the syntax error.", 1.0, "confirmed", "aura.syntax-error", True)]
    lines = source.splitlines()
    out: list[RawFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) \
                and isinstance(node.right, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
            out.append(_f(path, lines, node, "Possible division by zero", "medium", "runtime",
                          "The divisor is a runtime value; if it can be 0 this raises ZeroDivisionError.",
                          "Validate the divisor (or handle ZeroDivisionError) before dividing.", "aura.division-by-variable"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.args.defaults + [x for x in node.args.kw_defaults if x is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    out.append(_f(path, lines, d, "Mutable default argument", "medium", "logic",
                                  "A mutable default is created once and shared between calls.",
                                  "Use None as the default and create the object inside the function.", "aura.mutable-default"))
        elif isinstance(node, ast.ExceptHandler):
            swallow = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if node.type is None or (swallow and isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")):
                out.append(_f(path, lines, node, "Overly broad or silent exception handler", "low", "runtime",
                              "Catching everything (or silently passing) hides real errors.",
                              "Catch specific exceptions and log or re-raise.", "aura.broad-except"))
        elif isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comp, ast.Constant) and comp.value is None:
                    out.append(_f(path, lines, node, "Comparison to None with ==/!=", "low", "logic",
                                  "None should be compared by identity.", "Use 'is None' / 'is not None'.", "aura.eq-none"))
    return out
