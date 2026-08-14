from dataclasses import dataclass
from typing import Mapping

from hermes_runtime.domain.secret_handles import SecretBoundaryRejected, SecretHandle, secret_hash


@dataclass(frozen=True)
class VaultKv2Config:
    mount_point: str = "secret"
    metadata_prefix: str = "hermes/metadata"
    value_prefix: str = "hermes/values"


class VaultKv2SecretManager:
    def __init__(self, client, config: VaultKv2Config) -> None:
        self._client = client
        self._config = config

    def register(self, handle_id: str, secret_value: str, scope: str, metadata: Mapping[str, str]) -> SecretHandle:
        if not handle_id or "/" in handle_id or ".." in handle_id:
            raise SecretBoundaryRejected("SECRET_HANDLE_UNSAFE")
        digest = secret_hash(secret_value)
        handle = SecretHandle(
            handle_id=handle_id,
            provider="vault-kv2",
            scope=scope,
            secret_hash=digest,
            metadata=dict(metadata),
        )
        self._client.secrets.kv.v2.create_or_update_secret(
            mount_point=self._config.mount_point,
            path=f"{self._config.value_prefix}/{handle_id}",
            secret={"value": secret_value},
        )
        self._client.secrets.kv.v2.create_or_update_secret(
            mount_point=self._config.mount_point,
            path=f"{self._config.metadata_prefix}/{handle_id}",
            secret={
                "provider": handle.provider,
                "scope": handle.scope,
                "secret_hash": handle.secret_hash,
                "metadata": dict(handle.metadata),
            },
        )
        return handle

    def get_metadata(self, handle_id: str) -> SecretHandle:
        response = self._client.secrets.kv.v2.read_secret_version(
            mount_point=self._config.mount_point,
            path=f"{self._config.metadata_prefix}/{handle_id}",
        )
        data = response["data"]["data"]
        return SecretHandle(
            handle_id=handle_id,
            provider=data["provider"],
            scope=data["scope"],
            secret_hash=data["secret_hash"],
            metadata=dict(data.get("metadata", {})),
        )

    def resolve_for_execution(self, handle_id: str, *, authorized_execution: bool) -> str:
        if not authorized_execution:
            raise SecretBoundaryRejected("SECRET_RESOLUTION_UNAUTHORIZED")
        response = self._client.secrets.kv.v2.read_secret_version(
            mount_point=self._config.mount_point,
            path=f"{self._config.value_prefix}/{handle_id}",
        )
        return response["data"]["data"]["value"]
