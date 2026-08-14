from contextlib import asynccontextmanager
from typing import Any, Mapping, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.readiness import ReadinessCheck, StaticReadinessCheck
from hermes_runtime.application.human_gate_ui import HumanGateUiRenderer
from hermes_runtime.domain.models import Actor, ActorType
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
    app.state.accepting_requests = True
    app.state.max_body_bytes = max_body_bytes

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins or [],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

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

    return app


def _dispatch(request: Request, method: str, path: str, body: Mapping[str, Any]):
    request_id = request.headers.get("X-Request-ID", "req-missing")
    try:
        actor = _actor_from_headers_or_body(request, body)
        response = request.app.state.product_api.handle(
            ProductApiRequest(
                method=method,
                path=path,
                headers=dict(request.headers),
                body=body,
                actor=actor,
            )
        )
        return JSONResponse(
            status_code=response.status_code,
            content={"data": response.body, "error": None, "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except ProductApiRejected as exc:
        return _error(str(exc).split(":", 1)[0], 400, request_id, "request rejected")
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
