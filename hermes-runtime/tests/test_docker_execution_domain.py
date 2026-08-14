import unittest

from hermes_runtime.domain.docker_execution import (
    DockerExecutionRejected,
    DockerResourceLimits,
    DockerSandboxProfile,
    ExecutionEnvelope,
    compile_docker_run_plan,
    deterministic_container_name,
)


def _envelope(**overrides):
    values = dict(
        project_id="project-1",
        execution_request_id="exec-1",
        execution_attempt=1,
        run_id="run-1",
        lease_id="lease-1",
        lease_version=1,
        fencing_token=7,
        worker_agent_identity="worker-1",
        trace_id="trace-1",
        correlation_id="corr-1",
    )
    values.update(overrides)
    return ExecutionEnvelope(**values)


class DockerExecutionDomainTests(unittest.TestCase):
    def test_compile_plan_is_deterministic_and_deny_by_default(self):
        profile = DockerSandboxProfile(
            image="postgres:16",
            allow_unpinned_image=True,
            command=("sh", "-c", "echo ok > export/result.txt"),
            limits=DockerResourceLimits(timeout_seconds=5),
        )
        first = compile_docker_run_plan(profile, _envelope(), run_label="p3-test")
        second = compile_docker_run_plan(profile, _envelope(), run_label="p3-test")
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual("none", first.network_mode)
        self.assertTrue(first.read_only_rootfs)
        self.assertEqual(("ALL",), first.cap_drop)
        self.assertIn("no-new-privileges", first.security_opts)
        self.assertEqual("65532:65532", first.user)
        self.assertEqual(deterministic_container_name(_envelope()), deterministic_container_name(_envelope()))

    def test_unpinned_image_secret_network_root_and_export_escape_fail_closed(self):
        base = dict(image="postgres:16", command=("echo", "ok"))
        with self.assertRaisesRegex(DockerExecutionRejected, "DOCKER_IMAGE_UNTRUSTED"):
            compile_docker_run_plan(DockerSandboxProfile(**base), _envelope(), run_label="p3-test")
        with self.assertRaisesRegex(DockerExecutionRejected, "DOCKER_NETWORK_DENIED_BY_DEFAULT"):
            compile_docker_run_plan(
                DockerSandboxProfile(**dict(base, allow_unpinned_image=True, network_allowed=True)),
                _envelope(),
                run_label="p3-test",
            )
        with self.assertRaisesRegex(DockerExecutionRejected, "DOCKER_NON_ROOT_REQUIRED"):
            compile_docker_run_plan(
                DockerSandboxProfile(**dict(base, allow_unpinned_image=True, user="0:0")),
                _envelope(),
                run_label="p3-test",
            )
        with self.assertRaisesRegex(DockerExecutionRejected, "DOCKER_SECRET_VALUE_FORBIDDEN"):
            compile_docker_run_plan(
                DockerSandboxProfile(
                    **dict(base, allow_unpinned_image=True, environment={"TOKEN": "password=clear"})
                ),
                _envelope(),
                run_label="p3-test",
            )
        with self.assertRaisesRegex(DockerExecutionRejected, "DOCKER_ARTIFACT_EXPORT_VIOLATION"):
            compile_docker_run_plan(
                DockerSandboxProfile(**dict(base, allow_unpinned_image=True, export_paths=("../escape",))),
                _envelope(),
                run_label="p3-test",
            )


if __name__ == "__main__":
    unittest.main()
