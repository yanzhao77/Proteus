from typing import Dict, Mapping

from hermes_runtime.domain.secret_handles import SecretBoundaryRejected, SecretHandle, secret_hash


class LocalSecretHandleProvider:
    def __init__(self, provider: str = "local-test") -> None:
        self._provider = provider
        self._handles: Dict[str, SecretHandle] = {}
        self._secret_values: Dict[str, str] = {}

    def register(self, handle_id: str, secret_value: str, scope: str, metadata: Mapping[str, str]) -> SecretHandle:
        if handle_id in self._handles:
            raise SecretBoundaryRejected("SECRET_HANDLE_ALREADY_EXISTS")
        handle = SecretHandle(
            handle_id=handle_id,
            provider=self._provider,
            scope=scope,
            secret_hash=secret_hash(secret_value),
            metadata=dict(metadata),
        )
        self._handles[handle_id] = handle
        self._secret_values[handle_id] = secret_value
        return handle

    def get_metadata(self, handle_id: str) -> SecretHandle:
        return self._handles[handle_id]

    def assert_no_registered_secret_value(self, payload: object) -> None:
        text = repr(payload)
        for value in self._secret_values.values():
            if value and value in text:
                raise SecretBoundaryRejected("SECRET_VALUE_FORBIDDEN")
