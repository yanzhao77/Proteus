# E2.x Producer Integration Implementation — Auditable Baseline Seal

> **Implementation authority.** This record describes the current repository implementation and does not claim a live provider invocation. [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md) is the sole **Current Verification Authority**; the record below is a synchronized implementation-facing mirror.

## 1. Implemented Boundary

E2.x implements a typed, server-side OpenAI-compatible producer for Entry Understanding. The adapter is only an input boundary. The existing E2 authority store reserves a receipt, invokes the producer, validates source/domain constraints, rechecks the source snapshot, and atomically commits a legal revision plus immutable provenance. A replay returns the durable result without repeating producer work.

| Boundary | Implemented result |
| --- | --- |
| Provider integration | One `openai-compatible` server-side adapter with injected transport seam. |
| Configuration posture | Configured-or-unavailable only; no fake provider, fallback vendor or generic gateway. |
| Authority | Existing E1/E2 state machines, receipts, idempotency and OIDC scope are unchanged. |
| Data boundary | Raw prompt/response, key and `Authorization` value are excluded from persistence, envelope and smoke output. |
| P6 boundary | P6 Recovery repair remains unchanged; its Authority Gate is **CLOSED**. |
| Migration boundary | E2 provenance remains migration `0027`; the current repository chain ends at P6 revoke migration `0028`. |

## 2. Version Truthfulness Implementation

The implementation owns the versions used by request, provider payload and persisted provenance.

| Component | Actual implementation |
| --- | --- |
| `UNDERSTANDING_PROMPT_VERSION` | Code constant `v2`. |
| `UNDERSTANDING_SCHEMA_VERSION` | Code constant `v1`. |
| Provider config `schema_version` field | Removed because it did not control parser or request behavior. |
| `HERMES_UNDERSTANDING_SCHEMA_VERSION` | No production or script reader remains. A regression test proves an environment value cannot forge provenance. |
| E2 typed request | Store explicitly supplies the two code constants. |
| Provider provenance | Uses the typed request versions, so persisted values are `v2` / `v1`. |

Prompt V2 requires JSON only, exact candidate fields, string-array lists, source-traceable requirements, empty requirements when none are explicit, and placement of inference only in assumptions, risks, unknowns or clarification questions. It forbids secret values, authority metadata, Project/P6 data and out-of-schema fields. The independent E2 validation still rejects requirement text absent from source raw input.

## 3. Production Inventory

| Path | Responsibility |
| --- | --- |
| `src/hermes_runtime/domain/understanding_producer.py` | Typed protocol/provenance plus code-owned Prompt V2, Schema V1 and strict system prompt. |
| `src/hermes_runtime/infrastructure/openai_compatible_understanding_provider.py` | Strict `/chat/completions` parser, bounded retry and Prompt V2 payload. |
| `src/hermes_runtime/infrastructure/understanding_provider_registry.py` | Server-only registry; dead schema environment override removed. |
| `src/hermes_runtime/infrastructure/postgres_entry_understanding.py` | Receipt/source/domain authority bridge, fixed version request construction and safe provenance source-revision projection. |
| `scripts/e2x_live_provider_smoke.py` | Default-deny non-production Product API smoke runner. |
| `tests/test_e2x_provider_adapter.py` | Adapter/registry/version truthfulness tests. |
| `tests/test_e2x_live_provider_smoke.py` | Injected-transport, no-network smoke security tests. |
| `tests/test_entry_understanding_core.py` | E2 authority/provenance/source-revision projection test. |

## 4. Retry, Error and API Semantics

Timeout, connection failure, HTTP `429`, and every `500..599` response remain retryable subject to `max_retries` in `0..2`. HTTP `400`, `401`, `403`, other `4xx`, malformed response, schema/domain and configuration failures remain non-retryable. FastAPI returns stable redacted codes and authenticates before it can delegate to the producer.

| Check | Current rule |
| --- | --- |
| All `5xx` retry classification | `500 <= status <= 599`, including `501` and `599`. |
| Default timeout | `15` seconds. |
| Key precedence | Non-empty `PROTEUS_LLM_API_KEY` precedes `_FILE`; both remain server-only. |
| Schema environment override | Removed; no deployment value can claim a schema unsupported by code. |
| Read projection | Adds only `source_draft_revision_id` to provenance metadata; no raw prompt/response/credential exposure. |

