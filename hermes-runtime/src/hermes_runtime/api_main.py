import json
import os

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.entry_draft_api import UnavailableEntryDraftApi
from hermes_runtime.application.entry_understanding_api import UnavailableEntryUnderstandingApi
from hermes_runtime.application.entry_proposal_master_plan_api import UnavailableEntryProposalMasterPlanApi
from hermes_runtime.application.entry_approval_bridge import UnavailableEntryApprovalBridgeApi
from hermes_runtime.application.entry_approval_bridge_saga import ApprovalBridgeSaga
from hermes_runtime.application.durable_approval_bridge_orchestrator import DurableApprovalBridgeOrchestrator
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.user_project_command_transport import (
    UnavailableUserProjectCommandTransport,
    UserProjectCommandTransport,
)
from hermes_runtime.application.human_gate_product import HumanGateProductFacade
from hermes_runtime.application.human_gates import HumanGateAuthority
from hermes_runtime.application.user_human_gate_transport import (
    UnavailableUserHumanGateTransport,
    UserHumanGateTransport,
)
from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore
from hermes_runtime.infrastructure.understanding_provider_registry import build_understanding_producer_from_env
from hermes_runtime.application.readiness import StaticReadinessCheck
from hermes_runtime.application.factory_home_read_model import UnavailableFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_factory_home_read_model import DenyAllActorProjectScope, PostgresCreatorActorProjectScope, PostgresFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_live_production_read_model import PostgresLiveProductionReadModel, UnavailableLiveProductionReadModel
from hermes_runtime.infrastructure.postgres_worker_control_plane_read_model import PostgresWorkerControlPlaneReadModel
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore
from hermes_runtime.infrastructure.postgres_entry_understanding import PostgresEntryUnderstandingStore
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
from hermes_runtime.infrastructure.postgres_entry_approval_bridge import PostgresEntryApprovalBridgeStore
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider
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


def _build_oidc_verifier():
    issuer = os.getenv("HERMES_OIDC_ISSUER", "").strip()
    audience = os.getenv("HERMES_OIDC_AUDIENCE", "").strip()
    raw_jwks = env_or_file("HERMES_OIDC_JWKS_JSON")
    if not issuer or not audience or not raw_jwks:
        return None
    try:
        jwks = json.loads(raw_jwks)
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            return None
        return OidcTokenVerifier(OidcConfig(issuer=issuer, audience=audience), StaticJwksProvider(jwks))
    except Exception:
        return None


def build_app():
    origins = [item for item in os.getenv("HERMES_CORS_ORIGINS", "").split(",") if item]
    database_url = env_or_file("HERMES_DATABASE_URL")
    oidc_verifier = _build_oidc_verifier()
    entry_draft_api = PostgresEntryDraftStore(database_url) if database_url and oidc_verifier else UnavailableEntryDraftApi()
    _creator_scope = PostgresCreatorActorProjectScope(database_url) if database_url and oidc_verifier else None
    factory_home_read_model = (
        PostgresFactoryHomeReadModel(database_url, _creator_scope, entry_draft_api)
        if _creator_scope else UnavailableFactoryHomeReadModel()
    )
    live_production_read_model = (
        PostgresLiveProductionReadModel(database_url, _creator_scope)
        if _creator_scope else UnavailableLiveProductionReadModel()
    )
    worker_control_plane_read_model = (
        PostgresWorkerControlPlaneReadModel(database_url, _creator_scope)
        if _creator_scope else None
    )
    # No generic live LLM/provider is an established repository capability; remain fail-closed.
    entry_understanding_api = PostgresEntryUnderstandingStore(database_url, build_understanding_producer_from_env()) if database_url and oidc_verifier else UnavailableEntryUnderstandingApi()
    entry_proposal_master_plan_api = UnavailableEntryProposalMasterPlanApi()
    user_project_command_transport = UnavailableUserProjectCommandTransport()
    user_human_gate_transport = UnavailableUserHumanGateTransport()
    if database_url and oidc_verifier:
        _bridge_store = PostgresEntryApprovalBridgeStore(database_url)
        entry_proposal_master_plan_api = PostgresEntryProposalMasterPlanStore(
            database_url, plan_materialization_guard=lambda plan_id: _bridge_store.is_master_plan_approved(plan_id)
        )
        _project_store = PostgresProjectStore(database_url)
        _control_plane = ControlPlane(_project_store)
        user_project_command_transport = UserProjectCommandTransport(
            _control_plane, _creator_scope, _project_store
        )
        _human_gate_store = PostgresHumanGateStore(database_url)
        _human_gate_product = HumanGateProductFacade(
            _human_gate_store, HumanGateAuthority(_human_gate_store), _human_gate_store
        )
        user_human_gate_transport = UserHumanGateTransport(
            _human_gate_store, _creator_scope, _human_gate_product
        )
        entry_approval_bridge_api = DurableApprovalBridgeOrchestrator(
            _bridge_store, ApprovalBridgeSaga(_control_plane, _bridge_store)
        )
    else:
        entry_approval_bridge_api = UnavailableEntryApprovalBridgeApi()
    session_cookie_secure = os.getenv("HERMES_SESSION_COOKIE_SECURE", "true").strip().lower() != "false"
    return create_app(
        ProductApiFacade(EmptyReadModel(), RejectingGateway(), factory_home_read_model, entry_draft_api, entry_understanding_api, entry_proposal_master_plan_api, entry_approval_bridge_api, live_production_read_model, user_project_command_transport, user_human_gate_transport, worker_control_plane_read_model),
        StaticReadinessCheck(database_ready=bool(database_url)),
        allowed_cors_origins=origins,
        oidc_verifier=oidc_verifier,
        session_cookie_secure=session_cookie_secure,
    )


app = build_app()
