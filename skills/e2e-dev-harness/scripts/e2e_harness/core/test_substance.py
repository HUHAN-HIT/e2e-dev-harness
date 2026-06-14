"""Test-substance analysis — detect empty-shell tests (link ③).

A green test that asserts nothing proves nothing. This module statically
classifies each test as:

- ``empty``      — no assertion at all, only a trivial ``assert True``/``pass``,
                   or an ``assertDoesNotThrow(() -> {})`` with an empty body.
- ``suspicious`` — asserts only that something ``is not None`` (weak).
- ``ok``         — has a real assertion.

Pure and conservative: unparseable input yields no verdicts (never a false
block). The IMPLEMENTED gate blocks on ``empty`` and reports ``suspicious``.
"""
from __future__ import annotations

import ast
import re


def analyze_with_diagnostics(source: str, language: str) -> dict:
    if language == "python":
        try:
            ast.parse(source)
        except SyntaxError as exc:
            return {"verdicts": [], "warnings": [_warning("analyzer-limitation", exc.lineno)]}
        return {"verdicts": _analyze_python(source), "warnings": []}
    if language == "java":
        return {"verdicts": _analyze_java(source), "warnings": []}
    if language in ("javascript", "typescript"):
        return _analyze_javascript_like(source)
    return {"verdicts": [], "warnings": []}


def analyze(source: str, language: str) -> list[tuple[str, str]]:
    return list(analyze_with_diagnostics(source, language).get("verdicts", []))


def empties(source: str, language: str) -> list[str]:
    return [name for name, verdict in analyze(source, language) if verdict == "empty"]


# --- Python (AST) -------------------------------------------------------------

def _analyze_python(source: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            results.append((node.lineno, node.name, _classify_python(node)))
    results.sort(key=lambda r: r[0])
    return [(name, verdict) for _line, name, verdict in results]


def _classify_python(fn: ast.FunctionDef) -> str:
    strength = "none"  # none < trivial < weak < strong
    rank = {"none": 0, "trivial": 1, "weak": 2, "strong": 3}

    def bump(level: str) -> None:
        nonlocal strength
        if rank[level] > rank[strength]:
            strength = level

    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            bump(_python_assert_strength(node.test))
        elif isinstance(node, ast.Call):
            bump(_python_call_strength(node))
        elif isinstance(node, ast.withitem):
            ctx = node.context_expr
            if isinstance(ctx, ast.Call) and _attr_or_name(ctx.func) in ("raises", "assertRaises"):
                bump("strong")
    return {"none": "empty", "trivial": "empty", "weak": "suspicious", "strong": "ok"}[strength]


def _python_assert_strength(test: ast.expr) -> str:
    if isinstance(test, ast.Constant):
        return "trivial"
    if isinstance(test, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops):
        if any(isinstance(c, ast.Constant) and c.value is None for c in test.comparators):
            return "weak"  # `x is not None`
    return "strong"


def _python_call_strength(call: ast.Call) -> str:
    name = _attr_or_name(call.func)
    if name in ("assertIsNotNone", "assertIsNone"):
        return "weak"
    if name and (name.startswith("assert") or name.startswith("assert_")
                 or name in ("raises",) or name.endswith("_called")
                 or name.startswith("assert_called")):
        return "strong"
    return "none"


def _attr_or_name(node) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


# --- Java (text heuristics) ---------------------------------------------------

_JAVA_METHOD = re.compile(r"@Test\b[\s\S]*?\b(\w+)\s*\([^)]*\)\s*(?:throws[^{]*)?\{")
_JAVA_STRONG = re.compile(
    r"\b(assertEquals|assertTrue|assertFalse|assertThat|assertSame|"
    r"assertNotSame|assertArrayEquals|assertNotEquals|verify)\s*\(")
_JAVA_WEAK = re.compile(r"\b(assertNotNull|assertNull)\s*\(")


def _analyze_java(source: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _JAVA_METHOD.finditer(source):
        name = m.group(1)
        body = _brace_body(source, m.end() - 1)
        out.append((name, _classify_java(body)))
    return out


def _classify_java(body: str) -> str:
    if _JAVA_STRONG.search(body):
        return "ok"
    if _JAVA_WEAK.search(body):
        return "suspicious"
    return "empty"


def _brace_body(text: str, open_idx: int) -> str:
    """Return the text inside the method body whose opening brace is at open_idx."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
    return text[open_idx + 1:]


# --- JavaScript / TypeScript (conservative text heuristics) -------------------

_JS_TEST = re.compile(r"\b(?:test|it)\s*\(\s*(['\"])(.*?)\1\s*,", re.S)
_JS_STRONG = re.compile(
    r"\bexpect\s*\([\s\S]*?\)\s*\.(?:"
    r"toBe|toEqual|toStrictEqual|toMatchObject|toHaveBeenCalled|"
    r"toHaveBeenCalledWith|toHaveTextContent|toContain|toThrow"
    r")\s*\("
    r"|\bawait\s+expect\s*\([\s\S]*?\)\s*\.(?:resolves|rejects)\b"
    r"|\bexpect\s*\([\s\S]*?queryBy\w+\s*\([\s\S]*?\)[\s\S]*?\)\s*\.toBeNull\s*\("
    r"|\bassert\.(?:equal|deepEqual|strictEqual|deepStrictEqual)\s*\("
    r"|\bscreen\.(?:getBy|findBy)\w+\s*\("
    r"|\bawait\s+page\.expect\b",
    re.S,
)
_JS_WEAK = re.compile(
    r"\bexpect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)"
    r"|\bexpect\s*\([\s\S]*?\)\s*\.toBeDefined\s*\("
    r"|\bexpect\s*\([\s\S]*?\)\s*\.not\s*\.toBeNull\s*\(",
    re.S,
)


def _analyze_javascript_like(source: str) -> dict:
    verdicts: list[tuple[str, str]] = []
    warnings: list[dict] = []
    for match in _JS_TEST.finditer(source):
        name = match.group(2)
        open_idx = source.find("{", match.end())
        if open_idx == -1:
            warnings.append(_warning("analyzer-limitation", _line_of(source, match.start())))
            continue
        body = _balanced_body(source, open_idx)
        if body is None:
            return {
                "verdicts": [],
                "warnings": [_warning("analyzer-limitation", _line_of(source, match.start()))],
            }
        verdicts.append((name, _classify_javascript_like(body)))
    if not verdicts and re.search(r"\b(?:test|it)\s*\(", source):
        warnings.append(_warning("analyzer-limitation", 1))
    return {"verdicts": verdicts, "warnings": warnings}


def _classify_javascript_like(body: str) -> str:
    if _JS_STRONG.search(body):
        if re.fullmatch(r"\s*expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)\s*;?\s*", body, re.S):
            return "empty"
        return "ok"
    if _JS_WEAK.search(body):
        return "suspicious"
    return "empty"


def _balanced_body(text: str, open_idx: int) -> str | None:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
    return None


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _warning(code: str, line: int | None = None, message: str | None = None) -> dict:
    out = {"code": code, "message": message or "Analyzer could not fully classify this test shape."}
    if line is not None:
        out["line"] = line
    return out
