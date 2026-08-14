import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence, Tuple


DOCKER_COMPILER_VERSION = "docker-target/1.0"
DOCKER_ADAPTER_VERSION = "docker-adapter/1.0"
SECRET_PATTERN = re.compile(
    r"(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|"
    r"private key|sk-[A-Za-z0-9]{12,}|password=)",
    re.IGNORECASE,
)


class DockerExecutionRejected(ValueError):
    pass


class DockerProcessState(str, Enum):
    PREPARED = "PREPARED"
    SPAWNING = "SPAWNING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    STALE_TERMINATED = "STALE_TERMINATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DockerResourceLimits:
    cpus: float = 1.0
    memory_bytes: int = 134_217_728
    pids: int = 64
    timeout_seconds: int = 10
    stdout_bytes: int = 16_384
    stderr_bytes: int = 16_384


@dataclass(frozen=True)
class DockerSandboxProfile:
    image: str
    command: Sequence[str]
    entrypoint: Sequence[str] = ()
    allow_unpinned_image: bool = False
    network_allowed: bool = False
    environment: Mapping[str, str] = None
    secret_handles: Sequence[str] = ()
    export_paths: Sequence[str] = ("export",)
    writable_paths: Sequence[str] = ("/workspace", "/tmp")
    user: str = "65532:65532"
    limits: DockerResourceLimits = DockerResourceLimits()


@dataclass(frozen=True)
class ExecutionEnvelope:
    project_id: str
    execution_request_id: str
    execution_attempt: int
    run_id: str
    lease_id: str
    lease_version: int
    fencing_token: int
    worker_agent_identity: str
    trace_id: str
    correlation_id: str


@dataclass(frozen=True)
class DockerRunPlan:
    plan_id: str
    plan_hash: str
    compiler_version: str
    image: str
    command: Tuple[str, ...]
    entrypoint: Tuple[str, ...]
    user: str
    network_mode: str
    read_only_rootfs: bool
    cap_drop: Tuple[str, ...]
    security_opts: Tuple[str, ...]
    tmpfs: Tuple[str, ...]
    export_paths: Tuple[str, ...]
    environment: Mapping[str, str]
    secret_handles: Tuple[str, ...]
    limits: DockerResourceLimits
    labels: Mapping[str, str]

    def docker_args(self, container_name: str, workspace_host_path: str) -> Tuple[str, ...]:
        args = [
            "run",
            "--name",
            container_name,
            "--network",
            self.network_mode,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.limits.pids),
            "--memory",
            str(self.limits.memory_bytes),
            "--cpus",
            str(self.limits.cpus),
            "--user",
            self.user,
            "--workdir",
            "/workspace",
            "--volume",
            workspace_host_path + ":/workspace:rw",
        ]
        for item in self.tmpfs:
            args.extend(["--tmpfs", item])
        for key, value in sorted(self.labels.items()):
            args.extend(["--label", key + "=" + value])
        for key, value in sorted(self.environment.items()):
            args.extend(["--env", key + "=" + value])
        if self.entrypoint:
            args.extend(["--entrypoint", self.entrypoint[0]])
        args.append(self.image)
        args.extend(self.command)
        return tuple(args)


def compile_docker_run_plan(
    profile: DockerSandboxProfile,
    envelope: ExecutionEnvelope,
    *,
    run_label: str,
) -> DockerRunPlan:
    env = dict(profile.environment or {})
    _reject_secret({"environment": env, "secret_handles": tuple(profile.secret_handles)})
    if not profile.allow_unpinned_image and "@sha256:" not in profile.image:
        raise DockerExecutionRejected("DOCKER_IMAGE_UNTRUSTED")
    if profile.network_allowed:
        raise DockerExecutionRejected("DOCKER_NETWORK_DENIED_BY_DEFAULT")
    if not profile.user or profile.user.startswith("0") or profile.user == "root":
        raise DockerExecutionRejected("DOCKER_NON_ROOT_REQUIRED")
    command = tuple(_require_arg(item) for item in profile.command)
    if not command:
        raise DockerExecutionRejected("DOCKER_COMMAND_UNSUPPORTED")
    export_paths = tuple(_normalize_export_path(path) for path in profile.export_paths)
    labels = {
        "hermes.test.run": run_label,
        "hermes.project_id": envelope.project_id,
        "hermes.execution_request_id": envelope.execution_request_id,
        "hermes.run_id": envelope.run_id,
        "hermes.lease_id": envelope.lease_id,
        "hermes.lease_version": str(int(envelope.lease_version)),
        "hermes.fencing_token": str(int(envelope.fencing_token)),
        "hermes.trace_id": envelope.trace_id,
        "hermes.adapter": DOCKER_ADAPTER_VERSION,
    }
    payload = {
        "compiler_version": DOCKER_COMPILER_VERSION,
        "image": profile.image,
        "command": command,
        "entrypoint": tuple(profile.entrypoint),
        "user": profile.user,
        "network_mode": "none",
        "read_only_rootfs": True,
        "cap_drop": ("ALL",),
        "security_opts": ("no-new-privileges",),
        "tmpfs": ("/tmp:rw,noexec,nosuid,nodev",),
        "export_paths": export_paths,
        "environment": env,
        "secret_handles": tuple(sorted(profile.secret_handles)),
        "limits": profile.limits.__dict__,
        "labels": labels,
    }
    plan_hash = "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return DockerRunPlan(
        plan_id="docker-plan-" + plan_hash.split(":", 1)[1][:24],
        plan_hash=plan_hash,
        compiler_version=DOCKER_COMPILER_VERSION,
        image=profile.image,
        command=command,
        entrypoint=tuple(profile.entrypoint),
        user=profile.user,
        network_mode="none",
        read_only_rootfs=True,
        cap_drop=("ALL",),
        security_opts=("no-new-privileges",),
        tmpfs=("/tmp:rw,noexec,nosuid,nodev",),
        export_paths=export_paths,
        environment=env,
        secret_handles=tuple(sorted(profile.secret_handles)),
        limits=profile.limits,
        labels=labels,
    )


def deterministic_container_name(envelope: ExecutionEnvelope) -> str:
    raw = f"{envelope.project_id}|{envelope.execution_request_id}|{envelope.run_id}|{envelope.lease_id}|{envelope.fencing_token}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return "hermes-" + digest


def validate_export_member(path: str, root: str) -> str:
    full = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if not full.startswith(root_real + os.sep):
        raise DockerExecutionRejected("DOCKER_ARTIFACT_EXPORT_VIOLATION")
    if os.path.islink(path) or not os.path.isfile(path):
        raise DockerExecutionRejected("DOCKER_ARTIFACT_EXPORT_VIOLATION")
    return full


def _normalize_export_path(path: str) -> str:
    text = str(path or "")
    posix = PurePosixPath(text)
    if posix.is_absolute() or ".." in posix.parts or text.startswith("."):
        raise DockerExecutionRejected("DOCKER_ARTIFACT_EXPORT_VIOLATION")
    if not text:
        raise DockerExecutionRejected("DOCKER_ARTIFACT_EXPORT_VIOLATION")
    return text


def _require_arg(value: str) -> str:
    text = str(value or "")
    if not text or len(text) > 400:
        raise DockerExecutionRejected("DOCKER_COMMAND_UNSUPPORTED")
    _reject_secret(text)
    return text


def _reject_secret(value: Any) -> None:
    if SECRET_PATTERN.search(json.dumps(value, sort_keys=True, default=str)):
        raise DockerExecutionRejected("DOCKER_SECRET_VALUE_FORBIDDEN")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
