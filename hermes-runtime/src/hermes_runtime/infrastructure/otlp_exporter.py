from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Mapping

import httpx

from hermes_runtime.domain.observability import (
    ObservabilityRecord,
    to_export_envelope,
    to_otlp_json_envelope,
)


@dataclass(frozen=True)
class OtlpExporterConfig:
    endpoint: str
    timeout_seconds: float = 2.0
    max_queue_size: int = 100


class OtlpExporter:
    def __init__(
        self,
        config: OtlpExporterConfig,
        client: Any = None,
        *,
        envelope_builder: Any = None,
        content_type: str = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._queue: Deque[Mapping[str, Any]] = deque()
        self._dropped = 0
        self._failed_exports = 0
        self._envelope_builder = envelope_builder or to_export_envelope
        self._content_type = content_type

    def enqueue(self, record: ObservabilityRecord) -> Mapping[str, object]:
        envelope = self._envelope_builder(record)
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
            kwargs: dict = {"json": envelope, "timeout": self._config.timeout_seconds}
            if self._content_type:
                kwargs["headers"] = {"Content-Type": self._content_type}
            response = self._client.post(self._config.endpoint, **kwargs)
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


class OtlpHttpJsonExporter(OtlpExporter):
    """Exporter that emits the OTLP/HTTP proto3 JSON wire format.

    This is the real wire-compatible variant used for the P5 production
    observability acceptance against an OpenTelemetry Collector. The local
    `otel-compatible-local/1.0` envelope remains the P4 default and is produced
    by the base `OtlpExporter` when no builder is supplied.
    """

    def __init__(self, config: OtlpExporterConfig, client: Any = None) -> None:
        super().__init__(
            config,
            client,
            envelope_builder=to_otlp_json_envelope,
            content_type="application/json",
        )
