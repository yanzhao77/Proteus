"""P6 real Verifier role for the Golden Project trial.

The verifier is an independent capability (Invariant 14: Worker != Judge). It
runs pytest inside the produced workspace and emits a machine-readable JSON
result that the harness converts into a VerificationResult through the real
authority path (verifier identity, exact artifact hash).

The verifier never writes Proteus authority directly; it only produces
evidence JSON for the Control Plane to record.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

VERIFIER_RESULT_SCHEMA_VERSION = "golden-verifier/1.0"


class VerifierFaultMode:
    NONE = "none"
    TAMPERED_ARTIFACT = "tampered_artifact"  # Scenario D: hash mismatch


def run_pytest_checks(workspace: Path, timeout_seconds: int = 240,
                     test_database_url: str = "") -> dict:
    venv_python = workspace / ".venv" / "bin" / "python"
    env = dict(os.environ)
    if test_database_url:
        env["TEST_DATABASE_URL"] = test_database_url
        env["DATABASE_URL"] = test_database_url
    command = [str(venv_python), "-m", "pytest", "-q"]
    completed = subprocess.run(
        command, cwd=str(workspace), capture_output=True, text=True,
        timeout=timeout_seconds, env=env,
    )
    passed = completed.returncode == 0
    return {
        "passed": passed,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-3000:],
        "stderr_tail": completed.stderr[-3000:],
        "tests_run": _parse_test_count(completed.stdout, completed.stderr),
    }


def _parse_test_count(stdout: str, stderr: str) -> int:
    import re
    text = stdout + stderr
    match = re.search(r"(\d+) passed", text)
    return int(match.group(1)) if match else 0


def verify_workspace(workspace: Path, expected_manifest: list,
                    test_database_url: str = "") -> dict:
    """Independent verification: run pytest and check content hashes.

    The manifest lists (path, content_hash) recorded by the worker. The
    verifier re-hashes the actual workspace files, so tampering (Scenario D)
    produces ARTIFACT_HASH_MISMATCH and a FAIL verdict.
    """
    import hashlib

    mismatches = []
    expected_by_path = {item["path"]: item["content_hash"] for item in expected_manifest}
    for path, expected_hash in sorted(expected_by_path.items()):
        actual_file = workspace / path
        if not actual_file.is_file():
            mismatches.append({"path": path, "reason": "MISSING"})
            continue
        actual_hash = "sha256:" + hashlib.sha256(actual_file.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append({
                "path": path,
                "expected": expected_hash,
                "actual": actual_hash,
                "reason": "ARTIFACT_HASH_MISMATCH",
            })
    pytest = run_pytest_checks(workspace, test_database_url=test_database_url)
    if mismatches:
        verdict = "FAIL"
        finding_codes = ("ARTIFACT_HASH_MISMATCH",)
    elif pytest["passed"]:
        verdict = "PASS"
        finding_codes = ()
    else:
        verdict = "FAIL"
        finding_codes = ("TEST_ASSERTION_FAILURE",)
    return {
        "schema_version": VERIFIER_RESULT_SCHEMA_VERSION,
        "verdict": verdict,
        "finding_codes": finding_codes,
        "hash_mismatches": mismatches,
        "pytest": pytest,
    }


def verifier_main(context_path: str) -> int:
    with open(context_path, "r", encoding="utf-8") as handle:
        context = json.load(handle)
    workspace = Path(context["workspace"])
    result = verify_workspace(
        workspace, context.get("expected_manifest", []),
        test_database_url=context.get("test_database_url", ""),
    )
    result["context"] = {
        "project_id": context.get("project_id"),
        "task_id": context.get("task_id"),
        "verification_plan_id": context.get("verification_plan_id"),
    }
    result_path = Path(context["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(verifier_main(sys.argv[1]))
