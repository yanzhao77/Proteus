"""P6 real Worker role for the Golden Project trial.

This is the execution capability (the "HOW"). Proteus decides WHAT/WHY/WHEN/
WHETHER; this worker builds the Golden Project files into a workspace, runs
pytest inside the workspace to produce candidate evidence, and emits a
machine-readable result with content-addressed artifact manifests.

The worker is a real subprocess: it reads a JSON context file, writes real
project files, runs real commands, and writes a real JSON result. It never
touches Proteus authority directly.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GOLDEN_TODO_FILES = {
    "README.md": "README",
    "requirements.txt": "requirements",
    "pyproject.toml": "pyproject",
    "app/__init__.py": "app_init",
    "app/main.py": "app_main",
    "app/models.py": "app_models",
    "app/security.py": "app_security",
    "tests/__init__.py": "tests_init",
    "tests/conftest.py": "tests_conftest",
    "tests/test_api.py": "tests_api",
    "compose.yml": "compose",
    "Dockerfile": "dockerfile",
    ".env.example": "env_example",
    ".github/workflows/ci.yml": "ci",
    ".gitignore": "gitignore",
}


class WorkerFaultMode:
    NONE = "none"
    BROKEN_TEST = "broken_test"  # Scenario A: verification failure
    MISSING_FEATURE = "missing_feature"  # alternative repair target


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_root() -> Path:
    # examples/golden-todo lives at the repository root.
    here = Path(__file__).resolve()
    repo = here.parents[4]
    return repo / "examples" / "golden-todo"


def build_workspace(workspace: Path, fault_mode: str = WorkerFaultMode.NONE) -> dict:
    """Copy the Golden Project template into the workspace and apply fault mode.

    The worker genuinely materializes the project (real file writes) and
    computes the content-addressed manifest. pytest is run separately (after
    the workspace venv exists) so the build evidence is real. Fault modes are
    deterministic, real mutations used only by failure-injection scenarios.
    """
    source = _source_root()
    if not source.is_dir():
        raise RuntimeError("golden-todo template missing at " + str(source))
    for rel, _key in GOLDEN_TODO_FILES.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (source / rel).read_bytes()
        if fault_mode == WorkerFaultMode.BROKEN_TEST and rel == "tests/test_api.py":
            payload = payload.replace(
                b'assert response.json()["status"] == "LIVE"',
                b'assert response.json()["status"] == "NOT_LIVE"',
            )
        if fault_mode == WorkerFaultMode.MISSING_FEATURE and rel == "app/security.py":
            # Omit the security module: app.main imports it, so the build is
            # genuinely broken (ImportError) and pytest really fails.
            continue
        target.write_bytes(payload)

    manifest = _manifest(workspace)
    return {
        "workspace": str(workspace),
        "fault_mode": fault_mode,
        "manifest": manifest,
    }


def _manifest(workspace: Path) -> list:
    entries = []
    for path in sorted(workspace.rglob("*")):
        if (
            path.is_file()
            and ".venv" not in path.parts
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        ):
            relative = str(path.relative_to(workspace))
            entries.append({
                "path": relative,
                "content_hash": sha256_bytes(path.read_bytes()),
                "size_bytes": path.stat().st_size,
            })
    return entries


def _run_pytest(workspace: Path, timeout_seconds: int = 240,
                test_database_url: str = "") -> dict:
    """Run pytest inside the workspace; the workspace needs a venv with deps."""
    venv_python = workspace / ".venv" / "bin" / "python"
    env = dict(os.environ)
    if test_database_url:
        env["TEST_DATABASE_URL"] = test_database_url
        env["DATABASE_URL"] = test_database_url
    command = [str(venv_python), "-m", "pytest", "-q"]
    try:
        completed = subprocess.run(
            command, cwd=str(workspace), capture_output=True, text=True,
            timeout=timeout_seconds, env=env,
        )
        return {
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
            "passed": completed.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout_tail": "", "stderr_tail": "TIMEOUT", "passed": False}


def prepare_workspace_venv(workspace: Path) -> None:
    """Create a dedicated venv and install requirements inside the workspace.

    This is part of the worker's real build: the produced project must be able
    to install and run its own dependencies.
    """
    subprocess.run(
        [sys.executable, "-m", "venv", str(workspace / ".venv")],
        check=True,
    )
    pip = workspace / ".venv" / "bin" / "pip"
    requirements = workspace / "requirements.txt"
    subprocess.run(
        [str(pip), "install", "-q", "-r", str(requirements)],
        check=True,
        timeout=600,
    )


def worker_main(context_path: str) -> int:
    with open(context_path, "r", encoding="utf-8") as handle:
        context = json.load(handle)
    workspace = Path(context["workspace"])
    workspace.mkdir(parents=True, exist_ok=True)
    fault_mode = context.get("fault_mode", WorkerFaultMode.NONE)
    # Materialize the project files first, then prepare the venv: the venv
    # install reads requirements.txt from the produced workspace. pytest then
    # runs inside the workspace so the build evidence is real.
    result = build_workspace(workspace, fault_mode)
    if context.get("prepare_venv", True):
        prepare_workspace_venv(workspace)
    result["pytest"] = _run_pytest(
        workspace, test_database_url=context.get("test_database_url", "")
    )
    result["context"] = {
        "project_id": context.get("project_id"),
        "task_id": context.get("task_id"),
        "execution_request_id": context.get("execution_request_id"),
        "request_summary": context.get("request_summary", ""),
    }
    result_path = Path(context["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pytest"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(worker_main(sys.argv[1]))
