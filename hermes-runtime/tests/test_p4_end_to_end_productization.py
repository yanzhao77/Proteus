import tempfile
import unittest
from pathlib import Path

from hermes_runtime.application.human_gate_product import HumanGateProductFacade, ProductGateDecisionRequest
from hermes_runtime.application.observability import ObservabilityExportService
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.human_gate import GateDecisionKind, HumanGateRejected
from hermes_runtime.domain.identity import IdentityAssertionInput
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.observability import ObservabilityRecord, ObservabilityRejected, missing_link
from hermes_runtime.domain.product_artifacts import ArtifactBoundaryRejected, ArtifactProvenance
from hermes_runtime.domain.product_api import ProductApiRejected
from hermes_runtime.infrastructure.http_api import InProcessHttpApiAdapter
from hermes_runtime.infrastructure.local_artifact_store import LocalContentAddressedArtifactStore
from hermes_runtime.infrastructure.local_identity import LocalIdentityAssertionProvider
from hermes_runtime.infrastructure.local_observability import LocalObservabilityExporter
from hermes_runtime.infrastructure.local_secrets import LocalSecretHandleProvider


class ReadModel:
    def __init__(self):
        self.explain_queries = 0

    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "state_summary": "WAITING_FOR_HUMAN"}

    def decision_explain(self, decision_id, actor_scope):
        self.explain_queries += 1
        return {"decision_id": decision_id, "snapshot_id": "snapshot-fixed", "recomputed": False}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "safe_payload": {"question": "Resume?"}}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": [{"kind": "MISSING_LINK"}]}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": [{"state": "EXITED", "task_authority": "NONE"}]}


class CommandGateway:
    def __init__(self):
        self.payloads = []

    def submit_human_gate_decision(self, payload):
        self.payloads.append(dict(payload))
        return {"accepted": True, "command_id": payload["command_id"]}


class GateStore:
    def get_gate_request(self, gate_request_id):
        return {"gate_request_id": gate_request_id, "safe_payload": {"question": "Resume?"}}

    def list_gate_requests(self, project_id, actor):
        return (self.get_gate_request("gate-1"),)


class DecisionSink:
    def submit_decision(self, command):
        return {"status": "DECISION_RECORDED", "gate_decision_id": command.gate_decision_id}


class EvidenceQuery:
    def __init__(self, invalid=()):
        self.invalid = set(invalid)

    def invalid_evidence_refs(self, project_id, evidence_refs):
        return tuple(ref for ref in evidence_refs if ref in self.invalid)


