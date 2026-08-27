from typing import Any, Mapping, Optional, Protocol

from hermes_runtime.application.factory_home_read_model import FactoryHomeReadModel, UnavailableFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_live_production_read_model import UnavailableLiveProductionReadModel
from hermes_runtime.application.entry_understanding_api import UnavailableEntryUnderstandingApi
from hermes_runtime.application.entry_proposal_master_plan_api import UnavailableEntryProposalMasterPlanApi
from hermes_runtime.application.entry_approval_bridge import UnavailableEntryApprovalBridgeApi
from hermes_runtime.application.entry_draft_api import EntryDraftApi, UnavailableEntryDraftApi
from hermes_runtime.application.user_project_command_transport import (
    UnavailableUserProjectCommandTransport,
    UserProjectCommandRejected,
)
from hermes_runtime.domain.entry_draft import EntryDraftRejected
from hermes_runtime.infrastructure.postgres_entry_draft import EntryDraftStoreUnavailable
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
    def __init__(
        self,
        read_model: ProductReadModel,
        command_gateway: ProductCommandGateway,
        factory_home_read_model: Optional[FactoryHomeReadModel] = None,
        entry_draft_api: Optional[EntryDraftApi] = None,
        entry_understanding_api=None,
        entry_proposal_master_plan_api=None,
        entry_approval_bridge_api=None,
        live_production_read_model=None,
        user_project_command_transport=None,
    ) -> None:
        self._read_model = read_model
        self._command_gateway = command_gateway
        self._factory_home_read_model = factory_home_read_model or UnavailableFactoryHomeReadModel()
        self._entry_draft_api = entry_draft_api or UnavailableEntryDraftApi()
        self._entry_understanding_api = entry_understanding_api or UnavailableEntryUnderstandingApi()
        self._entry_proposal_master_plan_api = entry_proposal_master_plan_api or UnavailableEntryProposalMasterPlanApi()
        self._entry_approval_bridge_api = entry_approval_bridge_api or UnavailableEntryApprovalBridgeApi()
        self._live_production_read_model = live_production_read_model or UnavailableLiveProductionReadModel()
        self._user_project_command_transport = user_project_command_transport or UnavailableUserProjectCommandTransport()

    def handle(self, request: ProductApiRequest) -> ProductApiResponse:
        reject_forbidden_authority_shape(request)
        method = request.method.upper()
        parts = [part for part in request.path.strip("/").split("/") if part]
        actor_scope = {
            "actor_type": request.actor.actor_type.value,
            "actor_id": request.actor.actor_id,
            "identity_verified": bool(request.verified_identity_subject),
            "identity_subject": request.verified_identity_subject or None,
        }

        if method == "GET" and parts == ["factory-home"]:
            return self._safe(200, self._factory_home_read_model.factory_home_snapshot(actor_scope))
        if method == "GET" and parts == ["factory-home", "productions"]:
            return self._safe(200, self._factory_home_read_model.production_portfolio(actor_scope))
        if method == "GET" and len(parts) == 3 and parts[0] == "factory-home" and parts[1] == "productions":
            return self._safe(200, self._factory_home_read_model.production_snapshot(parts[2], actor_scope))
        if method == "GET" and len(parts) == 4 and parts[0] == "factory-home" and parts[1] == "productions" and parts[3] == "live":
            return self._safe(200, self._live_production_read_model.snapshot(parts[2], actor_scope))
        if method == "GET" and len(parts) == 4 and parts[0] == "factory-home" and parts[1] == "productions" and parts[3] == "live-feed":
            return self._safe(200, self._live_production_read_model.events(parts[2], actor_scope, request.body.get("after", 0), request.body.get("limit", 50)))
        if method == "POST" and len(parts) == 5 and parts[:2] == ["factory-home", "productions"] and parts[3] == "commands":
            payload = self._project_command_payload(request)
            try:
                response = self._user_project_command_transport.submit(
                    action=parts[4],
                    project_id=parts[2],
                    verified_identity_subject=request.verified_identity_subject,
                    actor=request.actor,
                    **payload,
                )
            except UserProjectCommandRejected as exc:
                raise ProductApiRejected(str(exc)) from exc
            return self._safe(202, response)
        if method == "GET" and len(parts) == 5 and parts[:2] == ["factory-home", "productions"] and parts[3] == "commands":
            try:
                response = self._user_project_command_transport.receipt(
                    project_id=parts[2],
                    command_id=parts[4],
                    verified_identity_subject=request.verified_identity_subject,
                    actor=request.actor,
                )
            except UserProjectCommandRejected as exc:
                raise ProductApiRejected(str(exc)) from exc
            return self._safe(200, response)
        if method == "GET" and parts == ["factory-home", "gates"]:
            return self._safe(200, self._factory_home_read_model.gate_attention(actor_scope))
        if method == "GET" and parts == ["factory-home", "drafts"]:
            subject = self._draft_subject(request)
            return self._safe(200, self._entry_draft_api.list(subject))
        if method == "GET" and parts == ["production-drafts"]:
            subject = self._draft_subject(request)
            return self._safe(200, self._entry_draft_api.list(subject))
        if method == "GET" and len(parts) == 2 and parts[0] == "production-drafts":
            subject = self._draft_subject(request)
            return self._safe(200, self._entry_draft_api.get(subject, parts[1]))
        if method == "POST" and parts == ["production-drafts"]:
            subject = self._draft_subject(request)
            payload = self._draft_payload(request)
            return self._safe(201, {"availability": "CURRENT", "item": self._entry_draft_api.create(subject, title=payload["title"], raw_input=payload["raw_input"], idempotency_key=payload["idempotency_key"], reason=payload["reason"])})
        if method == "POST" and len(parts) == 3 and parts[0] == "production-drafts" and parts[2] == "revisions":
            subject = self._draft_subject(request)
            payload = self._draft_payload(request, require_content=True)
            return self._safe(200, {"availability": "CURRENT", "item": self._entry_draft_api.revise(subject, parts[1], title=payload["title"], raw_input=payload["raw_input"], expected_version=payload["expected_version"], idempotency_key=payload["idempotency_key"], reason=payload["reason"])})
        if method == "POST" and len(parts) == 3 and parts[0] == "production-drafts" and parts[2] in {"submit", "archive"}:
            subject = self._draft_subject(request)
            payload = self._draft_payload(request, require_content=False)
            operation = self._entry_draft_api.submit if parts[2] == "submit" else self._entry_draft_api.archive
            return self._safe(200, {"availability": "CURRENT", "item": operation(subject, parts[1], expected_version=payload["expected_version"], idempotency_key=payload["idempotency_key"], reason=payload["reason"])})
        if len(parts) >= 3 and parts[0] == "production-drafts" and parts[2] == "understanding":
            subject = self._draft_subject(request)
            draft_id = parts[1]
            if method == "GET" and len(parts) == 3:
                return self._safe(200, self._entry_understanding_api.get(subject, draft_id))
            if method == "GET" and len(parts) == 4 and parts[3] == "revisions":
                return self._safe(200, self._entry_understanding_api.list_revisions(subject, draft_id))
            if method == "GET" and len(parts) == 4 and parts[3] == "clarifications":
                return self._safe(200, self._entry_understanding_api.list_clarifications(subject, draft_id))
            if method == "POST" and len(parts) == 3:
                payload = self._understanding_payload(request)
                return self._safe(202, {"availability":"CURRENT", "item":self._entry_understanding_api.generate(subject, draft_id, payload["expected_version"], payload["idempotency_key"], payload["reason"])})
            if method == "POST" and len(parts) == 6 and parts[3] == "clarifications" and parts[5] == "answer":
                payload = self._understanding_payload(request)
                answer = request.body.get("answer") if isinstance(request.body, Mapping) else None
                return self._safe(202, {"availability":"CURRENT", "item":self._entry_understanding_api.answer_clarification(subject, draft_id, parts[4], answer, payload["expected_version"], payload["idempotency_key"], payload["reason"])})
            raise ProductApiRejected("UNSUPPORTED_ROUTE")
        if len(parts) >= 3 and parts[0] == "production-drafts" and parts[2] == "proposal":
            subject = self._draft_subject(request)
            draft_id = parts[1]
            if method == "GET" and len(parts) == 3:
                return self._safe(200, self._entry_proposal_master_plan_api.get_proposal(subject, draft_id))
            if method == "GET" and len(parts) == 4 and parts[3] == "revisions":
                return self._safe(200, self._entry_proposal_master_plan_api.list_proposal_revisions(subject, draft_id))
            if method == "POST" and len(parts) == 3:
                payload = self._e3_payload(request, "ENTRY_PROPOSAL_SCHEMA_INVALID")
                return self._safe(201, {"availability": "CURRENT", "item": self._entry_proposal_master_plan_api.generate_proposal(subject, draft_id, payload["expected_version"], payload["idempotency_key"], payload["reason"])})
            if len(parts) >= 4 and parts[3] == "master-plan":
                if method == "GET" and len(parts) == 4:
                    return self._safe(200, self._entry_proposal_master_plan_api.get_master_plan(subject, draft_id))
                if method == "GET" and len(parts) == 5 and parts[4] == "revisions":
                    return self._safe(200, self._entry_proposal_master_plan_api.list_master_plan_revisions(subject, draft_id))
                if method == "POST" and len(parts) == 4:
                    payload = self._e3_payload(request, "ENTRY_PLAN_SCHEMA_INVALID")
                    return self._safe(201, {"availability": "CURRENT", "item": self._entry_proposal_master_plan_api.generate_master_plan(subject, draft_id, payload["expected_version"], payload["idempotency_key"], payload["reason"])})
                if method == "GET" and len(parts) == 5 and parts[4] == "approval-preview":
                    preview = self._entry_approval_bridge_api.preview(subject, draft_id)
                    if isinstance(preview, Mapping):
                        return self._safe(200, preview)
                    # ApprovalPreview is a domain dataclass. Do not expose its frozen
                    # blueprint (which contains child identities); return only the
                    # creator-visible values required to form the approval command.
                    return self._safe(200, {
                        "availability": "CURRENT",
                        "bridge_id": preview.bridge_id,
                        "compiled_blueprint_hash": preview.compiled_blueprint_hash,
                        "required_acknowledgements": list(preview.required_acknowledgements),
                        "compiler_version": preview.compiler_version,
                        "policy_version": preview.policy_version,
                    })
                if method == "GET" and len(parts) == 5 and parts[4] == "approval":
                    return self._safe(200, self._entry_approval_bridge_api.get_approval(subject, draft_id))
                if method == "POST" and len(parts) == 5 and parts[4] == "approve":
                    return self._safe(202, self._entry_approval_bridge_api.approve(subject, draft_id, self._e4_payload(request)))
                if method == "POST" and len(parts) == 6 and parts[4] == "approval" and parts[5] == "reconcile":
                    return self._safe(202, self._entry_approval_bridge_api.reconcile(subject, draft_id, self._e4_payload(request, reconcile=True)))
            raise ProductApiRejected("UNSUPPORTED_ROUTE")
        if method == "GET" and parts == ["factory-home", "status"]:
            return self._safe(200, self._factory_home_read_model.factory_status(actor_scope))
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

    @staticmethod
    def _draft_subject(request: ProductApiRequest) -> str:
        subject = request.verified_identity_subject
        if not subject or request.actor.actor_type.value != "user" or request.actor.actor_id != subject:
            raise ProductApiRejected("ENTRY_DRAFT_IDENTITY_REQUIRED")
        return subject

    @staticmethod
    def _draft_payload(request: ProductApiRequest, *, require_content: bool = False) -> Mapping[str, Any]:
        body = dict(request.body)
        key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")
        payload = {"idempotency_key": key, "reason": body.get("reason"), "expected_version": body.get("expected_version")}
        if require_content or request.path.strip("/") == "production-drafts":
            payload["title"] = body.get("title")
            payload["raw_input"] = body.get("raw_input") or body.get("idea")
        if not isinstance(payload["idempotency_key"], str) or not isinstance(payload["reason"], str):
            raise ProductApiRejected("ENTRY_DRAFT_VALIDATION_FAILED")
        if request.path.strip("/") != "production-drafts" and (not isinstance(payload["expected_version"], int) or payload["expected_version"] < 1):
            raise ProductApiRejected("ENTRY_DRAFT_VALIDATION_FAILED")
        return payload

    @staticmethod
    def _e3_payload(request: ProductApiRequest, code: str) -> Mapping[str, Any]:
        body = dict(request.body)
        allowed = {"idempotency_key", "reason", "expected_version"}
        if set(body) - allowed:
            raise ProductApiRejected(code)
        key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")
        reason = body.get("reason")
        expected = body.get("expected_version")
        if not isinstance(key, str) or not key.strip() or not isinstance(reason, str) or not reason.strip() or not isinstance(expected, int) or expected < 0:
            raise ProductApiRejected(code)
        return {"idempotency_key": key, "reason": reason, "expected_version": expected}

    @staticmethod
    def _e4_payload(request: ProductApiRequest, reconcile: bool = False) -> Mapping[str, Any]:
        body = dict(request.body)
        allowed = {"reason", "idempotency_key", "correlation_id"} if reconcile else {"reason", "idempotency_key", "expected_draft_version", "master_plan_id", "expected_plan_version", "plan_revision_id", "approved_plan_content_hash", "proposal_revision_id", "proposal_content_hash", "compiled_blueprint_hash", "acknowledgements", "correlation_id"}
        if set(body) - allowed:
            raise ProductApiRejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if not isinstance(key, str) or not key.strip() or not isinstance(body.get("reason"), str) or not body["reason"].strip():
            raise ProductApiRejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        body["idempotency_key"] = key
        if not reconcile and (not isinstance(body.get("expected_draft_version"), int) or not isinstance(body.get("expected_plan_version"), int) or not isinstance(body.get("acknowledgements"), list)):
            raise ProductApiRejected("ENTRY_APPROVAL_SCHEMA_INVALID")
        return body

    @staticmethod
    def _understanding_payload(request: ProductApiRequest) -> Mapping[str, Any]:
        body = dict(request.body)
        key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")
        expected = body.get("expected_version")
        reason = body.get("reason")
        if not isinstance(key, str) or not isinstance(reason, str) or not isinstance(expected, int) or expected < 0:
            raise ProductApiRejected("E2_UNDERSTANDING_VALIDATION_FAILED")
        return {"idempotency_key": key, "reason": reason, "expected_version": expected}
    @staticmethod
    def _project_command_payload(request: ProductApiRequest) -> Mapping[str, Any]:
        body = dict(request.body)
        forbidden = {"actor", "requested_by", "project_id", "command_type", "executor"}
        if forbidden.intersection(body):
            raise ProductApiRejected("E11_COMMAND_CLIENT_AUTHORITY_FIELD_FORBIDDEN")
        command_id = body.get("command_id")
        idempotency_key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")
        expected_version = body.get("expected_version")
        reason = body.get("reason")
        if not isinstance(command_id, str) or not command_id.strip() or not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ProductApiRejected("E11_COMMAND_METADATA_MISSING")
        if not isinstance(expected_version, int) or expected_version < 0:
            raise ProductApiRejected("E11_COMMAND_EXPECTED_VERSION_INVALID")
        if not isinstance(reason, str) or not reason.strip():
            raise ProductApiRejected("E11_COMMAND_REASON_REQUIRED")
        authorization_ref = body.get("authorization_ref", "")
        if not isinstance(authorization_ref, str):
            raise ProductApiRejected("E11_COMMAND_AUTHORIZATION_REF_INVALID")
        return {
            "command_id": command_id.strip(),
            "expected_version": expected_version,
            "idempotency_key": idempotency_key.strip(),
            "reason": reason.strip(),
            "authorization_ref": authorization_ref.strip(),
        }

    def _safe(self, status_code: int, body: Mapping[str, Any]) -> ProductApiResponse:
        ensure_safe_response(body)
        return ProductApiResponse(status_code=status_code, body=body)
