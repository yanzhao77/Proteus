from contextlib import asynccontextmanager
from typing import Any, Mapping, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.readiness import ReadinessCheck, StaticReadinessCheck
from hermes_runtime.application.human_gate_ui import HumanGateUiRenderer
from hermes_runtime.application.factory_workspace_ui import FactoryWorkspaceRenderer
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.oidc import OidcRejected, OidcTokenVerifier
from hermes_runtime.domain.entry_draft import EntryDraftRejected
from hermes_runtime.domain.entry_understanding import EntryUnderstandingRejected, EntryUnderstandingValidationError
from hermes_runtime.domain.entry_proposal_master_plan import EntryE3Rejected
from hermes_runtime.infrastructure.postgres_entry_draft import EntryDraftStoreUnavailable
from hermes_runtime.infrastructure.postgres_entry_understanding import EntryUnderstandingStoreUnavailable
from hermes_runtime.infrastructure.postgres_entry_proposal_master_plan import EntryProposalMasterPlanStoreUnavailable
from hermes_runtime.domain.product_api import ProductApiRejected, ProductApiRequest


DEFAULT_MAX_BODY_BYTES = 64 * 1024


class ActorDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class GateDecisionDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    actor: ActorDto
    reason: str = Field(min_length=1)
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    gate_decision_id: str = Field(default="", max_length=128)
    authorization_ref: str = Field(default="", max_length=256)
    assertion_id: str = Field(default="", max_length=128)
    assertion_hash: str = Field(default="", max_length=256)