class P4EndToEndProductizationTests(unittest.TestCase):
    def setUp(self):
        self.actor = Actor(ActorType.USER, "user-1")

    def test_api_to_human_gate_decision_cannot_skip_resume_guard(self):
        read_model = ReadModel()
        gateway = CommandGateway()
        api = InProcessHttpApiAdapter(ProductApiFacade(read_model, gateway))
        response = api.dispatch(
            "POST",
            "/human-gates/gate-1/decisions",
            {"Idempotency-Key": "idem-1"},
            {
                "command_id": "cmd-1",
                "expected_version": 2,
                "actor": {"type": "user", "id": "user-1"},
                "reason": "approve guarded resume",
                "decision": "APPROVE",
            },
            self.actor,
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual("gate-1", gateway.payloads[0]["gate_request_id"])
        with self.assertRaises(ProductApiRejected):
            api.dispatch("POST", "/projects/project-1/status", {"Idempotency-Key": "idem-2"}, {"status": "IMPLEMENTING"}, self.actor)

    def test_decision_explain_query_is_read_only_and_not_recomputed(self):
        read_model = ReadModel()
        api = InProcessHttpApiAdapter(ProductApiFacade(read_model, CommandGateway()))
        first = api.dispatch("GET", "/decisions/decision-1/explain", {}, {}, self.actor)
        second = api.dispatch("GET", "/decisions/decision-1/explain", {}, {}, self.actor)
        self.assertEqual("snapshot-fixed", first.body["snapshot_id"])
        self.assertFalse(second.body["recomputed"])
        self.assertEqual(2, read_model.explain_queries)

    def test_docker_observation_query_has_no_task_pass_authority(self):
        api = InProcessHttpApiAdapter(ProductApiFacade(ReadModel(), CommandGateway()))
        response = api.dispatch("GET", "/docker-processes/process-1/observations", {}, {}, self.actor)
        self.assertEqual("NONE", response.body["observations"][0]["task_authority"])

    def test_artifact_store_export_binds_verification_to_exact_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalContentAddressedArtifactStore(Path(tmp))
            artifact = store.put(
                "artifact-1",
                b"verified payload",
                "text/plain",
                ArtifactProvenance("project-1", "task-1", "worker", "worker-1", "evt-1", "corr-1"),
                "short",
                "2026-01-01T00:00:00Z",
            )
            verification_ref = {"artifact_id": "artifact-1", "artifact_hash": artifact.content_hash}
            self.assertEqual(artifact.content_hash, verification_ref["artifact_hash"])
            with self.assertRaises(ArtifactBoundaryRejected):
                store.put("artifact-1", b"mutated payload", "text/plain", artifact.provenance, "short", "2026-01-01T00:00:00Z")

    def test_secret_handle_does_not_leak_to_payloads(self):
        provider = LocalSecretHandleProvider()
        handle = provider.register("secret-1", "plain-secret", "project-1", {"purpose": "test"})
        payload = {"secret_handle": handle.handle_id, "secret_hash": handle.secret_hash}
        provider.assert_no_registered_secret_value(payload)
        with self.assertRaises(Exception):
            provider.assert_no_registered_secret_value({"log": "plain-secret"})

    def test_retention_archive_does_not_delete_referenced_authority_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalContentAddressedArtifactStore(Path(tmp))
            artifact = store.put(
                "artifact-1",
                b"payload",
                "text/plain",
                ArtifactProvenance("project-1", "task-1", "worker", "worker-1", "evt-1", "corr-1"),
                "short",
                "2026-01-01T00:00:00Z",
            )
            with self.assertRaisesRegex(ArtifactBoundaryRejected, "RETENTION_AUTHORITY_DEPENDENCY_ACTIVE"):
                store.purge_raw_content("artifact-1", "2027-01-01T00:00:00Z", ("decision-1",))
            archived = store.archive("artifact-1", "2027-01-01T00:00:00Z")
            self.assertEqual(artifact.content_hash, archived.content_hash)

    def test_observability_missing_link_is_missing_and_not_fabricated(self):
        exporter = LocalObservabilityExporter()
        service = ObservabilityExportService(exporter)
        service.export_record(
            ObservabilityRecord(
                trace_id="trace-1",
                span_id="span-1",
                parent_span_id="",
                name="gate.resume.query",
                timestamp="2026-08-14T00:00:00Z",
                attributes={"component": "api"},
                missing_links=(missing_link("evidence", "evidence-1", "invalidated"),),
            )
        )
        self.assertEqual("invalidated", exporter.envelopes[0]["missing_links"][0]["reason"])
        with self.assertRaisesRegex(ObservabilityRejected, "OBSERVABILITY_CANNOT_AUTHORIZE"):
            service.export_record(
                ObservabilityRecord(
                    trace_id="trace-2",
                    span_id="span-2",
                    parent_span_id="",
                    name="unsafe",
                    timestamp="2026-08-14T00:00:00Z",
                    attributes={"policy_allow": True},
                )
            )

    def test_gate_product_facade_blocks_invalidated_evidence_and_direct_resume(self):
        assertion = LocalIdentityAssertionProvider().issue(
            "assert-1",
            IdentityAssertionInput(
                issuer="local-test",
                subject="user-1",
                role="approver",
                project_id="project-1",
                task_id=None,
                gate_request_id="gate-1",
                action_scope="project:resume",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2099-01-01T00:00:00Z",
            ),
        )
        facade = HumanGateProductFacade(GateStore(), DecisionSink(), EvidenceQuery(invalid=("evidence-1",)))
        request = ProductGateDecisionRequest(
            command_id="cmd-1",
            idempotency_key="idem-1",
            project_id="project-1",
            gate_decision_id="decision-1",
            gate_request_id="gate-1",
            decision=GateDecisionKind.APPROVE,
            requester=Actor(ActorType.MAIN_HERMES, "main"),
            approver=self.actor,
            authorization_ref="authz-1",
            assertion=assertion,
            expected_gate_version=2,
            current_gate_version=2,
            action_scope="project:resume",
            reason="approve guarded resume",
            now="2026-08-14T00:00:00Z",
            evidence_refs=("evidence-1",),
        )
        with self.assertRaisesRegex(HumanGateRejected, "GATE_EVIDENCE_INVALID"):
            facade.submit_decision(request)
        with self.assertRaisesRegex(HumanGateRejected, "GATE_PRODUCT_FACADE_CANNOT_RESUME_PROJECT"):
            facade.apply_resume()


if __name__ == "__main__":
    unittest.main()
