import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "e2x_live_provider_smoke.py"
SPEC = importlib.util.spec_from_file_location("e2x_live_provider_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


class FakeProductApi:
    def __init__(self, *, generate_error=None, replay_mutation=None, missing_provenance=False, unexpected=False):
        self.calls = []
        self.generate_error = generate_error
        self.replay_mutation = replay_mutation
        self.missing_provenance = missing_provenance
        self.unexpected = unexpected

    def request(self, method, url, headers, body, timeout_seconds):
        self.calls.append((method, url, dict(headers), body))
        path = url.replace("https://smoke.invalid", "")
        if self.unexpected:
            return 200, {"data": []}
        if path == "/readyz":
            return 200, {"ready": True}
        if path == "/production-drafts" and method == "POST":
            return 200, {"data": {"availability": "CURRENT", "item": {"draft_id": "ed-1", "version": 1, "revisions": [{"revision_id": "edr-1"}]}}, "error": None}
        if path == "/production-drafts/ed-1/submit":
            return 202, {"data": {"availability": "CURRENT", "item": {"draft_id": "ed-1", "state": "SUBMITTED", "version": 2}}, "error": None}
        if path == "/production-drafts/ed-1/understanding" and method == "POST":
            generate_calls = sum(1 for item in self.calls if item[0] == "POST" and item[1].endswith("/understanding"))
            if self.generate_error and generate_calls == 1:
                return 503, {"data": None, "error": {"code": self.generate_error}}
            return 202, {"data": {"availability": "CURRENT", "item": {"understanding_id": "eun-1"}}, "error": None}
        if path == "/production-drafts/ed-1/understanding" and method == "GET":
            return 200, {"data": {"availability": "CURRENT", "item": {"understanding_id": "eun-1", "state": "READY"}}, "error": None}
        if path == "/production-drafts/ed-1/understanding/revisions":
            metadata = None if self.missing_provenance else {
                "source_draft_revision_id": "edr-1",
                "provider": "openai-compatible",
                "model": "nonproduction-model",
                "provider_request_id": "provider-request-1",
                "prompt_version": "v2",
                "schema_version": "v1",
                "latency_ms": 12,
                "retry_count": 0,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }
            revision = {"understanding_revision_id": "eur-1", "source_draft_id": "ed-1", "provider_metadata": metadata}
            revision_calls = sum(1 for item in self.calls if item[0] == "GET" and item[1].endswith("/revisions"))
            if revision_calls > 1 and self.replay_mutation == "revision":
                return 200, {"data": {"availability": "CURRENT", "items": [revision, dict(revision, understanding_revision_id="eur-2")]}, "error": None}
            if revision_calls > 1 and self.replay_mutation == "metadata":
                revision["provider_metadata"] = dict(metadata, provider_request_id="provider-request-2")
            return 200, {"data": {"availability": "CURRENT", "items": [revision]}, "error": None}
        raise AssertionError("unexpected route " + method + " " + path)


def config():
    return smoke.SmokeConfig("https://smoke.invalid", "test-token", expected_provider="openai-compatible", expected_model="nonproduction-model")


class LiveProviderSmokeRunnerTests(unittest.TestCase):
    def test_missing_external_guard_makes_zero_http_calls(self):
        transport = FakeProductApi()
        result = smoke.execute_from_env({}, transport)
        self.assertEqual({"status": "BLOCKED", "code": smoke.SMOKE_PRECONDITION_NOT_MET}, result)
        self.assertEqual([], transport.calls)

    def test_production_target_is_rejected_before_http(self):
        transport = FakeProductApi()
        env = {"HERMES_E2X_SMOKE_ALLOW_EXTERNAL": "true", "HERMES_E2X_SMOKE_TARGET_CLASS": "production", "HERMES_E2X_SMOKE_API_BASE_URL": "https://smoke.invalid", "HERMES_E2X_SMOKE_OIDC_TOKEN_FILE": "/not-used"}
        result = smoke.execute_from_env(env, transport)
        self.assertEqual(smoke.SMOKE_TARGET_REJECTED, result["code"])
        self.assertEqual([], transport.calls)

    def test_missing_or_empty_token_file_makes_zero_http_calls(self):
        for content, path in ((None, "/missing-token"), ("", None)):
            transport = FakeProductApi()
            if path is None:
                with tempfile.NamedTemporaryFile(mode="w", delete=False) as token_file:
                    token_file.write(content)
                    path = token_file.name
            env = {"HERMES_E2X_SMOKE_ALLOW_EXTERNAL": "true", "HERMES_E2X_SMOKE_TARGET_CLASS": "non-production", "HERMES_E2X_SMOKE_API_BASE_URL": "https://smoke.invalid", "HERMES_E2X_SMOKE_OIDC_TOKEN_FILE": path}
            result = smoke.execute_from_env(env, transport)
            self.assertEqual(smoke.SMOKE_PRECONDITION_NOT_MET, result["code"])
            self.assertEqual([], transport.calls)
            if content == "":
                Path(path).unlink()

    def test_sanitized_success_uses_product_api_in_required_order_and_accepts_nullable_usage(self):
        transport = FakeProductApi()
        result = smoke.run_smoke(config(), transport, run_id="fixed")
        self.assertEqual("PASS", result["status"])
        self.assertEqual({"input_tokens": None, "output_tokens": None, "total_tokens": None}, result["usage"])
        self.assertNotIn(smoke.FIXTURE_IDEA, str(result))
        self.assertNotIn("test-token", str(result))
        sequence = [(method, url.replace("https://smoke.invalid", "")) for method, url, _headers, _body in transport.calls]
        self.assertEqual([
            ("GET", "/readyz"),
            ("POST", "/production-drafts"),
            ("POST", "/production-drafts/ed-1/submit"),
            ("POST", "/production-drafts/ed-1/understanding"),
            ("GET", "/production-drafts/ed-1/understanding"),
            ("GET", "/production-drafts/ed-1/understanding/revisions"),
            ("POST", "/production-drafts/ed-1/understanding"),
            ("GET", "/production-drafts/ed-1/understanding"),
            ("GET", "/production-drafts/ed-1/understanding/revisions"),
        ], sequence)
        generate_bodies = [body for method, url, _headers, body in transport.calls if method == "POST" and url.endswith("/understanding")]
        self.assertEqual(2, len(generate_bodies))
        self.assertEqual(generate_bodies[0], generate_bodies[1])
        self.assertEqual(1, len({body["idempotency_key"] for body in generate_bodies}))

    def test_provider_stable_error_stops_without_second_draft_or_generate(self):
        transport = FakeProductApi(generate_error="ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED")
        with self.assertRaisesRegex(smoke.SmokeError, "ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED"):
            smoke.run_smoke(config(), transport, run_id="stable-error")
        self.assertEqual(1, sum(1 for method, url, _headers, _body in transport.calls if method == "POST" and url.endswith("/production-drafts")))
        self.assertEqual(1, sum(1 for method, url, _headers, _body in transport.calls if method == "POST" and url.endswith("/understanding")))

    def test_schema_or_domain_error_never_auto_creates_second_draft(self):
        transport = FakeProductApi(generate_error="ENTRY_UNDERSTANDING_DOMAIN_INVALID")
        with self.assertRaisesRegex(smoke.SmokeError, "ENTRY_UNDERSTANDING_DOMAIN_INVALID"):
            smoke.run_smoke(config(), transport, run_id="domain-error")
        self.assertEqual(1, sum(1 for method, url, _headers, _body in transport.calls if method == "POST" and url.endswith("/production-drafts")))

    def test_replay_result_metadata_mismatch_fails_closed(self):
        with self.assertRaisesRegex(smoke.SmokeError, smoke.SMOKE_REPLAY_MISMATCH):
            smoke.run_smoke(config(), FakeProductApi(replay_mutation="metadata"), run_id="mismatch")

    def test_replay_revision_growth_fails_closed(self):
        with self.assertRaisesRegex(smoke.SmokeError, smoke.SMOKE_REPLAY_MISMATCH):
            smoke.run_smoke(config(), FakeProductApi(replay_mutation="revision"), run_id="growth")

    def test_missing_provenance_fails_closed(self):
        with self.assertRaisesRegex(smoke.SmokeError, smoke.SMOKE_PROVENANCE_MISSING):
            smoke.run_smoke(config(), FakeProductApi(missing_provenance=True), run_id="provenance")

    def test_unexpected_response_shape_fails_closed(self):
        with self.assertRaisesRegex(smoke.SmokeError, smoke.SMOKE_RESPONSE_INVALID):
            smoke.run_smoke(config(), FakeProductApi(unexpected=True), run_id="shape")


if __name__ == "__main__":
    unittest.main()
