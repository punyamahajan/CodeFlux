"""Verify that a workspace written by models actually works.

Four checks, cheapest first: every Python file must compile, no name may be used
without being defined or imported, the unittest suite must pass, and every
Streamlit script must render headlessly without raising.
The last two execute model-written code, so they run in a subprocess inside the
workspace with a time limit.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 180  # acceptance tests start the app several times


def is_test_file(path: Path) -> bool:
    # Models name tests both test_x.py and x_test.py; unittest's default pattern finds only the first.
    return path.name.startswith("test") or path.stem.endswith("_test")
MAX_OUTPUT_CHARS = 3000
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}

SMOKE_SCRIPT = """
import os, sys
sys.path.insert(0, os.getcwd())  # -I drops the workspace from the path; apps import siblings
from streamlit.testing.v1 import AppTest
app = AppTest.from_file(sys.argv[1], default_timeout=30).run()
for error in app.exception:
    print(error.message)
    print("\\n".join(error.stack_trace[-8:]))
sys.exit(1 if app.exception else 0)
"""


def python_files(workspace: Path) -> list[Path]:
    return sorted(
        path for path in workspace.rglob("*.py")
        if not SKIP_DIRS.intersection(path.relative_to(workspace).parts)
    )


def _tail(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_OUTPUT_CHARS else "…" + text[-MAX_OUTPUT_CHARS:]


def _run(args: list[str], workspace: Path) -> tuple[bool, str]:
    try:
        # -B: a fix often rewrites a file within the same second and at the same size, which
        # makes Python reuse the stale cached bytecode and re-run the broken code.
        completed = subprocess.run(
            [sys.executable, "-I", "-B", *args], cwd=workspace, capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {TIMEOUT_SECONDS}s (an infinite loop or a blocking input() call?)"
    return completed.returncode == 0, _tail(completed.stdout + completed.stderr)


# Undefined names we can import without asking a model; small models miss these repeatedly.
KNOWN_IMPORTS = {"st": "import streamlit as st", "pd": "import pandas as pd", "np": "import numpy as np"}


def _insert_at(lines: list[str]) -> int:
    """Index after a shebang/encoding comment, module docstring, and __future__ imports."""
    index = 0
    while index < len(lines) and lines[index].startswith("#"):
        index += 1
    if index < len(lines) and lines[index].lstrip().startswith(('"""', "'''")):
        quote = lines[index].lstrip()[:3]
        closed = lines[index].count(quote) >= 2
        index += 1
        while not closed and index < len(lines):
            closed = quote in lines[index]
            index += 1
    while index < len(lines) and lines[index].startswith("from __future__"):
        index += 1
    return index


def add_missing_imports(workspace: Path) -> list[str]:
    """Add imports for undefined names that are standard-library modules (or st/pd/np).

    Returns a line per fix, such as "save_load_test.py: import json".
    """
    passed, output = _run(
        ["-m", "ruff", "check", "--isolated", "--no-cache", "--select", "F821",
         "--output-format", "json", "."],
        workspace,
    )
    if passed:
        return []
    try:
        findings = json.loads(output[output.index("["):])
    except ValueError:
        return []  # ruff missing or output truncated: leave it to the model
    wanted: dict[Path, set[str]] = {}
    for finding in findings:
        name = re.search(r"`(\w+)`", finding.get("message", ""))
        if not name:
            continue
        statement = KNOWN_IMPORTS.get(name[1]) or (
            f"import {name[1]}" if name[1] in sys.stdlib_module_names else None
        )
        if statement:
            wanted.setdefault(Path(finding["filename"]), set()).add(statement)
    fixes = []
    for path, statements in wanted.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        index = _insert_at(lines)
        lines[index:index] = [f"{statement}\n" for statement in sorted(statements)]
        path.write_text("".join(lines), encoding="utf-8")
        relative = path.resolve().relative_to(workspace.resolve()).as_posix()
        fixes += [f"{relative}: {statement}" for statement in sorted(statements)]
    return fixes


def check_workspace(workspace: Path) -> list[str]:
    """Return a list of problems; an empty list means everything passed."""
    problems: list[str] = []
    files = python_files(workspace)
    for path in files:
        relative = path.relative_to(workspace).as_posix()
        try:
            compile(path.read_text(encoding="utf-8"), relative, "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            problems.append(f"{relative} does not compile: {exc}")
    if problems:
        return problems  # nothing else can run until the syntax is fixed

    add_missing_imports(workspace)

    # Undefined names (a missing import, a typo) hide in code paths no test or smoke run reaches.
    passed, output = _run(
        ["-m", "ruff", "check", "--isolated", "--no-cache", "--select", "F821,F822,F823",
         "--output-format", "concise", "."],
        workspace,
    )
    if not passed and "No module named ruff" not in output:
        problems.append(f"Undefined names (missing imports or typos):\n{output}")

    if any(is_test_file(path) for path in files):
        passed, output = _run_in_copy(["-m", "unittest", "discover", "-s", ".", "-t", ".", "-p", "*test*.py"], workspace)
        if not passed:
            problems.append(f"The tests fail (python -m unittest):\n{output}")

    for path in files:
        if is_test_file(path):
            continue
        source = path.read_text(encoding="utf-8")
        if "import streamlit" not in source or "st." not in source:
            continue
        relative = path.relative_to(workspace).as_posix()
        passed, output = _run_in_copy(["-c", SMOKE_SCRIPT, relative], workspace)
        if not passed:
            problems.append(f"The Streamlit app {relative} crashes when it loads:\n{output}")
    return problems


def _run_in_copy(args: list[str], workspace: Path) -> tuple[bool, str]:
    """Run model-written code against a throwaway copy of the source files.

    Tests and apps create data files (expenses.json and so on). Run in the real folder, one
    run's leftovers (an empty JSON file, say) make every later check fail for reasons that
    have nothing to do with the code. Only source files are copied, so each run starts clean.
    """
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder)
        for path in python_files(workspace):
            target = copy / path.relative_to(workspace)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        passed, output = _run(args, copy)
    # Point tracebacks at the real files so the model fixes the right thing.
    return passed, output.replace(str(copy), str(workspace)).replace(str(copy.resolve()), str(workspace))
