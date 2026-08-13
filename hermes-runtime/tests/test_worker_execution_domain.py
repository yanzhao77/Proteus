import unittest

from hermes_runtime.domain.worker_execution import (
    ArtifactCandidateSubmission,
    EvidenceCandidateSubmission,
    ExecutionOutcome,
    ExecutionResultSubmission,
    UsageSampleSubmission,
    WorkerExecutionRejected,
    WorkerFrozenContext,
    WorkerLeaseBinding,
    hash_payload,
    normalize_artifact_candidate,
    normalize_binding,
    normalize_evidence_candidate,
    normalize_execution_result,
    normalize_frozen_context,
    normalize_usage_sample,
    reject_forbidden_worker_verdict,
)


class WorkerExecutionDomainTests(unittest.TestCase):
    def binding(self, **overrides):
        values = dict(
            project_id="project-1",
            execution_request_id="exec-1",
            execution_attempt=1,
            run_id="run-1",
            lease_id="lease-1",
            lease_version=1,
            fencing_token=7,
            scheduler_id="sched-1",
            scheduler_session_id="session-1",
            worker_agent_identity="worker-1",
            context_identity="ctx-identity-1",
            observed_request_version=2,
        )
        values.update(overrides)
        return WorkerLeaseBinding(**values)

    def frozen_context(self, **overrides):
        values = dict(
            worker_template_id="template-1",
            worker_template_revision=1,
            worker_template_content_hash="sha256:template",
            context_bundle_id="context-1",
            context_manifest_hash="sha256:context",
            sandbox_profile_id="sandbox-1",
            sandbox_profile_hash="sha256:sandbox",
            reservation_id="reservation-1",
        )
        values.update(overrides)
        return WorkerFrozenContext(**values)

    def test_binding_and_frozen_context_are_strictly_scoped(self):
        self.assertEqual(7, normalize_binding(self.binding())["fencing_token"])
        self.assertEqual(
            "contract-free",
            normalize_frozen_context(
                self.frozen_context(sandbox_profile_id="contract-free")
            )["sandbox_profile_id"],
        )
        with self.assertRaisesRegex(WorkerExecutionRejected, "FENCING_TOKEN_STALE"):
            normalize_binding(self.binding(fencing_token=0))
        with self.assertRaisesRegex(WorkerExecutionRejected, "AGENT_RUN_SCOPE_MISMATCH"):
            normalize_frozen_context(self.frozen_context(worker_template_content_hash="bad"))

    def test_candidate_provenance_and_refs_fail_closed(self):
        candidate = normalize_artifact_candidate(ArtifactCandidateSubmission(
            "artifact-candidate-1", "patch", "sha256:artifact", "object://artifact/1", 10
        ))
        self.assertEqual("sha256:artifact", candidate["content_hash"])
        with self.assertRaisesRegex(WorkerExecutionRejected, "ARTIFACT_REF_UNSAFE"):
            normalize_artifact_candidate(ArtifactCandidateSubmission(
                "artifact-candidate-2", "patch", "sha256:artifact", "/tmp/raw-file"
            ))
        evidence = normalize_evidence_candidate(EvidenceCandidateSubmission(
            "evidence-candidate-1", "log-summary", "object://evidence/1",
            "sha256:evidence", "2026-08-13T00:00:00Z",
        ))
        self.assertEqual("sha256:evidence", evidence["source_hash"])

    def test_usage_sample_uses_integer_p1_dimensions(self):
        sample = normalize_usage_sample(UsageSampleSubmission(
            "usage-1", "sample-1", "reservation-1",
            {"execution_time_ms": 100, "llm_tokens": 0},
        ))
        self.assertEqual(100, sample["amounts"]["execution_time_ms"])
        with self.assertRaisesRegex(WorkerExecutionRejected, "RESOURCE_AMOUNT_INVALID"):
            normalize_usage_sample(UsageSampleSubmission(
                "usage-2", "sample-2", "reservation-1", {"execution_time_ms": 1.5},
            ))
        with self.assertRaisesRegex(WorkerExecutionRejected, "RESOURCE_CURRENCY_MISMATCH"):
            normalize_usage_sample(UsageSampleSubmission(
                "usage-3", "sample-3", "reservation-1", {"llm_cost_minor": 10},
            ))

    def test_result_outcome_is_not_verification_verdict(self):
        succeeded = normalize_execution_result(ExecutionResultSubmission(
            "result-1", ExecutionOutcome.SUCCEEDED, "", ("artifact-candidate-1",),
            ("evidence-candidate-1",), ("sample-1",),
            "2026-08-13T00:00:00Z", "2026-08-13T00:00:01Z",
            "test-adapter", "1.0", primary_artifact_candidate_id="artifact-candidate-1",
            completion_claim_id="claim-1",
        ))
        self.assertEqual("SUCCEEDED", succeeded["outcome"])
        with self.assertRaisesRegex(WorkerExecutionRejected, "COMPLETION_CLAIM_ARTIFACT_REQUIRED"):
            normalize_execution_result(ExecutionResultSubmission(
                "result-2", ExecutionOutcome.SUCCEEDED, "", (), (), (),
                "2026-08-13T00:00:00Z", "2026-08-13T00:00:01Z",
                "test-adapter", "1.0",
            ))
        with self.assertRaisesRegex(WorkerExecutionRejected, "COMPLETION_CLAIM_NOT_ELIGIBLE"):
            normalize_execution_result(ExecutionResultSubmission(
                "result-3", ExecutionOutcome.FAILED_PERMANENT, "test_failed", (), (), (),
                "2026-08-13T00:00:00Z", "2026-08-13T00:00:01Z",
                "test-adapter", "1.0", completion_claim_id="claim-3",
            ))
        with self.assertRaisesRegex(WorkerExecutionRejected, "WORKER_VERDICT_FORBIDDEN"):
            reject_forbidden_worker_verdict({"nested": {"verdict": "PASS"}})

    def test_payload_hash_is_canonical(self):
        self.assertEqual(hash_payload({"b": 2, "a": 1}), hash_payload({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
