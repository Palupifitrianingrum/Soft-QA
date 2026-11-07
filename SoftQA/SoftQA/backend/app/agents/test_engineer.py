"""Test Engineer agent: one Gemini call produces test cases + executable pytest functions.
Code is validated (AST allow-list) before it can be approved; execution happens only in the Docker sandbox."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from . import llm
from .reviewer import numbered

SYSTEM = """You are a senior test engineer. Write pytest tests for the given Python project files.
Cover positive, negative, boundary, edge and exception-handling cases.
Each test's 'code' must be a complete snippet: its own import lines, then EXACTLY ONE top-level function named test_*.
Import project code ONLY via the module names provided (e.g. 'from calc import add'). Only these stdlib modules may be
imported: pytest, math, re, json, datetime, decimal, fractions, collections, itertools, functools, typing, string,
random, statistics, copy, dataclasses, enum, operator, textwrap. No file, network, subprocess, eval/exec/open, no dunder attributes.
Tests must be deterministic and contain assertions (use pytest.raises for expected exceptions).
Base expectations on what the code actually does; do not guess unseen behaviour. 'input_json' is a JSON string of the inputs used."""


class AITest(BaseModel):
    test_name: str
    description: str
    test_type: Literal["positive", "negative", "boundary", "edge", "exception"]
    input_json: str
    expected_result: str
    priority: Literal["high", "medium", "low"]
    target_file: str
    code: str


class AITests(BaseModel):
    tests: list[AITest]


def module_name(path: str) -> str:
    p = path[:-3] if path.endswith(".py") else path
    p = p.removesuffix("/__init__")
    return p.replace("/", ".")


def generate(files: list[tuple[str, str]], finding_titles: list[str], max_tests: int = 20) -> list[AITest]:
    parts = [f"### {path}  (import as: {module_name(path)})\n{numbered(src)[:15000]}" for path, src in files]
    ctx = "\n".join(f"- {t}" for t in finding_titles[:15]) or "(none)"
    user = f"Write at most {max_tests} tests.\nKnown analysis findings (may suggest edge cases):\n{ctx}\n\n" + "\n\n".join(parts)
    return llm.parse(AITests, SYSTEM, user).tests[:max_tests]


def parse_input(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text
