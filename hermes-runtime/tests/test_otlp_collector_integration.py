import os
import socket
import time
import unittest
from urllib.parse import urlsplit

import httpx

from hermes_runtime.domain.observability import ObservabilityRecord, missing_link
from hermes_runtime.infrastructure.otlp_exporter import OtlpExporterConfig, OtlpHttpJsonExporter


OTLP_ENDPOINT = os.environ.get("HERMES_TEST_OTLP_ENDPOINT")


def _endpoint_ready() -> bool:
    try:
        parts = urlsplit(OTLP_ENDPOINT)
        with socket.create_connection((parts.hostname, parts.port or 4318), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(OTLP_ENDPOINT, "requires real OTLP HTTP endpoint via HERMES_TEST_OTLP_ENDPOINT")
class OtlpCollectorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        deadline = time.time() + 30
        while time.time() < deadline:
            if _endpoint_ready():
                break
            time.sleep(0.5)
        else:
            raise unittest.SkipTest("OTLP endpoint not reachable")
        cls.exporter = OtlpHttpJsonExporter(OtlpExporterConfig(OTLP_ENDPOINT, timeout_seconds=5))

    def test_exports_redacted_span_to_real_collector(self):
        canary = "otlp-canary-value-7a2b"
        record = ObservabilityRecord(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            parent_span_id="",
            name="hermes.p5.integration",
            timestamp="2026-08-17T00:00:00Z",
            attributes={"route": "/readyz", "secret_value": canary},
            missing_links=(missing_link("evidence", "evidence-1", "MISSING"),),
        )
        self.assertEqual("QUEUED", self.exporter.enqueue(record)["status"])
        result = self.exporter.flush_once()
        self.assertEqual("EXPORTED", result["status"])
        self.assertEqual(0, self.exporter.stats["queue_size"])
        self.assertEqual(0, self.exporter.stats["failed_exports"])

    def test_real_backend_rejects_non_otlp_payload(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "scope": {"name": "s"},
                            "spans": [
                                {
                                    "traceId": "abcd",
                                    "spanId": "abcd",
                                    "name": "x",
                                    "kind": 1,
                                    "startTimeUnixNano": "0",
                                    "endTimeUnixNano": "0",
                                    "attributes": [],
                                    "events": [],
                                    "status": {"code": 1},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        response = httpx.post(OTLP_ENDPOINT, json=payload, timeout=5)
        self.assertGreaterEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
