from typing import Any, Mapping, Protocol

from hermes_runtime.domain.observability import ObservabilityRecord, to_export_envelope


class ObservabilityExporter(Protocol):
    def export(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class ObservabilityExportService:
    def __init__(self, exporter: ObservabilityExporter) -> None:
        self._exporter = exporter

    def export_record(self, record: ObservabilityRecord) -> Mapping[str, Any]:
        envelope = to_export_envelope(record)
        return self._exporter.export(envelope)
