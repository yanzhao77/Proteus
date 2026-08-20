# E2.x Producer Integration Design — Auditable Baseline Seal

> **Document authority.** This design snapshot is authoritative for the E2.x producer boundary. The sole **Current Verification Authority** for repository-wide E2.x/P6 statistics is [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md); the table below mirrors that manifest at this reseal.

## 1. Current Phase Status

E2.x is a server-side, OpenAI-compatible producer boundary for the **Understanding** step. It transforms an already submitted E1 Draft snapshot into a typed candidate; it does not create authority outside E2 and it does not constitute evidence that a real provider has been invoked.

| Dimension | Authoritative status |
| --- | --- |
| E2.x Internal Implementation | **PASS** |
| E2.x Final Acceptance Correction | **PASS** |
| E2.x Live Provider Verification | **PASS — NON-PRODUCTION** |
| E2.x Phase | **COMPLETE / LIVE VERIFIED** |
| P6 Recovery Runtime Least-Privilege Repair | **PASS** |
| P6 Authority Gate | **CLOSED** |
| P6 Phase | **COMPLETE / REVALIDATED** |
| Current migration continuity | `0001 → 0028` **PASS** |

Live verification completed on an authorized local Docker non-production target. The controlled smoke used the Product API only and preserved the server-only credential boundary; it recorded only sanitized provenance and entity identifiers.

## 2. Authority Boundary

The broader flow remains `Idea → Draft → Understanding → Proposal → Master Plan → Approve → Production → Live Production`. E2.x occupies only the typed Understanding boundary. The producer receives a source Draft revision and returns a candidate; E2 validates that candidate, rechecks the source snapshot, and atomically records the Understanding revision plus immutable provenance.

> Provider output has no authority to create Projects, Tasks, Plans, executions, worker actions, human-gate decisions, P6 facts, receipts, or arbitrary state transitions.

Receipt reservation happens before provider invocation. A replay with the same idempotency identity returns the durable authoritative result and does not invoke the producer again. A changed Draft snapshot fails closed before authority application. The E1/E2 state machines, receipt and idempotency semantics, OIDC creator scope, Recovery/P6 authority, frontend provider boundary, and all migrations remain unchanged by this design.

## 3. Code-Owned Version Truthfulness

Prompt and schema versions are implementation facts, not deployment claims. The code owns both constants and passes them through the typed request, provider payload and persisted provenance.

| Fact | Current value | Source of truth |
| --- | --- | --- |
| `UNDERSTANDING_PROMPT_VERSION` | `v2` | `understanding_producer.py` |
| `UNDERSTANDING_SCHEMA_VERSION` | `v1` | `understanding_producer.py` |
| Provider config schema field | Removed | It did not control parsing or authority behavior. |
| `HERMES_UNDERSTANDING_SCHEMA_VERSION` | Removed from production code | Deployment cannot fabricate schema provenance. |
| Persisted provenance | Request-owned `v2` / `v1` | Same code constants used by the E2 store. |

The candidate schema itself has not changed. It therefore remains `v1`. Prompt V2 is recorded because the system instruction was strengthened, not because the output schema was revised.

## 4. Prompt V2 and Source/Domain Validation

The provider system instruction requires one JSON object whose fields exactly match `UnderstandingCandidate`: `goal`, `objectives`, `requirements`, `unknowns`, `assumptions`, `risks`, and `clarification_questions`. `goal` must be non-empty; every remaining field must be a string array; unknown, nested, omitted or explanatory fields are rejected.

Prompt V2 requires every `requirements` item to be a non-empty, verbatim traceable fragment of `idea_text`. It prohibits inferred requirements, recommendations and general knowledge. When no explicit requirement exists, the model must emit an empty `requirements` array and may place uncertainty only in assumptions, risks, unknowns or clarification questions. It also forbids credentials, tokens, internal authority metadata, Project/P6 data, Plans, Tasks and Executions.

The prompt does **not** weaken E2 authority. The store still independently rejects any requirement whose case-folded text is not present in the source Draft raw input. Structural, source, domain and stale-snapshot failures remain fail-closed.

## 5. Server-Only Provider Boundary

The registry recognizes exactly one configured provider name: `openai-compatible`. An empty provider configuration constructs an unavailable producer. An unknown provider name or invalid configuration produces a configuration-error unavailable producer. There is no fallback vendor, generic gateway, browser configuration or client-side secret path.

| Setting | Rule |
| --- | --- |
| `HERMES_UNDERSTANDING_PROVIDER` | Empty means unavailable; only `openai-compatible` is configured. |
| `HERMES_UNDERSTANDING_BASE_URL` / `HERMES_UNDERSTANDING_MODEL` | Required only for a configured server-side adapter. |
| `PROTEUS_LLM_API_KEY` | Server-only key; a non-empty inline value takes priority over `_FILE`. |
| `PROTEUS_LLM_API_KEY_FILE` | Server-only fallback when the inline value is absent or empty. |
| `HERMES_UNDERSTANDING_TIMEOUT_SECONDS` | Default `15`; finite and positive. |
| `HERMES_UNDERSTANDING_MAX_RETRIES` | Integer `0..2`; one to three total attempts. |
| `HERMES_UNDERSTANDING_SCHEMA_VERSION` | **Not read.** Schema provenance is code-owned. |

No key, bearer header, raw prompt or raw provider response may enter frontend artifacts, migrations, persisted provenance, API envelopes, smoke reports or repository documentation.

## 6. Retry and Error Semantics

