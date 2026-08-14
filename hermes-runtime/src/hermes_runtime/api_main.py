import os

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.readiness import StaticReadinessCheck
from hermes_runtime.config import env_or_file
from hermes_runtime.infrastructure.fastapi_app import create_app


class EmptyReadModel:
    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id, "state_summary": "UNAVAILABLE_UNTIL_CONFIGURED"}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id, "snapshot_id": "", "missing_links": [{"reason": "read model not configured"}]}

    def human_gate_request(self, gate_request_id, actor_scope):
        return {"gate_request_id": gate_request_id, "safe_payload": {}, "status": "UNAVAILABLE_UNTIL_CONFIGURED"}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"project_id": project_id, "findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"process_id": process_id, "observations": []}


class RejectingGateway:
    def submit_human_gate_decision(self, payload):
        return {"status": "REJECTED", "reason": "command gateway not configured", "command_id": payload.get("command_id", "")}


def build_app():
    origins = [item for item in os.getenv("HERMES_CORS_ORIGINS", "").split(",") if item]
    database_url = env_or_file("HERMES_DATABASE_URL")
    return create_app(
        ProductApiFacade(EmptyReadModel(), RejectingGateway()),
        StaticReadinessCheck(database_ready=bool(database_url)),
        allowed_cors_origins=origins,
    )


app = build_app()
