from typing import Any, Mapping, Protocol

from hermes_runtime.domain.product_api import (
    ProductApiRejected,
    ProductApiRequest,
    ProductApiResponse,
    canonical_payload_hash,
    ensure_safe_response,
    reject_forbidden_authority_shape,
    require_authority_command_metadata,
)


class ProductReadModel(Protocol):
    def project_status(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def decision_explain(self, decision_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def human_gate_request(self, gate_request_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def replay_reconcile_findings(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def docker_process_observations(self, process_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class ProductCommandGateway(Protocol):
    def submit_human_gate_decision(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class ProductApiFacade:
    def __init__(self, read_model: ProductReadModel, command_gateway: ProductCommandGateway) -> None:
        self._read_model = read_model
        self._command_gateway = command_gateway

    def handle(self, request: ProductApiRequest) -> ProductApiResponse:
        reject_forbidden_authority_shape(request)
        method = request.method.upper()
        parts = [part for part in request.path.strip("/").split("/") if part]
        actor_scope = {
            "actor_type": request.actor.actor_type.value,
            "actor_id": request.actor.actor_id,
        }

        if method == "GET" and len(parts) == 3 and parts[0] == "projects" and parts[2] == "status":
            return self._safe(200, self._read_model.project_status(parts[1], actor_scope))

        if method == "GET" and len(parts) == 3 and parts[0] == "decisions" and parts[2] == "explain":
            return self._safe(200, self._read_model.decision_explain(parts[1], actor_scope))

        if method == "GET" and len(parts) == 2 and parts[0] == "human-gates":
            return self._safe(200, self._read_model.human_gate_request(parts[1], actor_scope))

        if method == "POST" and len(parts) == 3 and parts[0] == "human-gates" and parts[2] == "decisions":
            payload = dict(request.body)
            payload["gate_request_id"] = parts[1]
            payload["idempotency_key"] = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
            require_authority_command_metadata(payload)
            payload["canonical_payload_hash"] = canonical_payload_hash(payload)
            return self._safe(202, self._command_gateway.submit_human_gate_decision(payload))

        if method == "GET" and len(parts) == 3 and parts[0] == "projects" and parts[2] == "reconcile-findings":
            return self._safe(200, self._read_model.replay_reconcile_findings(parts[1], actor_scope))

        if method == "GET" and len(parts) == 3 and parts[0] == "docker-processes" and parts[2] == "observations":
            return self._safe(200, self._read_model.docker_process_observations(parts[1], actor_scope))

        raise ProductApiRejected("API_ROUTE_NOT_SUPPORTED")

    def _safe(self, status_code: int, body: Mapping[str, Any]) -> ProductApiResponse:
        ensure_safe_response(body)
        return ProductApiResponse(status_code=status_code, body=body)