Timeouts, connection failures, HTTP `429`, and every HTTP status in `500..599` are retryable within the existing bounded policy. `400`, `401`, `403`, malformed responses, schema/domain failures and configuration failures are non-retryable. The FastAPI envelope is redacted and authenticates before delegation.

| Condition | Stable code | Retry | HTTP mapping |
| --- | --- | --- | --- |
| Provider unavailable/configuration error | `ENTRY_UNDERSTANDING_PROVIDER_UNAVAILABLE` / `ENTRY_UNDERSTANDING_CONFIGURATION_ERROR` | No | 503 |
| Timeout, connection, `429`, `500..599` | Corresponding stable provider code | Bounded | 503 |
| `401`/`403`, other `400..499`, invalid response | Corresponding stable provider code | No | 502 |
| Candidate schema/domain violation | `ENTRY_UNDERSTANDING_SCHEMA_INVALID` / `ENTRY_UNDERSTANDING_DOMAIN_INVALID` | No | 422 |

## 7. Provenance and Read Projection

Migration `0027_e2x_producer_provenance.sql` remains the E2.x provenance migration. It binds one immutable provenance record to each Understanding revision and stores the source Draft revision identity, provider/model identity, upstream request identifier when present, prompt/schema version, latency, retry count and nullable usage. Migration `0028` is a P6 least-privilege revoke and does not alter E2 provenance schema or semantics.

The E2 read projection now includes `source_draft_revision_id` inside `provider_metadata`. It is a non-sensitive identity projection required for smoke verification; it does not expose raw prompts, raw responses, credentials or authority data.

## 8. Controlled Live Smoke Design

`hermes-runtime/scripts/e2x_live_provider_smoke.py` is a reusable Product-API-only smoke runner. It never reads a provider key or contacts a provider URL directly. It performs one non-production E1/E2 flow through verified OIDC HTTP endpoints:

```text
readyz → create Draft → submit Draft → generate Understanding → read → replay same key → compare
```

The runner cannot issue any HTTP request until all guards pass: `HERMES_E2X_SMOKE_ALLOW_EXTERNAL=true`, `HERMES_E2X_SMOKE_TARGET_CLASS=non-production`, an explicit API base URL, and a readable non-empty OIDC token file. It rejects production targets, accepts no inline token CLI argument, performs at most one logical generate command plus one same-key replay, and stops on the first stable provider/API failure. The durable side effect is explicitly non-production E1/E2 evidence.

A successful smoke requires current E2 state, an immutable revision, correct source revision identity, non-empty provider/model provenance, `prompt_version=v2`, `schema_version=v1`, legal nullable usage, non-negative latency/retry counts and an unchanged replay result/revision count. Its sanitized report contains identifiers and metadata only; it never includes the token, raw provider prompt, raw response or raw fixture text.

## 9. Internal Evidence

| Evidence | Current result |
| --- | --- |
| Provider adapter and registry/version tests | **10/10 PASS** |
| Smoke runner no-network tests | **10/10 PASS** |
| FastAPI E2 error envelope tests | **2/2 PASS** |
| P6 bootstrap cleanup-authenticity/PostgreSQL/Golden Todo suite | **13/13 PASS** in `2.830 s`; includes factory-issued, evidence-tamper, OID-replacement and owner-mismatch closure. |
| Focused E1/E2/E2.x/FH-1/FastAPI/OIDC/Product API suite | **86/86 PASS** in `4.309 s` |
| P6 Recovery permission/runtime-role suite | **6/6 PASS** in `3.777 s` |
| P6 standalone / fresh `0001 → 0028` | **1/1 PASS** in `105.839 s`; no `todo_p6_ci_*` residue. |
| P0–P5 no-DB discovery | **575 run, 333 skipped, 0 failures** in `1.280 s` |
| Full Runtime regression | **575 run, 12 skipped, 0 failures** in `293.539 s` |
| Frontend | **33/33 PASS** in `1.33 s`; build PASS in `342 ms`; lint `0` warnings / `0` errors |

## References

[1]: ../hermes-runtime/src/hermes_runtime/domain/understanding_producer.py "Code-owned prompt and schema constants"
[2]: ../hermes-runtime/src/hermes_runtime/infrastructure/openai_compatible_understanding_provider.py "OpenAI-compatible adapter"
[3]: ../hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_understanding.py "E2 authority and read projection"
[4]: ../hermes-runtime/scripts/e2x_live_provider_smoke.py "Controlled smoke runner"
[5]: ./E2X_LIVE_PROVIDER_SMOKE_RUNBOOK.md "Non-production smoke runbook"
[6]: ./P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md "P6 least-privilege revalidation"

## 10. Authorized Non-Production Live Verification

The controlled live verification specified in Section 8 completed once against the local Docker `non-production` target at `2026-08-20T03:14:47Z`. The Product-API-only runner used nine requests to create and submit one Draft, generate one Understanding, read its authority/revisions, and replay the identical idempotency key. The authoritative result matched source Draft revision `edr-3f1adc2180ac41e88e98baf90b30b753`, returned the same result on replay without a new revision, and recorded `openai-compatible` / `deepseek-chat` provenance, `v2` prompt version, `v1` schema version, legal usage, `1805 ms` latency and retry count `0`.

This verification confirms the design boundary rather than adding a second authority path: OIDC-verified Product API calls reach the existing E2 authority, while credentials remain server-side. Its sanitized evidence is maintained in the live smoke delivery report. No E3 scope is authorized or included.
