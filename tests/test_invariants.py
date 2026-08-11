"""Invariant: rates are data, not code.

The engine must contain no rate, no CPT code, and no conversion factor. If a
number that belongs in a CMS file ever appears in engine source, this fails —
which is the whole scalability thesis: loading a new schedule year must never
require touching this package.

Docstrings and string constants are stripped before the check, so prose that
mentions a figure is fine. Only executable numeric literals count.
"""
import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "pfs"

# Small integers are structural — slice indices, tuple sizes, precision args.
# Anything a CMS file would supply is either a float or a 5-digit code.
ALLOWED_INTS = frozenset(range(0, 11))


def engine_sources():
    return sorted(PACKAGE.glob("*.py"))


def strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove docstring expressions so prose can mention numbers freely."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                node.body = body[1:]
    return tree


def numeric_literals(path: Path):
    """Every executable numeric literal in a source file, with line numbers."""
    tree = strip_docstrings(ast.parse(path.read_text(), filename=str(path)))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            found.append((node.lineno, node.value))
    return found


@pytest.mark.parametrize("path", engine_sources(), ids=lambda p: p.name)
def test_no_float_literals_in_engine_source(path):
    """Rates, GPCIs and conversion factors are floats. None may be hardcoded."""
    floats = [(line, value) for line, value in numeric_literals(path) if isinstance(value, float)]
    assert not floats, (
        f"{path.name} contains float literal(s) in executable code: {floats}. "
        "Rates, GPCIs and conversion factors must come from CMS data, not source."
    )


@pytest.mark.parametrize("path", engine_sources(), ids=lambda p: p.name)
def test_no_cpt_shaped_integers_in_engine_source(path):
    """A 5-digit integer in engine code is a CPT code that shouldn't be there."""
    codes = [
        (line, value)
        for line, value in numeric_literals(path)
        if isinstance(value, int) and 10000 <= value <= 99999
    ]
    assert not codes, (
        f"{path.name} contains CPT-shaped integer literal(s): {codes}. "
        "Codes belong in the RVU file, not in engine source."
    )


@pytest.mark.parametrize("path", engine_sources(), ids=lambda p: p.name)
def test_only_structural_integers_in_engine_source(path):
    """Catches magic numbers generally, not just CPT-shaped ones."""
    unexpected = [
        (line, value)
        for line, value in numeric_literals(path)
        if isinstance(value, int) and value not in ALLOWED_INTS
    ]
    assert not unexpected, (
        f"{path.name} contains unexplained integer literal(s): {unexpected}."
    )


def test_the_check_would_actually_catch_a_hardcoded_rate(tmp_path):
    """A guard that fails open is worse than no guard."""
    planted = tmp_path / "planted.py"
    planted.write_text('"""A docstring mentioning 110.50 is fine."""\nRATE = 110.50\n')

    floats = [v for _, v in numeric_literals(planted) if isinstance(v, float)]
    assert floats == [110.50], "the AST check failed to see a planted rate"