## 5. Controlled Smoke Runner

The smoke runner uses verified OIDC Product API endpoints only: `/readyz`, Draft creation/submission, Understanding generation/read/revisions, and a same-idempotency-key replay. It does not access the provider base URL, provider key, database or authority rows directly.

Before any HTTP call it requires all four guards: external permission exactly `true`, target class exactly `non-production`, explicit API base URL, and readable non-empty OIDC token file. It rejects production targets and does not accept an inline token argument. It makes one logical generate request and one identical replay; it stops on the first stable error and never creates a replacement Draft.

The runner checks legal E2 state, immutable revisions, source revision identity, provider/model identity, `v2`/`v1` provenance, nullable usage legality, latency/retry legality, stable replay and no extra revision. Its returned evidence is sanitized to identifiers and safe metadata.

## 6. Current Verification Record

| Verification | Exact result |
| --- | --- |
| Provider adapter/registry/version suite | **10/10 PASS** |
| Smoke runner injected no-network suite | **10/10 PASS** |
| FastAPI E2 error-envelope suite | **2/2 PASS** |
| P6 bootstrap cleanup-authenticity/PostgreSQL/Golden Todo suite | **13/13 PASS** in `2.830 s`; factory-issued capability, OID replacement and owner mismatch verified. |
| Focused E1/E2/E2.x/FH-1/FastAPI/OIDC/Product API suite | **86/86 PASS** in `4.309 s` |
| Fresh `0001 → 0028` path | **PASS** through the P6 standalone fresh control database; migrations remain immutable. |
| Recovery permission/runtime-role suite | **6/6 PASS** in `3.777 s` |
| P6 standalone autonomous acceptance | **1/1 PASS** in `105.839 s`; cleanup leaves no `todo_p6_ci_*` target. |
| P0–P5 no-DB discovery | **575 run, 333 skipped, 0 failures** in `1.280 s` |
| Full Runtime regression | **575 run, 12 skipped, 0 failures** in `293.539 s` |
| Frontend tests | **33/33 PASS** in `1.33 s` |
| Frontend production build | **PASS** in `342 ms` |
| Frontend lint | **PASS — 0 warnings / 0 errors** |

## 7. Status and Non-Goals

The repository delivery is internally verified and live-verified. One authorized fixed-budget local Docker non-production smoke passed through the Product API using verified OIDC and a real OpenAI-compatible provider. Its evidence is sanitized to safe identifiers and metadata; it contains no credential, endpoint, raw prompt or raw response.

The implementation did not modify migrations `0001–0028`, P6 Recovery code/tests/trial/evidence, E1/E2 state machines, receipt/idempotency semantics, frontend provider configuration, Project/Plan/Approval authority, or real-provider behavior. It did not add a provider fallback or a second authority path.

## References

[1]: ./E2X_PRODUCER_INTEGRATION_DESIGN.md "Current E2.x design authority"
[2]: ./E2X_LIVE_PROVIDER_SMOKE_RUNBOOK.md "Non-production smoke runbook"
[3]: ./P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md "P6 closed-gate evidence"
[4]: ../hermes-runtime/scripts/e2x_live_provider_smoke.py "Smoke runner"
[5]: ../hermes-runtime/tests/test_e2x_live_provider_smoke.py "Smoke runner tests"

## 8. Authorized Non-Production Live Verification

At `2026-08-20T03:14:47Z`, the implementation completed one authorized local Docker `non-production` Product-API-only smoke on merged release `ebc9e6e8d80ad07a48f8274f7d686444941e0604`. The run consumed the complete fixed budget of nine Product API requests, made one logical Understanding generation, and made one same-key replay. It produced one authoritative Understanding with matching source Draft revision, non-empty `openai-compatible` / `deepseek-chat` provenance, `prompt_version=v2`, `schema_version=v1`, legal usage (`325` input, `117` output, `442` total tokens), `1805 ms` latency and retry count `0`. The replay returned the same authoritative result without a new revision.

The runner invoked no Proposal, Plan, Project, Task, Execution or P6 route. The full runtime regression was not re-run; the sealed `575 run / 12 skipped / 0 failures` evidence remains unchanged. The delivery retains no credential, token, authorization header, endpoint, DSN, raw prompt or raw provider response.
