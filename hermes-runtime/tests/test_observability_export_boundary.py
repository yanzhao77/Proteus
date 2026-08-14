import unittest

from hermes_runtime.application.observability import ObservabilityExportService
from hermes_runtime.domain.observability import (
    ObservabilityRecord,
    ObservabilityRejected,
    missing_link,
    to_export_envelope,
)
from hermes_runtime.infrastructure.local_observability import LocalObservabilityExporter


class ObservabilityExportBoundaryTests(unittest.TestCase):
    def test_export_redacts_unsafe_fields_and_preserves_missing_link(self):
        record = ObservabilityRecord(
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id="",
            name="decision.explain.query",
            timestamp="2026-08-14T00:00:00Z",
            attributes={"component": "explain", "token": "plain-token", "nested": {"raw_stdout": "noise"}},
            events=({"name": "link-check", "secret_value": "secret"},),
            metrics={"latency_ms": 1.5},
            source_refs=({"type": "decision", "id": "decision-1"},),
            missing_links=(missing_link("evidence", "evidence-missing", "retention redacted raw content"),),
        )
        envelope = to_export_envelope(record)
        self.assertEqual("[REDACTED]", envelope["attributes"]["token"])
        self.assertEqual("[REDACTED]", envelope["attributes"]["nested"]["raw_stdout"])
        self.assertEqual("[REDACTED]", envelope["events"][0]["secret_value"])
        self.assertEqual("MISSING", "MISSING" if envelope["missing_links"] else "")

    def test_metrics_and_traces_cannot_authorize_actions(self):
        with self.assertRaisesRegex(ObservabilityRejected, "OBSERVABILITY_CANNOT_AUTHORIZE"):
            to_export_envelope(
                ObservabilityRecord(
                    trace_id="trace-1",
                    span_id="span-1",
                    parent_span_id="",
                    name="unsafe",
                    timestamp="2026-08-14T00:00:00Z",
                    attributes={"gate_approved": True},
                    metrics={"score": 1.0},
                )
            )

    def test_local_exporter_is_backend_optional(self):
        exporter = LocalObservabilityExporter()
        service = ObservabilityExportService(exporter)
        result = service.export_record(
            ObservabilityRecord(
                trace_id="trace-1",
                span_id="span-1",
                parent_span_id="",
                name="api.request",
                timestamp="2026-08-14T00:00:00Z",
                attributes={"route": "/projects/project-1/status"},
                metrics={"duration_ms": 2.0},
            )
        )
        self.assertEqual("EXPORTED", result["status"])
        self.assertEqual("otel-compatible-local/1.0", exporter.envelopes[0]["schema"])


if __name__ == "__main__":
    unittest.main()
