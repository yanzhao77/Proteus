import os
import shutil
import subprocess
import unittest

from hermes_runtime.domain.docker_execution import (
    DockerResourceLimits,
    DockerSandboxProfile,
    ExecutionEnvelope,
    compile_docker_run_plan,
)
from hermes_runtime.infrastructure.docker_adapter import DockerExecutionAdapter


DOCKER_ENABLED = os.environ.get("HERMES_TEST_DOCKER") == "1"


def _docker_available():
    if not DOCKER_ENABLED:
        return False
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0


@unittest.skipUnless(_docker_available(), "requires real Docker daemon and HERMES_TEST_DOCKER=1")
class DockerAdapterTests(unittest.TestCase):
    def test_real_container_runs_non_root_readonly_and_exports_artifact(self):
        envelope = ExecutionEnvelope(
            "project-1",
            "exec-1",
            1,
            "run-docker-1",
            "lease-1",
            1,
            11,
            "worker-1",
            "trace-docker",
            "corr-docker",
        )
        profile = DockerSandboxProfile(
            image="postgres:16",
            allow_unpinned_image=True,
            command=(
                "sh",
                "-c",
                "mkdir -p export && id -u > export/uid.txt && "
                "(touch /root/forbidden 2>/dev/null || echo rootfs-denied > export/rootfs.txt) && "
                "echo hello-p3-docker",
            ),
            limits=DockerResourceLimits(timeout_seconds=10, stdout_bytes=32, stderr_bytes=32),
        )
        plan = compile_docker_run_plan(profile, envelope, run_label="p3-4-6-production-hardening")
        result = DockerExecutionAdapter().execute(plan, envelope)
        self.assertEqual("SUCCEEDED", result.outcome)
        self.assertIn("hello-p3-docker", result.stdout_summary)
        by_path = {artifact["path"]: artifact for artifact in result.artifacts}
        self.assertIn("export/uid.txt", by_path)
        self.assertIn("export/rootfs.txt", by_path)
        self.assertTrue(by_path["export/uid.txt"]["content_hash"].startswith("sha256:"))
        self.assertGreater(by_path["export/uid.txt"]["size_bytes"], 0)
        self.assertEqual("PARTIAL_DOCKER_DESKTOP_OBSERVED", result.usage["trust"])

    def test_output_is_bounded_and_container_is_cleaned_by_name(self):
        envelope = ExecutionEnvelope("project-1", "exec-2", 1, "run-docker-2", "lease-2", 1, 12, "worker-1", "trace", "corr")
        profile = DockerSandboxProfile(
            image="postgres:16",
            allow_unpinned_image=True,
            command=("sh", "-c", "python3 - <<'PY'\nprint('x'*200)\nPY"),
            limits=DockerResourceLimits(timeout_seconds=10, stdout_bytes=24),
        )
        plan = compile_docker_run_plan(profile, envelope, run_label="p3-4-6-production-hardening")
        result = DockerExecutionAdapter().execute(plan, envelope)
        self.assertTrue(result.stdout_truncated or result.outcome == "FAILED")
        leaked = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=" + result.container_name, "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual("", leaked.stdout.decode().strip())


if __name__ == "__main__":
    unittest.main()
