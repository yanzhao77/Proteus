import unittest

from fastapi.testclient import TestClient

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.readiness import StaticReadinessCheck
from hermes_runtime.infrastructure.fastapi_app import create_app


class ReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "state_summary": "IMPLEMENTING", "actor": actor_scope}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id, "snapshot_id": "snapshot-1"}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "safe_payload": {"question": "Approve?"}}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": [{"state": "EXITED"}]}


class CommandGateway:
    def __init__(self):
        self.payloads = []

    def submit_human_gate_decision(self, payload):
        self.payloads.append(dict(payload))
        return {"status": "ACCEPTED", "command_id": payload["command_id"]}


class FastApiServiceHostTests(unittest.TestCase):
    def setUp(self):
        self.gateway = CommandGateway()
        app = create_app(
            ProductApiFacade(ReadModel(), self.gateway),
            StaticReadinessCheck(),
            allowed_cors_origins=["https://operator.example"],
            max_body_bytes=512,
        )
        self.client = TestClient(app)

    def test_read_routes_are_allowlisted_and_generic_routes_are_absent(self):
        response = self.client.get(
            "/projects/project-1/status",
            headers={"X-Hermes-Actor-ID": "user-1", "X-Request-ID": "req-1"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("req-1", response.json()["request_id"])
        self.assertEqual("project-1", response.json()["data"]["project_id"])

        self.assertEqual(405, self.client.patch("/projects/project-1/status", json={"state": "ACCEPTED"}).status_code)
        schema = self.client.get("/openapi.json").json()
        schema_text = repr(schema)
        self.assertNotIn("/sql", schema_text)
        self.assertNotIn("/events", schema_text)
        self.assertNotIn("arbitrary_command", schema_text)

    def test_authority_changing_route_requires_content_type_idempotency_and_metadata(self):
        missing_idem = self.client.post(
            "/human-gates/gate-1/decisions",
            json={
                "command_id": "cmd-1",
                "expected_version": 1,
                "actor": {"type": "user", "id": "user-1"},
                "reason": "approve",
                "decision": "APPROVE",
            },
        )
        self.assertEqual(400, missing_idem.status_code)

        accepted = self.client.post(
            "/human-gates/gate-1/decisions",
            headers={"Idempotency-Key": "idem-1", "X-Request-ID": "req-2"},
            json={
                "command_id": "cmd-1",
                "expected_version": 1,
                "actor": {"type": "user", "id": "user-1"},
                "reason": "approve",
                "decision": "APPROVE",
            },
        )
        self.assertEqual(202, accepted.status_code)
        self.assertEqual("idem-1", self.gateway.payloads[0]["idempotency_key"])

    def test_errors_are_redacted_and_body_size_is_bounded(self):
        too_large = self.client.post(
            "/human-gates/gate-1/decisions",
            headers={"Idempotency-Key": "idem-1", "content-length": "9999"},
            content=b"{}",
        )
        self.assertEqual(413, too_large.status_code)
        body = too_large.json()
        self.assertEqual("REQUEST_TOO_LARGE", body["error"]["code"])
        self.assertNotIn("Traceback", repr(body))
        self.assertNotIn("postgresql://", repr(body))

    def test_livez_readyz_are_health_only(self):
        self.assertEqual({"status": "LIVE"}, self.client.get("/livez").json())
        ready = self.client.get("/readyz")
        self.assertEqual(200, ready.status_code)
        self.assertTrue(ready.json()["ready"])

        app = create_app(ProductApiFacade(ReadModel(), self.gateway), StaticReadinessCheck(database_ready=False))
        unavailable = TestClient(app).get("/readyz")
        self.assertEqual(503, unavailable.status_code)
        self.assertFalse(unavailable.json()["ready"])

    def test_default_cors_is_closed(self):
        app = create_app(ProductApiFacade(ReadModel(), self.gateway))
        client = TestClient(app)
        response = client.options(
            "/projects/project-1/status",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        self.assertNotEqual("https://evil.example", response.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()
