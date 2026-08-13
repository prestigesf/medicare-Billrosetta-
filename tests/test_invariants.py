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


def numeric_literals(path: Path, *, skip_named_constants: bool = False):
    """Every executable numeric literal in a source file, with line numbers.

    With skip_named_constants, literals assigned to a module-level UPPER_CASE
    name are excluded. A named constant is explained by its name; an inline
    number is not. This does not open a hole in invariant 2 — a rate is a
    float and a CPT code is a 5-digit int, and both are checked separately
    regardless of whether they are named.
    """
    tree = strip_docstrings(ast.parse(path.read_text(), filename=str(path)))

    named_constant_lines = set()
    if skip_named_constants:
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not all(isinstance(t, ast.Name) and t.id.isupper() for t in targets):
                continue
            if node.value is not None:
                named_constant_lines.update(
                    n.lineno for n in ast.walk(node.value) if hasattr(n, "lineno")
                )

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            if node.lineno in named_constant_lines:
                continue
            found.append((node.lineno, node.value))
    return found


@pytest.mark.parametrize("path", engine_sources(), ids=lambda p: p.name)
def test_no_float_literals_in_engine_source(path):
    """Rates, GPCIs and conversion factors are floats. None may be hardcoded.

    Exactly 0.0 is permitted: it is the identity used to start an accumulator
    or return an empty total, and no CMS value is ever zero — a rate, an index
    and a conversion factor are all strictly positive. Any other float is
    rejected regardless of how it is named.
    """
    floats = [
        (line, value) for line, value in numeric_literals(path)
        if isinstance(value, float) and value != 0.0
    ]
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
    """Catches magic numbers generally, not just CPT-shaped ones.

    A module-level UPPER_CASE constant counts as explained. An inline number
    does not.
    """
    unexpected = [
        (line, value)
        for line, value in numeric_literals(path, skip_named_constants=True)
        if isinstance(value, int) and value not in ALLOWED_INTS
    ]
    assert not unexpected, (
        f"{path.name} contains unexplained integer literal(s): {unexpected}. "
        "Give it a module-level UPPER_CASE name explaining what it is."
    )


def test_inline_magic_integer_still_fails_when_not_named(tmp_path):
    """The relaxation must not swallow an inline magic number."""
    planted = tmp_path / "planted.py"
    planted.write_text("NAMED_LIMIT = 20\n\n\ndef f(xs):\n    return xs[:37]\n")

    ints = [
        v for _, v in numeric_literals(planted, skip_named_constants=True)
        if isinstance(v, int) and v not in ALLOWED_INTS
    ]
    assert ints == [37], f"expected only the inline 37 to survive, got {ints}"


def test_a_named_cpt_code_is_still_caught(tmp_path):
    """Naming a constant must not launder CMS data into engine source."""
    planted = tmp_path / "planted.py"
    planted.write_text("DEFAULT_CODE = 99214\nDEFAULT_RATE = 110.50\n")

    all_literals = [v for _, v in numeric_literals(planted, skip_named_constants=True)]
    assert all_literals == [], "named constants are skipped by the general int check"

    unfiltered = [v for _, v in numeric_literals(planted)]
    assert 99214 in unfiltered and 110.50 in unfiltered, (
        "the CPT and float checks must see named constants — they do not skip them"
    )


def test_the_check_would_actually_catch_a_hardcoded_rate(tmp_path):
    """A guard that fails open is worse than no guard."""
    planted = tmp_path / "planted.py"
    planted.write_text('"""A docstring mentioning 110.50 is fine."""\nRATE = 110.50\n')

    floats = [v for _, v in numeric_literals(planted) if isinstance(v, float)]
    assert floats == [110.50], "the AST check failed to see a planted rate"


def test_a_nonzero_float_is_still_caught_however_it_is_written(tmp_path):
    """The 0.0 allowance must not become a doorway for a real rate."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "ZERO = 0.0\n"
        "TOTAL = 0.0\n"
        "SNEAKY_RATE = 110.50\n"
        "def f():\n"
        "    return 33.4009\n"
    )

    offending = [
        v for _, v in numeric_literals(planted)
        if isinstance(v, float) and v != 0.0
    ]
    assert sorted(offending) == [33.4009, 110.50]
