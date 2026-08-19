import inspect
import unittest

from fastapi.testclient import TestClient

from hermes_runtime.application.factory_workspace_ui import FactoryWorkspaceRenderer
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.infrastructure.fastapi_app import create_app


class ReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "status": "REQUESTED"}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": []}


class Gateway:
    def submit_human_gate_decision(self, payload):
        return {"status": "ACCEPTED"}


class FactoryWorkspaceUiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ProductApiFacade(ReadModel(), Gateway()))
        self.client = TestClient(self.app)

    def test_workspace_routes_render_non_authoritative_fixture_notice(self):
        for path in (
            "/home", "/new", "/drafts/demo-draft", "/productions",
            "/productions/demo-production", "/gates",
        ):
            response = self.client.get(path)
            self.assertEqual(200, response.status_code, path)
            self.assertIn("DEMO / NON-AUTHORITATIVE UI FIXTURE", response.text)
            self.assertIn("not connected", response.text.lower())

    def test_home_is_entry_navigation_not_authority_creation(self):
        response = self.client.get("/home")
        self.assertEqual(200, response.status_code)
        self.assertIn("What do you want to build?", response.text)
        self.assertIn('action="/drafts/demo-draft" method="get"', response.text)
        self.assertNotIn("Production Created", response.text)
        self.assertNotIn("start_worker", response.text)
        self.assertNotIn("apply_resume", response.text)

    def test_workspace_routes_register_get_only(self):
        workspace_paths = {
            "/home", "/new", "/drafts/{draft_id}", "/productions",
            "/productions/{production_id}", "/gates",
        }
        methods = {
            route.path: route.methods for route in self.app.routes
            if route.path in workspace_paths
        }
        self.assertEqual(workspace_paths, set(methods))
        for route_methods in methods.values():
            self.assertEqual({"GET"}, route_methods)

    def test_renderer_has_no_runtime_authority_imports(self):
        source = inspect.getsource(FactoryWorkspaceRenderer)
        for forbidden in (
            "postgres_", "sqlite", "sqlalchemy", "scheduler", "worker_execution",
            "ProductCommandGateway", "trial.", "command_handlers",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
