import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from hermes_runtime.domain.human_gate import AuthorizationAssertion, HumanGateRejected


IDENTITY_ASSERTION_HASH_VERSION = "identity-assertion-hash/1.0"


@dataclass(frozen=True)
class IdentityAssertionInput:
    issuer: str
    subject: str
    role: str
    project_id: str
    task_id: Optional[str]
    gate_request_id: str
    action_scope: str
    valid_from: str
    valid_until: str
    revoked: bool = False


def assertion_hash(payload: IdentityAssertionInput) -> str:
    material = {
        "hash_version": IDENTITY_ASSERTION_HASH_VERSION,
        "issuer": payload.issuer,
        "subject": payload.subject,
        "role": payload.role,
        "project_id": payload.project_id,
        "task_id": payload.task_id,
        "gate_request_id": payload.gate_request_id,
        "action_scope": payload.action_scope,
        "valid_from": payload.valid_from,
        "valid_until": payload.valid_until,
        "revoked": payload.revoked,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def to_authorization_assertion(assertion_id: str, payload: IdentityAssertionInput) -> AuthorizationAssertion:
    return AuthorizationAssertion(
        assertion_id=assertion_id,
        issuer=payload.issuer,
        subject=payload.subject,
        role=payload.role,
        project_id=payload.project_id,
        task_id=payload.task_id,
        gate_request_id=payload.gate_request_id,
        action_scope=payload.action_scope,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        assertion_hash=assertion_hash(payload),
        revoked=payload.revoked,
    )


def validate_assertion_window(assertion: AuthorizationAssertion, now: str) -> None:
    if assertion.revoked:
        raise HumanGateRejected("GATE_APPROVER_UNAUTHORIZED")
    if assertion.valid_from and now < assertion.valid_from:
        raise HumanGateRejected("GATE_ASSERTION_NOT_YET_VALID")
    if assertion.valid_until and now >= assertion.valid_until:
        raise HumanGateRejected("GATE_ASSERTION_EXPIRED")
