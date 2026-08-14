import hashlib
from dataclasses import dataclass
from typing import Mapping


class SecretBoundaryRejected(ValueError):
    pass


@dataclass(frozen=True)
class SecretHandle:
    handle_id: str
    provider: str
    scope: str
    secret_hash: str
    metadata: Mapping[str, str]


def secret_hash(secret_value: str) -> str:
    if not secret_value:
        raise SecretBoundaryRejected("SECRET_VALUE_REQUIRED")
    return "sha256:" + hashlib.sha256(secret_value.encode("utf-8")).hexdigest()


def assert_handle_only(payload: Mapping[str, object]) -> None:
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in {"secret", "secret_value", "password", "token", "api_key"} and value:
            raise SecretBoundaryRejected("SECRET_VALUE_FORBIDDEN")
