import hashlib
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes_runtime.domain.docker_execution import (
    DOCKER_ADAPTER_VERSION,
    DockerExecutionRejected,
    DockerRunPlan,
    ExecutionEnvelope,
    deterministic_container_name,
    validate_export_member,
)


@dataclass(frozen=True)
class DockerExecutionResult:
    container_name: str
    container_id: str
    exit_code: int
    outcome: str
    elapsed_ms: int
    stdout_summary: str
    stderr_summary: str
    stdout_truncated: bool
    stderr_truncated: bool
    artifacts: Sequence[Mapping[str, Any]]
    usage: Mapping[str, Any]


class DockerExecutionAdapter:
    def __init__(self, docker_bin: str = "docker") -> None:
        self._docker = docker_bin

    def execute(self, plan: DockerRunPlan, envelope: ExecutionEnvelope) -> DockerExecutionResult:
        container_name = deterministic_container_name(envelope)
        workspace = tempfile.mkdtemp(prefix="hermes-docker-work-")
        os.chmod(workspace, 0o777)
        try:
            for export_path in plan.export_paths:
                path = Path(workspace) / export_path
                path.mkdir(parents=True, exist_ok=True)
                os.chmod(path, 0o777)
            args = [self._docker] + list(plan.docker_args(container_name, workspace))
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=plan.limits.timeout_seconds,
                    check=False,
                )
                exit_code = int(completed.returncode)
                outcome = "SUCCEEDED" if exit_code == 0 else "FAILED"
            except subprocess.TimeoutExpired as exc:
                subprocess.run([self._docker, "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                completed = exc
                exit_code = 124
                outcome = "TIMED_OUT"
            elapsed_ms = int((time.monotonic() - started) * 1000)
            container_id = self._container_id(container_name)
            stdout_raw = completed.stdout or b""
            stderr_raw = completed.stderr or b""
            stdout_summary, stdout_truncated = _summarize(stdout_raw, plan.limits.stdout_bytes)
            stderr_summary, stderr_truncated = _summarize(stderr_raw, plan.limits.stderr_bytes)
            artifacts = self._collect_artifacts(workspace, plan.export_paths)
            usage = {
                "elapsed_time_ms": elapsed_ms,
                "cpu_time_ms": None,
                "memory_peak_bytes": None,
                "io_bytes": None,
                "trust": "PARTIAL_DOCKER_DESKTOP_OBSERVED",
            }
            return DockerExecutionResult(
                container_name=container_name,
                container_id=container_id,
                exit_code=exit_code,
                outcome=outcome,
                elapsed_ms=elapsed_ms,
                stdout_summary=stdout_summary,
                stderr_summary=stderr_summary,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                artifacts=tuple(artifacts),
                usage=usage,
            )
        finally:
            subprocess.run([self._docker, "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            shutil.rmtree(workspace, ignore_errors=True)

    def _container_id(self, container_name: str) -> str:
        result = subprocess.run(
            [self._docker, "ps", "-a", "--filter", "name=^/" + container_name + "$", "--format", "{{.ID}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()

    def _collect_artifacts(self, workspace: str, export_paths: Sequence[str]):
        artifacts = []
        root = os.path.realpath(workspace)
        for export_path in export_paths:
            base = Path(workspace) / export_path
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_dir():
                    continue
                full = validate_export_member(str(path), root)
                data = Path(full).read_bytes()
                digest = "sha256:" + hashlib.sha256(data).hexdigest()
                artifacts.append(
                    {
                        "path": str(path.relative_to(workspace)),
                        "content_hash": digest,
                        "size_bytes": len(data),
                        "media_type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
                        "provenance": {
                            "adapter": DOCKER_ADAPTER_VERSION,
                            "export_root": export_path,
                        },
                    }
                )
        return artifacts


def _summarize(raw: bytes, limit: int):
    truncated = len(raw) > limit
    clipped = raw[:limit]
    text = clipped.decode("utf-8", errors="replace")
    text = text.replace("password=", "password:<redacted>")
    return text, truncated
