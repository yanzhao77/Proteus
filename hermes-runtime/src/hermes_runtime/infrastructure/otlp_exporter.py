from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Mapping

import httpx

from hermes_runtime.domain.observability import ObservabilityRecord, to_export_envelope


@dataclass(frozen=True)
class OtlpExporterConfig:
    endpoint: str
    timeout_seconds: float = 2.0
    max_queue_size: int = 100


class OtlpExporter:
    def __init__(self, config: OtlpExporterConfig, client: Any = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._queue: Deque[Mapping[str, Any]] = deque()
        self._dropped = 0
        self._failed_exports = 0

    def enqueue(self, record: ObservabilityRecord) -> Mapping[str, object]:
        envelope = to_export_envelope(record)
        if len(self._queue) >= self._config.max_queue_size:
            self._dropped += 1
            return {"status": "DROPPED", "dropped": self._dropped}
        self._queue.append(envelope)
        return {"status": "QUEUED", "queue_size": len(self._queue)}

    def flush_once(self) -> Mapping[str, object]:
        if not self._queue:
            return {"status": "EMPTY", "exported": 0, "dropped": self._dropped}
        envelope = self._queue[0]
        try:
            response = self._client.post(self._config.endpoint, json=envelope, timeout=self._config.timeout_seconds)
            if getattr(response, "status_code", 500) >= 400:
                raise RuntimeError("OTLP_BACKEND_REJECTED")
            self._queue.popleft()
            return {"status": "EXPORTED", "exported": 1, "dropped": self._dropped}
        except Exception:
            self._failed_exports += 1
            return {
                "status": "EXPORT_FAILED",
                "exported": 0,
                "dropped": self._dropped,
                "failed_exports": self._failed_exports,
            }

    @property
    def stats(self) -> Mapping[str, int]:
        return {"queue_size": len(self._queue), "dropped": self._dropped, "failed_exports": self._failed_exports}
