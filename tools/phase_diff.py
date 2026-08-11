"""Code-drift differ against a frozen phase baseline.

Compares the current code-scope tree against a baseline file and separates two
things that must never be conflated:

  AUTHORIZED   changes the phase declared it would make
  UNEXPECTED   everything else — drift

Code scope EXCLUDES evidence/, so generated artifacts never register as source
drift. Evidence is hashed inside the evidence artifact itself, separately.

Baseline format is one line per file:

    <sha256>  <path>

Usage:
    python tools/phase_diff.py <baseline-file> "<authorized,csv,of,paths>"
    python tools/phase_diff.py --freeze <baseline-file>

Exit code is 0 when there is no unexpected drift, 1 when there is.
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE_GLOBS = ("pfs/*.py", "tests/*.py", "tools/*.py", "*.toml", "*.md")
EXCLUDED_DIRS = {"evidence", ".venv", ".git", "__pycache__", ".pytest_cache"}


def in_code_scope(path: Path) -> bool:
    return not any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts)


def current_tree() -> dict:
    tree = {}
    for pattern in CODE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file() or not in_code_scope(path):
                continue
            rel = str(path.relative_to(ROOT))
            tree[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(tree.items()))


def read_baseline(path: Path) -> dict:
    baseline = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition("  ")
        baseline[rel.strip()] = digest.strip()
    return baseline


def freeze(baseline_path: Path) -> int:
    tree = current_tree()
    baseline_path.parent.mkdir(exist_ok=True)
    baseline_path.write_text("".join(f"{d}  {p}\n" for p, d in tree.items()))
    print(f"froze {len(tree)} files -> {baseline_path.relative_to(ROOT)}")
    return 0


def diff(baseline_path: Path, authorized: set) -> int:
    baseline = read_baseline(baseline_path)
    current = current_tree()

    added = sorted(set(current) - set(baseline))
    deleted = sorted(set(baseline) - set(current))
    modified = sorted(p for p in set(current) & set(baseline) if current[p] != baseline[p])

    def split(paths):
        return (
            [p for p in paths if p in authorized],
            [p for p in paths if p not in authorized],
        )

    auth_added, drift_added = split(added)
    auth_modified, drift_modified = split(modified)
    auth_deleted, drift_deleted = split(deleted)

    print(f"baseline: {baseline_path.relative_to(ROOT)} ({len(baseline)} files)")
    print(f"current:  {len(current)} files in code scope\n")

    print("AUTHORIZED")
    for label, paths in (("added", auth_added), ("modified", auth_modified), ("deleted", auth_deleted)):
        print(f"  {label} ({len(paths)}):")
        for p in paths:
            print(f"    {p}")

    drift_total = len(drift_added) + len(drift_modified) + len(drift_deleted)
    print(f"\nUNEXPECTED CODE DRIFT ({drift_total})")
    for label, paths in (("added", drift_added), ("modified", drift_modified), ("deleted", drift_deleted)):
        if paths:
            print(f"  {label}:")
            for p in paths:
                print(f"    {p}")
    if drift_total == 0:
        print("  none")

    return 1 if drift_total else 0


def resolve_under_root(raw: str) -> Path:
    """Accept a path relative to the project root or an absolute one."""
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path).resolve()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--freeze":
        return freeze(resolve_under_root(sys.argv[2]))
    if len(sys.argv) in (2, 3):
        baseline = resolve_under_root(sys.argv[1])
        authorized = set()
        if len(sys.argv) == 3:
            authorized = {p.strip() for p in sys.argv[2].split(",") if p.strip()}
        return diff(baseline, authorized)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
