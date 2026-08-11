"""Generate a phase evidence artifact, then read it back and re-verify.

A claim is not a result. This runs the suite, preserves the raw output,
records what produced it, hashes every source file, and hashes the payload
itself — then re-reads the file from disk and recomputes the payload hash to
prove the artifact on disk is the artifact that was generated.

Usage:
    python tools/make_evidence.py <phase-number>

All dict keys are strings throughout. JSON coerces integer keys to strings on
write, so a payload containing int keys hashes differently after a round-trip
and the read-back check fails for a reason that has nothing to do with the
evidence.
"""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"

# Hashed as the code under test. Generated artifacts are excluded so evidence
# never registers as source drift.
SOURCE_GLOBS = ("pfs/*.py", "tests/*.py", "tools/*.py", "pyproject.toml", "README.md")


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def dependency_versions() -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True, text=True, timeout=120,
    )
    versions = {}
    for line in out.stdout.splitlines():
        if "==" in line:
            name, _, version = line.partition("==")
            versions[name.strip()] = version.strip()
    return versions


def run_suite(phase: int) -> tuple[str, int, dict]:
    """Run pytest with warnings as errors, preserving the raw output."""
    EVIDENCE.mkdir(exist_ok=True)
    raw_path = EVIDENCE / f"phase{phase}_raw_test_output.txt"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-W", "error"],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    raw = result.stdout + result.stderr
    raw_path.write_text(raw)

    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for line in raw.splitlines():
        if " PASSED" in line:
            counts["passed"] += 1
        elif " FAILED" in line:
            counts["failed"] += 1
        elif " ERROR" in line:
            counts["error"] += 1
        elif " SKIPPED" in line:
            counts["skipped"] += 1

    return str(raw_path.relative_to(ROOT)), result.returncode, counts


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    phase = int(sys.argv[1])

    raw_rel, exit_code, counts = run_suite(phase)

    files = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            files[str(path.relative_to(ROOT))] = sha256_file(path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    payload = {
        "phase": str(phase),
        "timestamp_utc": timestamp,
        "git_commit": git_commit(),
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "dependencies": dependency_versions(),
        "test_command": "python -m pytest -v -W error",
        "test_exit_code": str(exit_code),
        "test_counts": {k: str(v) for k, v in counts.items()},
        "raw_output_file": raw_rel,
        "raw_output_sha256": sha256_file(ROOT / raw_rel),
        "source_file_sha256": files,
        "overall_status": "PASS" if exit_code == 0 and counts["failed"] == 0 else "FAIL",
    }

    artifact = {"payload": payload, "payload_sha256": payload_hash(payload)}

    out_path = EVIDENCE / f"phase_{phase}_validation_{timestamp}.json"
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    # Read back from disk and re-verify — the artifact must prove itself.
    reloaded = json.loads(out_path.read_text())
    recomputed = payload_hash(reloaded["payload"])
    verified = recomputed == reloaded["payload_sha256"]

    print(f"artifact:        {out_path.relative_to(ROOT)}")
    print(f"raw output:      {raw_rel}")
    print(f"tests:           {counts['passed']} passed, {counts['failed']} failed, "
          f"{counts['error']} error, {counts['skipped']} skipped (exit {exit_code})")
    print(f"overall_status:  {payload['overall_status']}")
    print(f"payload sha256:  {reloaded['payload_sha256']}")
    print(f"read-back:       {'VERIFIED — recomputed hash matches' if verified else 'MISMATCH'}")

    if not verified:
        print(f"  recomputed:    {recomputed}")
        return 1
    return 0 if payload["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
