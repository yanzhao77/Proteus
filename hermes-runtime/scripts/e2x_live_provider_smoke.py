#!/usr/bin/env python3
"""Non-production-only, Product-API-only E2.x live provider smoke runner.

The runner never reads provider credentials, never contacts a provider URL directly,
and performs no request until explicit non-production egress guards pass.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

SMOKE_PRECONDITION_NOT_MET = "SMOKE_PRECONDITION_NOT_MET"
SMOKE_API_NOT_READY = "SMOKE_API_NOT_READY"
SMOKE_PRODUCT_API_ERROR = "SMOKE_PRODUCT_API_ERROR"
SMOKE_RESPONSE_INVALID = "SMOKE_RESPONSE_INVALID"
SMOKE_REPLAY_MISMATCH = "SMOKE_REPLAY_MISMATCH"
SMOKE_PROVENANCE_MISSING = "SMOKE_PROVENANCE_MISSING"
SMOKE_TARGET_REJECTED = "SMOKE_TARGET_REJECTED"

FIXTURE_IDEA = (
    "Build a non-production task tracker API.\n"
    "Explicit requirements: create task, list tasks, complete task.\n"
    "Constraints: no external integrations and no production deployment."
)


class SmokeError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ProductApiTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None,
        timeout_seconds: float,
    ) -> tuple[int, Mapping[str, object]]: ...


class UrllibProductApiTransport:
    def request(self, method, url, headers, body, timeout_seconds):
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                return int(response.status), _json_object(payload)
        except urllib.error.HTTPError as error:
            payload = error.read().decode("utf-8", errors="replace")
            try:
                decoded = _json_object(payload)
            except SmokeError:
                decoded = {}
            return int(error.code), decoded
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SmokeError(SMOKE_PRODUCT_API_ERROR) from error


@dataclass(frozen=True)
class SmokeConfig:
    api_base_url: str
    oidc_token: str
    timeout_seconds: float = 20.0
    expected_provider: str = ""
    expected_model: str = ""


def _json_object(value: str) -> Mapping[str, object]:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as error:
        raise SmokeError(SMOKE_RESPONSE_INVALID) from error
    if not isinstance(decoded, Mapping):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    return decoded


def _nonempty_string(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def load_config_from_env(environ: Mapping[str, str] | None = None) -> SmokeConfig:
    env = os.environ if environ is None else environ
    if env.get("HERMES_E2X_SMOKE_ALLOW_EXTERNAL") != "true":
        raise SmokeError(SMOKE_PRECONDITION_NOT_MET)
    if env.get("HERMES_E2X_SMOKE_TARGET_CLASS") != "non-production":
        raise SmokeError(SMOKE_TARGET_REJECTED)
    base_url = _nonempty_string(env.get("HERMES_E2X_SMOKE_API_BASE_URL"))
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SmokeError(SMOKE_PRECONDITION_NOT_MET)
    token_file = _nonempty_string(env.get("HERMES_E2X_SMOKE_OIDC_TOKEN_FILE"))
    if not token_file:
        raise SmokeError(SMOKE_PRECONDITION_NOT_MET)
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SmokeError(SMOKE_PRECONDITION_NOT_MET) from error
    if not token:
        raise SmokeError(SMOKE_PRECONDITION_NOT_MET)
    return SmokeConfig(
        api_base_url=base_url.rstrip("/"),
        oidc_token=token,
        expected_provider=_nonempty_string(env.get("HERMES_E2X_SMOKE_EXPECTED_PROVIDER")),
        expected_model=_nonempty_string(env.get("HERMES_E2X_SMOKE_EXPECTED_MODEL")),
    )


def _headers(config: SmokeConfig, request_id: str, idempotency_key: str = "") -> Mapping[str, str]:
    headers = {
        "Authorization": "Bearer " + config.oidc_token,
        "Accept": "application/json",
        "X-Request-ID": request_id,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _stable_api_code(body: Mapping[str, object]) -> str:
    error = body.get("error")
    if isinstance(error, Mapping):
        code = _nonempty_string(error.get("code"))
        if code:
            return code
    return SMOKE_PRODUCT_API_ERROR


def _call(
    transport: ProductApiTransport,
    config: SmokeConfig,
    method: str,
    path: str,
    request_id: str,
    body: Mapping[str, object] | None = None,
    idempotency_key: str = "",
) -> Mapping[str, object]:
    status, response = transport.request(
        method,
        config.api_base_url + path,
        _headers(config, request_id, idempotency_key),
        body,
        config.timeout_seconds,
    )
    if status < 200 or status >= 300:
        raise SmokeError(_stable_api_code(response))
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    return data


def _ready(transport: ProductApiTransport, config: SmokeConfig, request_id: str) -> None:
    status, response = transport.request(
        "GET",
        config.api_base_url + "/readyz",
        _headers(config, request_id),
        None,
        config.timeout_seconds,
    )
    if status != 200:
        raise SmokeError(SMOKE_API_NOT_READY)
    if not isinstance(response.get("ready"), bool):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    if response["ready"] is not True:
        raise SmokeError(SMOKE_API_NOT_READY)


def _item(data: Mapping[str, object]) -> Mapping[str, object]:
    value = data.get("item")
    if not isinstance(value, Mapping):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    return value


def _list(data: Mapping[str, object]) -> list[Mapping[str, object]]:
    values = data.get("items")
    if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    return list(values)


def _nonnegative_optional(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _validate_understanding(
    item: Mapping[str, object],
    revisions: list[Mapping[str, object]],
    draft_id: str,
    source_revision_id: str,
    config: SmokeConfig,
) -> Mapping[str, object]:
    if _nonempty_string(item.get("state")) not in {"READY", "NEEDS_CLARIFICATION"}:
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    if not revisions:
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    latest = revisions[-1]
    if _nonempty_string(latest.get("source_draft_id")) != draft_id:
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    metadata = latest.get("provider_metadata")
    if not isinstance(metadata, Mapping):
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    if _nonempty_string(metadata.get("source_draft_revision_id")) != source_revision_id:
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    provider = _nonempty_string(metadata.get("provider"))
    model = _nonempty_string(metadata.get("model"))
    if not provider or not model:
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    if config.expected_provider and provider != config.expected_provider:
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    if config.expected_model and model != config.expected_model:
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    if metadata.get("prompt_version") != "v2" or metadata.get("schema_version") != "v1":
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    if not _nonnegative_optional(metadata.get("latency_ms")) or not _nonnegative_optional(metadata.get("retry_count")):
        raise SmokeError(SMOKE_PROVENANCE_MISSING)
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        if not _nonnegative_optional(metadata.get(field)):
            raise SmokeError(SMOKE_PROVENANCE_MISSING)
    return latest


def run_smoke(config: SmokeConfig, transport: ProductApiTransport, run_id: str | None = None) -> Mapping[str, object]:
    """Execute exactly one generate command plus one same-key replay over Product API."""
    run = run_id or uuid.uuid4().hex
    _ready(transport, config, "e2x-smoke-ready-" + run)

    create_key = "e2x-smoke-create-" + run
    draft_data = _call(
        transport,
        config,
        "POST",
        "/production-drafts",
        "e2x-smoke-create-" + run,
        {"title": "E2x non-production smoke " + run, "raw_input": FIXTURE_IDEA, "reason": "non-production e2x live provider smoke", "idempotency_key": create_key},
        create_key,
    )
    draft = _item(draft_data)
    draft_id = _nonempty_string(draft.get("draft_id"))
    draft_version = draft.get("version")
    revisions = draft.get("revisions")
    if not draft_id or not isinstance(draft_version, int) or draft_version < 1 or not isinstance(revisions, list) or not revisions or not isinstance(revisions[-1], Mapping):
        raise SmokeError(SMOKE_RESPONSE_INVALID)
    source_revision_id = _nonempty_string(revisions[-1].get("revision_id"))
    if not source_revision_id:
        raise SmokeError(SMOKE_RESPONSE_INVALID)

    submit_key = "e2x-smoke-submit-" + run
    submitted = _item(_call(
        transport,
        config,
        "POST",
        "/production-drafts/" + draft_id + "/submit",
        "e2x-smoke-submit-" + run,
        {"expected_version": draft_version, "reason": "submit non-production smoke draft", "idempotency_key": submit_key},
        submit_key,
    ))
    if submitted.get("state") != "SUBMITTED":
        raise SmokeError(SMOKE_RESPONSE_INVALID)

    generate_key = "e2x-smoke-generate-" + run
    generate_body = {"expected_version": 0, "reason": "generate one non-production smoke understanding", "idempotency_key": generate_key}
    generated = _item(_call(
        transport,
        config,
        "POST",
        "/production-drafts/" + draft_id + "/understanding",
        "e2x-smoke-generate-" + run,
        generate_body,
        generate_key,
    ))
    understanding_id = _nonempty_string(generated.get("understanding_id"))
    if not understanding_id:
        raise SmokeError(SMOKE_RESPONSE_INVALID)

    read_data = _call(transport, config, "GET", "/production-drafts/" + draft_id + "/understanding", "e2x-smoke-read-" + run)
    read_item = _item(read_data)
    revisions_before = _list(_call(transport, config, "GET", "/production-drafts/" + draft_id + "/understanding/revisions", "e2x-smoke-revisions-" + run))
    latest_before = _validate_understanding(read_item, revisions_before, draft_id, source_revision_id, config)

    replay = _item(_call(
        transport,
        config,
        "POST",
        "/production-drafts/" + draft_id + "/understanding",
        "e2x-smoke-replay-" + run,
        generate_body,
        generate_key,
    ))
    read_after = _item(_call(transport, config, "GET", "/production-drafts/" + draft_id + "/understanding", "e2x-smoke-read-replay-" + run))
    revisions_after = _list(_call(transport, config, "GET", "/production-drafts/" + draft_id + "/understanding/revisions", "e2x-smoke-revisions-replay-" + run))
    latest_after = _validate_understanding(read_after, revisions_after, draft_id, source_revision_id, config)
    if replay != generated or len(revisions_after) != len(revisions_before) or latest_after != latest_before:
        raise SmokeError(SMOKE_REPLAY_MISMATCH)

    metadata = latest_after["provider_metadata"]
    return {
        "status": "PASS",
        "target_class": "non-production",
        "draft_id": draft_id,
        "understanding_id": understanding_id,
        "understanding_revision_id": _nonempty_string(latest_after.get("understanding_revision_id")),
        "source_draft_revision_id": source_revision_id,
        "provider": metadata["provider"],
        "model": metadata["model"],
        "provider_request_id": metadata.get("provider_request_id"),
        "prompt_version": metadata["prompt_version"],
        "schema_version": metadata["schema_version"],
        "usage": {field: metadata.get(field) for field in ("input_tokens", "output_tokens", "total_tokens")},
        "latency_ms": metadata.get("latency_ms"),
        "retry_count": metadata.get("retry_count"),
        "replay": "same_authoritative_result_no_new_revision",
    }


def execute_from_env(environ: Mapping[str, str] | None = None, transport: ProductApiTransport | None = None) -> Mapping[str, object]:
    try:
        config = load_config_from_env(environ)
        return run_smoke(config, transport or UrllibProductApiTransport())
    except SmokeError as error:
        return {"status": "BLOCKED" if error.code in {SMOKE_PRECONDITION_NOT_MET, SMOKE_TARGET_REJECTED} else "FAIL", "code": error.code}


if __name__ == "__main__":
    result = execute_from_env()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if result.get("status") == "PASS" else 2)
