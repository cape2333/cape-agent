"""Generic, reusable checkers for agent evaluation.

Each checker is registered via the ``@checker`` decorator.  Eval cases
reference checkers by name in their ``expected`` block — the runner
matches keys automatically, so adding a new case never requires new
Python code (unless you need a brand-new check *type*).
"""

import ast
import subprocess
import time
from pathlib import Path
from typing import Any

CHECKER_REGISTRY: dict[str, "Checker"] = {}


class Checker:
    """Wraps a checker function with metadata."""

    def __init__(self, name: str, fn):
        self.name = name
        self.fn = fn

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


def checker(name: str):
    """Register a checker function by *name*."""
    def decorator(fn):
        c = Checker(name, fn)
        CHECKER_REGISTRY[name] = c
        return c
    return decorator


# ------------------------------------------------------------------
# File-level checks
# ------------------------------------------------------------------

@checker("files")
def check_files(expected_files: list, workdir: str, **_) -> dict[str, bool]:
    """Assert that expected files exist in *workdir*."""
    return {
        f"file_exists:{f}": (Path(workdir) / f).exists()
        for f in expected_files
    }


@checker("file_not_empty")
def check_not_empty(files: list, workdir: str, **_) -> dict[str, bool]:
    results = {}
    for f in files:
        p = Path(workdir) / f
        results[f"not_empty:{f}"] = p.exists() and p.stat().st_size > 0
    return results


@checker("file_min_size")
def check_min_size(size_map: dict, workdir: str, **_) -> dict[str, bool]:
    results = {}
    for f, min_bytes in size_map.items():
        p = Path(workdir) / f
        results[f"min_size:{f}>={min_bytes}B"] = (
            p.exists() and p.stat().st_size >= min_bytes
        )
    return results


# ------------------------------------------------------------------
# Python code checks
# ------------------------------------------------------------------

def _read_source(workdir: str, files: list) -> dict[str, str]:
    """Read source code for all .py files, returning {filename: source}."""
    sources = {}
    for f in files:
        p = Path(workdir) / f
        if p.exists() and f.endswith(".py"):
            try:
                sources[f] = p.read_text(encoding="utf-8")
            except Exception:
                pass
    return sources


@checker("python_syntax_valid")
def check_syntax(expected: bool, workdir: str, files: list = (), **_) -> dict[str, bool]:
    """Verify that every .py file compiles without ``SyntaxError``."""
    results = {}
    for f in files:
        p = Path(workdir) / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            compile(p.read_text(encoding="utf-8"), f, "exec")
            results[f"syntax:{f}"] = True
        except SyntaxError:
            results[f"syntax:{f}"] = False
    return results


@checker("python_runnable")
def check_python_runs(
    expected: bool, workdir: str, files: list = (), timeout: int = 5, **_,
) -> dict[str, bool]:
    """Start each .py file and assert it survives *timeout* seconds."""
    results = {}
    for f in files:
        p = Path(workdir) / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            proc = subprocess.Popen(
                ["python", str(p)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
            )
            time.sleep(timeout)
            alive = proc.poll() is None
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            results[f"runs:{f}"] = alive
        except Exception as exc:
            results[f"runs:{f}"] = False
    return results


@checker("code_must_contain")
def check_keywords(
    keywords: list, workdir: str, files: list = (), **_,
) -> dict[str, bool]:
    """Case-insensitive keyword search across all output files."""
    results = {}
    for f in files:
        p = Path(workdir) / f
        if not p.exists():
            for kw in keywords:
                results[f"contains:{kw}"] = False
            continue
        content = p.read_text(encoding="utf-8", errors="replace").lower()
        for kw in keywords:
            results[f"contains:{kw}"] = kw.lower() in content
    return results


@checker("code_must_import")
def check_imports(
    modules: list, workdir: str, files: list = (), **_,
) -> dict[str, bool]:
    """AST-level import check for .py files."""
    results = {}
    for f in files:
        p = Path(workdir) / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            for mod in modules:
                results[f"imports:{mod}"] = False
            continue

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for mod in modules:
            results[f"imports:{mod}"] = mod in imported
    return results


@checker("ast_has_loop")
def check_has_loop(expected: bool, workdir: str, files: list = (), **_) -> dict[str, bool]:
    """Check that at least one .py file contains a while/for loop."""
    for f in files:
        p = Path(workdir) / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.While, ast.For)):
                return {"ast_has_loop": True}
    return {"ast_has_loop": False}


@checker("ast_min_functions")
def check_min_functions(
    min_count: int, workdir: str, files: list = (), **_,
) -> dict[str, bool]:
    """Assert that .py files define at least *min_count* functions total."""
    total = 0
    for f in files:
        p = Path(workdir) / f
        if not p.exists() or not f.endswith(".py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        total += sum(
            1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
    return {f"min_functions>={min_count}": total >= min_count}


# ------------------------------------------------------------------
# Classification check
# ------------------------------------------------------------------

@checker("classification")
def check_classification(
    expected: str, actual_classification: str = "", **_,
) -> dict[str, bool]:
    return {"classification": actual_classification == expected}


# ------------------------------------------------------------------
# Simple-path answer check
# ------------------------------------------------------------------

@checker("answer_contains")
def check_answer_contains(
    keywords: list, answer: str = "", **_,
) -> dict[str, bool]:
    lower = answer.lower()
    return {
        f"answer_contains:{kw}": kw.lower() in lower for kw in keywords
    }


# ------------------------------------------------------------------
# Agent usage check (from SSE events)
# ------------------------------------------------------------------

_AGENT_KEYWORDS = {
    "browser": ["browser", "web research", "browsing", "information gathering"],
    "developer": ["developer", "code writing", "execution", "technical implementation"],
    "document": ["document", "file management", "content writing"],
}


@checker("agents_used")
def check_agents_used(
    expected_agents: list, activated_agents: list[str] = (), **_,
) -> dict[str, bool]:
    """Check that expected agent types were activated during execution."""
    activated_lower = [a.lower() for a in activated_agents]
    results = {}
    for agent_type in expected_agents:
        keywords = _AGENT_KEYWORDS.get(agent_type, [agent_type])
        found = any(
            kw in act for act in activated_lower for kw in keywords
        )
        results[f"agent_used:{agent_type}"] = found
    return results
