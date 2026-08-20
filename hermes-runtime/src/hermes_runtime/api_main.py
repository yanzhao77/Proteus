import json
import os

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.entry_draft_api import UnavailableEntryDraftApi
from hermes_runtime.application.entry_understanding_api import UnavailableEntryUnderstandingApi
from hermes_runtime.application.entry_proposal_master_plan_api import UnavailableEntryProposalMasterPlanApi
from hermes_runtime.application.entry_approval_bridge import UnavailableEntryApprovalBridgeApi
from hermes_runtime.infrastructure.understanding_provider_registry import build_understanding_producer_from_env
from hermes_runtime.application.readiness import StaticReadinessCheck
from hermes_runtime.application.factory_home_read_model import UnavailableFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_factory_home_read_model import DenyAllActorProjectScope, PostgresCreatorActorProjectScope, PostgresFactoryHomeReadModel
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore
from hermes_runtime.infrastructure.postgres_entry_understanding import PostgresEntryUnderstandingStore
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import PostgresEntryProposalMasterPlanStore
from hermes_runtime.infrastructure.postgres_entry_approval_bridge import PostgresEntryApprovalBridgeStore
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
    factory_home_read_model = (
        PostgresFactoryHomeReadModel(database_url, PostgresCreatorActorProjectScope(database_url))
        if database_url and oidc_verifier
        else UnavailableFactoryHomeReadModel()
    )
    entry_draft_api = PostgresEntryDraftStore(database_url) if database_url and oidc_verifier else UnavailableEntryDraftApi()
    # No generic live LLM/provider is an established repository capability; remain fail-closed.
    entry_understanding_api = PostgresEntryUnderstandingStore(database_url, build_understanding_producer_from_env()) if database_url and oidc_verifier else UnavailableEntryUnderstandingApi()
    entry_proposal_master_plan_api = PostgresEntryProposalMasterPlanStore(database_url) if database_url and oidc_verifier else UnavailableEntryProposalMasterPlanApi()
    entry_approval_bridge_api = PostgresEntryApprovalBridgeStore(database_url) if database_url and oidc_verifier else UnavailableEntryApprovalBridgeApi()
    return create_app(
        ProductApiFacade(EmptyReadModel(), RejectingGateway(), factory_home_read_model, entry_draft_api, entry_understanding_api, entry_proposal_master_plan_api, entry_approval_bridge_api),
        StaticReadinessCheck(database_ready=bool(database_url)),
        allowed_cors_origins=origins,
        oidc_verifier=oidc_verifier,
    )


app = build_app()