def create_app(
    product_api: ProductApiFacade,
    readiness: Optional[ReadinessCheck] = None,
    *,
    allowed_cors_origins: Optional[list] = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    oidc_verifier: Optional[OidcTokenVerifier] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.accepting_requests = True
        yield
        app.state.accepting_requests = False

    app = FastAPI(
        title="Hermes Runtime API",
        version="p5.1",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.product_api = product_api
    app.state.readiness = readiness or StaticReadinessCheck()
    app.state.gate_ui = HumanGateUiRenderer()
    app.state.factory_workspace_ui = FactoryWorkspaceRenderer()
    app.state.accepting_requests = True
    app.state.max_body_bytes = max_body_bytes
    app.state.oidc_verifier = oidc_verifier

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins or [],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, _exc: RequestValidationError):
        return _error("VALIDATION_FAILED", 400, request.headers.get("X-Request-ID", "req-missing"), "request rejected")

    @app.middleware("http")
    async def request_bounds_and_errors(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "req-missing")
        try:
            if not app.state.accepting_requests:
                return _error("SERVICE_STOPPING", 503, request_id, "service is stopping")
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > app.state.max_body_bytes:
                return _error("REQUEST_TOO_LARGE", 413, request_id, "request body too large")
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            return _error("INTERNAL_ERROR", 500, request_id, "internal server error")

    @app.get("/livez")
    def livez():
        return {"status": "LIVE"}

    @app.get("/readyz")
    def readyz():
        result = app.state.readiness.check()
        status = 200 if result.get("ready") else 503
        return JSONResponse(status_code=status, content=result)

    @app.get("/projects/{project_id}/status")
    def project_status(project_id: str, request: Request):
        return _dispatch(request, "GET", f"/projects/{project_id}/status", {})

    @app.get("/decisions/{decision_id}/explain")
    def decision_explain(decision_id: str, request: Request):
        return _dispatch(request, "GET", f"/decisions/{decision_id}/explain", {})

    @app.get("/human-gates/{gate_request_id}")
    def human_gate(gate_request_id: str, request: Request):
        return _dispatch(request, "GET", f"/human-gates/{gate_request_id}", {})

    @app.get("/ui/human-gates", response_class=HTMLResponse)
    def human_gate_inbox(request: Request):
        response = request.app.state.product_api.handle(
            ProductApiRequest(
                method="GET",
                path="/human-gates/gate-1",
                headers=dict(request.headers),
                body={},
                actor=_actor_from_headers_or_body(request, {}),
            )
        )
        return HTMLResponse(request.app.state.gate_ui.render_inbox((response.body,)))

    @app.get("/ui/human-gates/{gate_request_id}", response_class=HTMLResponse)
    def human_gate_detail(gate_request_id: str, request: Request):
        response = request.app.state.product_api.handle(
            ProductApiRequest(
                method="GET",
                path=f"/human-gates/{gate_request_id}",
                headers=dict(request.headers),
                body={},
                actor=_actor_from_headers_or_body(request, {}),
            )
        )
        return HTMLResponse(request.app.state.gate_ui.render_detail(response.body))

    @app.post("/human-gates/{gate_request_id}/decisions")
    def submit_gate_decision(
        gate_request_id: str,
        body: GateDecisionDto,
        request: Request,
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(status_code=415, detail="CONTENT_TYPE_UNSUPPORTED")
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="API_IDEMPOTENCY_KEY_MISSING")
        payload = body.model_dump()
        payload["idempotency_key"] = idempotency_key
        return _dispatch(request, "POST", f"/human-gates/{gate_request_id}/decisions", payload)

    @app.get("/projects/{project_id}/reconcile-findings")
    def reconcile_findings(project_id: str, request: Request):
        return _dispatch(request, "GET", f"/projects/{project_id}/reconcile-findings", {})

    @app.get("/docker-processes/{process_id}/observations")
    def docker_observations(process_id: str, request: Request):
        return _dispatch(request, "GET", f"/docker-processes/{process_id}/observations", {})

    @app.get("/factory-home")
    def factory_home_snapshot(request: Request):
        return _factory_dispatch(request, "/factory-home")

    @app.get("/factory-home/productions")
    def factory_home_productions(request: Request):
        return _factory_dispatch(request, "/factory-home/productions")

    @app.get("/factory-home/productions/{project_id}")
    def factory_home_production_snapshot(project_id: str, request: Request):
        return _factory_dispatch(request, f"/factory-home/productions/{project_id}")

    @app.get("/factory-home/gates")
    def factory_home_gates(request: Request):
        return _factory_dispatch(request, "/factory-home/gates")

    @app.get("/factory-home/drafts")
    def factory_home_drafts(request: Request):
        return _factory_dispatch(request, "/factory-home/drafts")

    @app.get("/factory-home/status")
    def factory_home_status(request: Request):
        return _factory_dispatch(request, "/factory-home/status")

    @app.get("/production-drafts")
    def production_drafts(request: Request):
        return _draft_dispatch(request, "GET", "/production-drafts", {})

    @app.get("/production-drafts/{draft_id}")
    def production_draft(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}", {})

    @app.post("/production-drafts")
    async def create_production_draft(request: Request):
        return _draft_dispatch(request, "POST", "/production-drafts", await _json_body(request))

    @app.post("/production-drafts/{draft_id}/revisions")
    async def revise_production_draft(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/revisions", await _json_body(request))

    @app.post("/production-drafts/{draft_id}/submit")
    async def submit_production_draft(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/submit", await _json_body(request))

    @app.post("/production-drafts/{draft_id}/archive")
    async def archive_production_draft(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/archive", await _json_body(request))

    @app.get("/production-drafts/{draft_id}/understanding")
    def production_draft_understanding(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/understanding", {})

    @app.get("/production-drafts/{draft_id}/understanding/revisions")
    def production_draft_understanding_revisions(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/understanding/revisions", {})

    @app.get("/production-drafts/{draft_id}/understanding/clarifications")
    def production_draft_understanding_clarifications(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/understanding/clarifications", {})

    @app.post("/production-drafts/{draft_id}/understanding")
    async def generate_production_draft_understanding(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/understanding", await _json_body(request))

    @app.post("/production-drafts/{draft_id}/understanding/clarifications/{clarification_id}/answer")
    async def answer_production_draft_clarification(draft_id: str, clarification_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/understanding/clarifications/{clarification_id}/answer", await _json_body(request))

    @app.get("/production-drafts/{draft_id}/proposal")
    def production_draft_proposal(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/proposal", {})

    @app.get("/production-drafts/{draft_id}/proposal/revisions")
    def production_draft_proposal_revisions(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/proposal/revisions", {})

    @app.post("/production-drafts/{draft_id}/proposal")
    async def generate_production_draft_proposal(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/proposal", await _json_body(request))

    @app.get("/production-drafts/{draft_id}/proposal/master-plan")
    def production_draft_master_plan(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/proposal/master-plan", {})

    @app.get("/production-drafts/{draft_id}/proposal/master-plan/revisions")
    def production_draft_master_plan_revisions(draft_id: str, request: Request):
        return _draft_dispatch(request, "GET", f"/production-drafts/{draft_id}/proposal/master-plan/revisions", {})

    @app.post("/production-drafts/{draft_id}/proposal/master-plan")
    async def generate_production_draft_master_plan(draft_id: str, request: Request):
        return _draft_dispatch(request, "POST", f"/production-drafts/{draft_id}/proposal/master-plan", await _json_body(request))

    @app.get("/home", response_class=HTMLResponse)
    def factory_home(request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_home())

    @app.get("/new", response_class=HTMLResponse)
    def factory_new(request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_new())

    @app.get("/drafts/{draft_id}", response_class=HTMLResponse)
    def factory_draft(draft_id: str, request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_draft(draft_id))

    @app.get("/productions", response_class=HTMLResponse)
    def factory_productions(request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_productions())

    @app.get("/productions/{production_id}", response_class=HTMLResponse)
    def factory_production(production_id: str, request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_production(production_id))

    @app.get("/gates", response_class=HTMLResponse)
    def factory_gates(request: Request):
        return HTMLResponse(request.app.state.factory_workspace_ui.render_gates())

    return app


async def _json_body(request: Request) -> Mapping[str, Any]:
    try:
        value = await request.json()
    except Exception:
        raise ProductApiRejected("ENTRY_DRAFT_VALIDATION_FAILED")
    if not isinstance(value, Mapping):
        raise ProductApiRejected("ENTRY_DRAFT_VALIDATION_FAILED")
    return value


def _draft_dispatch(request: Request, method: str, path: str, body: Mapping[str, Any]):
    return _verified_dispatch(request, method, path, body)


def _factory_dispatch(request: Request, path: str):
    return _verified_dispatch(request, "GET", path, {})


def _verified_dispatch(request: Request, method: str, path: str, body: Mapping[str, Any]):
    request_id = request.headers.get("X-Request-ID", "req-missing")
    verifier = request.app.state.oidc_verifier
    if verifier is None:
        return _error("FACTORY_HOME_IDENTITY_UNAVAILABLE", 503, request_id, "factory home identity unavailable")
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        return _error("FACTORY_HOME_AUTH_REQUIRED", 401, request_id, "factory home authentication required")
    try:
        identity = verifier.verify(authorization[7:].strip())
    except OidcRejected:
        return _error("FACTORY_HOME_AUTH_INVALID", 401, request_id, "factory home authentication rejected")
    header_actor_id = request.headers.get("X-Hermes-Actor-ID")
    header_actor_type = request.headers.get("X-Hermes-Actor-Type")
    if (header_actor_id and header_actor_id != identity.subject) or (header_actor_type and header_actor_type != "user"):
        return _error("FACTORY_HOME_ACTOR_MISMATCH", 401, request_id, "factory home actor mismatch")
    return _dispatch(request, method, path, body, actor_override=identity.actor, verified_identity_subject=identity.subject)


def _dispatch(
    request: Request,
    method: str,
    path: str,
    body: Mapping[str, Any],
    *,
    actor_override: Optional[Actor] = None,
    verified_identity_subject: str = "",
):
    request_id = request.headers.get("X-Request-ID", "req-missing")
    try:
        actor = actor_override or _actor_from_headers_or_body(request, body)
        response = request.app.state.product_api.handle(
            ProductApiRequest(
                method=method,
                path=path,
                headers=dict(request.headers),
                body=body,
                actor=actor,
                verified_identity_subject=verified_identity_subject,
            )
        )
        return JSONResponse(
            status_code=response.status_code,
            content={"data": response.body, "error": None, "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except ProductApiRejected as exc:
        code = str(exc).split(":", 1)[0]
        status = 409 if code in {"ENTRY_DRAFT_VERSION_CONFLICT", "ENTRY_DRAFT_IDEMPOTENCY_CONFLICT"} else 422 if code == "ENTRY_DRAFT_VALIDATION_FAILED" else 400
        return _error(code, status, request_id, "request rejected")
    except EntryDraftRejected as exc:
        code = str(exc).split(":", 1)[0]
        status = 409 if code in {"ENTRY_DRAFT_VERSION_CONFLICT", "ENTRY_DRAFT_IDEMPOTENCY_CONFLICT", "ENTRY_DRAFT_TRANSITION_FORBIDDEN"} else 404 if code == "ENTRY_DRAFT_NOT_AVAILABLE" else 422
        return _error(code, status, request_id, "request rejected")
    except EntryDraftStoreUnavailable:
        return _error("ENTRY_DRAFT_AUTHORITY_UNAVAILABLE", 503, request_id, "draft authority unavailable")
    except EntryUnderstandingValidationError as exc:
        return _error(str(exc).split(":", 1)[0], 422, request_id, "request rejected")
    except EntryUnderstandingRejected as exc:
        code = str(exc).split(":", 1)[0]
        status = 409 if code in {"E2_UNDERSTANDING_VERSION_CONFLICT", "E2_UNDERSTANDING_IDEMPOTENCY_CONFLICT", "E2_CLARIFICATION_NOT_OPEN", "ENTRY_UNDERSTANDING_STALE_SOURCE_REVISION"} else 404 if code in {"E2_UNDERSTANDING_NOT_AVAILABLE", "E2_CLARIFICATION_NOT_AVAILABLE", "ENTRY_DRAFT_NOT_AVAILABLE"} else 503 if code in {"ENTRY_UNDERSTANDING_PROVIDER_UNAVAILABLE", "ENTRY_UNDERSTANDING_CONFIGURATION_ERROR", "ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT", "ENTRY_UNDERSTANDING_PROVIDER_CONNECTION_ERROR", "ENTRY_UNDERSTANDING_PROVIDER_RATE_LIMITED", "ENTRY_UNDERSTANDING_PROVIDER_SERVER_ERROR"} else 502 if code in {"ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED", "ENTRY_UNDERSTANDING_PROVIDER_BAD_REQUEST", "ENTRY_UNDERSTANDING_PROVIDER_INVALID_RESPONSE", "ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED"} else 422
        return _error(code, status, request_id, "request rejected")
    except EntryUnderstandingStoreUnavailable:
        return _error("E2_UNDERSTANDING_AUTHORITY_UNAVAILABLE", 503, request_id, "understanding authority unavailable")
    except EntryE3Rejected as exc:
        code = str(exc).split(":", 1)[0]
        status = 409 if code.endswith("_VERSION_CONFLICT") or code.endswith("_IDEMPOTENCY_CONFLICT") or code.endswith("_SOURCE_STALE") else 404 if code in {"ENTRY_PROPOSAL_NOT_AVAILABLE", "ENTRY_PLAN_NOT_AVAILABLE"} else 422
        return _error(code, status, request_id, "request rejected")
    except EntryProposalMasterPlanStoreUnavailable as exc:
        code = str(exc).split(":", 1)[0]
        return _error(code, 503, request_id, "E3 authority unavailable")
    except ValueError:
        return _error("VALIDATION_FAILED", 400, request_id, "request rejected")


def _actor_from_headers_or_body(request: Request, body: Mapping[str, Any]) -> Actor:
    actor_payload = body.get("actor") if isinstance(body, Mapping) else None
    if isinstance(actor_payload, Mapping):
        actor_type = actor_payload.get("type", "user")
        actor_id = actor_payload.get("id", "")
    else:
        actor_type = request.headers.get("X-Hermes-Actor-Type", "user")
        actor_id = request.headers.get("X-Hermes-Actor-ID", "anonymous")
    return Actor(ActorType(actor_type), actor_id)


def _error(code: str, status_code: int, request_id: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {
                "code": code,
                "message": message,
            },
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )
