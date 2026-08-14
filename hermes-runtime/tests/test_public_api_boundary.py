import unittest

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRejected
from hermes_runtime.infrastructure.http_api import InProcessHttpApiAdapter


class FakeReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "state_summary": "IMPLEMENTING", "actor_scope": actor_scope}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id, "snapshot_id": "expl-1", "links": []}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "safe_payload": {"question": "Approve?"}}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": [{"state": "EXITED"}]}


class FakeCommandGateway:
    def __init__(self):
        self.payloads = []

    def submit_human_gate_decision(self, payload):
        self.payloads.append(dict(payload))
        return {"status": "ACCEPTED", "command_id": payload["command_id"]}


class PublicApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeCommandGateway()
        self.adapter = InProcessHttpApiAdapter(ProductApiFacade(FakeReadModel(), self.gateway))
        self.actor = Actor(ActorType.USER, "user-1")

    def test_read_endpoints_are_read_model_only(self):
        response = self.adapter.dispatch("GET", "/projects/project-1/status", {}, {}, self.actor)
        self.assertEqual(200, response.status_code)
        self.assertEqual("project-1", response.body["project_id"])

        explain = self.adapter.dispatch("GET", "/decisions/decision-1/explain", {}, {}, self.actor)
        self.assertEqual("expl-1", explain.body["snapshot_id"])

    def test_human_gate_decision_preserves_actor_scope_and_command_metadata(self):
        response = self.adapter.dispatch(
            "POST",
            "/human-gates/gate-1/decisions",
            {"Idempotency-Key": "idem-header"},
            {
                "command_id": "cmd-1",
                "expected_version": 4,
                "actor": {"type": "user", "id": "user-1"},
                "reason": "authorized product decision",
                "decision": "APPROVE",
            },
            self.actor,
        )

        self.assertEqual(202, response.status_code)
        self.assertEqual("gate-1", self.gateway.payloads[0]["gate_request_id"])
        self.assertEqual("idem-header", self.gateway.payloads[0]["idempotency_key"])
        self.assertTrue(self.gateway.payloads[0]["canonical_payload_hash"].startswith("sha256:"))

    def test_missing_idempotency_and_stale_expected_version_shape_are_rejected(self):
        with self.assertRaisesRegex(ProductApiRejected, "API_IDEMPOTENCY_KEY_MISSING"):
            self.adapter.dispatch(
                "POST",
                "/human-gates/gate-1/decisions",
                {},
                {
                    "command_id": "cmd-1",
                    "expected_version": 4,
                    "actor": {"type": "user", "id": "user-1"},
                    "reason": "authorized product decision",
                },
                self.actor,
            )
        with self.assertRaisesRegex(ProductApiRejected, "API_EXPECTED_VERSION_INVALID"):
            self.adapter.dispatch(
                "POST",
                "/human-gates/gate-1/decisions",
                {"Idempotency-Key": "idem"},
                {
                    "command_id": "cmd-1",
                    "expected_version": "4",
                    "actor": {"type": "user", "id": "user-1"},
                    "reason": "authorized product decision",
                },
                self.actor,
            )

    def test_generic_authority_routes_are_not_supported(self):
        for method, path, body in (
            ("PATCH", "/projects/project-1", {}),
            ("POST", "/generic-command", {"command_type": "task.pass"}),
            ("POST", "/events", {"event_type": "task.passed"}),
            ("POST", "/tasks/task-1/status", {"status": "PASSED"}),
        ):
            with self.subTest(path=path):
                with self.assertRaises(ProductApiRejected):
                    self.adapter.dispatch(method, path, {"Idempotency-Key": "idem"}, body, self.actor)


if __name__ == "__main__":
    unittest.main()
