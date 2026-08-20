# E2.x Auditable Baseline Seal and Live Provider Smoke Delivery Report

> **Current Final Status:** **E2.x Repository/Internal Delivery: PASS.** **E2.x Live Provider Verification: PASS — NON-PRODUCTION.** **E2.x Phase: COMPLETE / LIVE VERIFIED.** **P6 Authority Gate: CLOSED.** **P6 Functional Revalidation: PASS.** **E3: NOT ENTERED.** Repository-wide current verification authority remains exclusively in [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md); this delivery report is a synchronized mirror.

## 1. Baseline Seal

The previous P6 permission discrepancy is resolved by the documented least-privilege `0028` forward migration. P6 remains independently revalidated and closed. E2.x provenance schema remains migration `0027`; no migration was created or changed in this delivery. The current chain is `0001 → 0028`.

| Baseline fact | Result |
| --- | --- |
| P6 Recovery Runtime Least-Privilege Repair | **PASS** |
| P6 Authority Gate | **CLOSED** |
| P6 Phase | **COMPLETE / REVALIDATED** |
| E2.x Internal Implementation | **PASS** |
| E2.x Final Acceptance Correction | **PASS** |
| Temporary fresh migration verifier | Removed after read-only confirmation that it was unreferenced and replaced by formal P6 evidence. |
| Migration chain | Fresh `0001 → 0028` **PASS** through the dedicated P6 acceptance path. |

## 2. Prompt and Schema Truthfulness

Prompt V2 is now a code-owned constant and schema remains code-owned V1. The provider configuration field that did not control parser/request behavior was removed; no production/script code reads `HERMES_UNDERSTANDING_SCHEMA_VERSION`. A regression test injects `v999` through that environment name and proves it cannot manufacture provenance.

| Provenance fact | Result |
| --- | --- |
| Prompt version | `v2` |
| Schema version | `v1` |
| Prompt V2 | Exact JSON contract plus strict source-traceable requirements instruction. |
| E2 source/domain validation | Unchanged and fail-closed. |
| Persisted source revision ID | Safely projected in `provider_metadata` for smoke verification. |
| Raw provider input/output or secret persistence | Not implemented. |

## 3. Smoke Runner Security Model

The new smoke runner is Product-API-only and default-deny. It requires explicit egress permission, a non-production target class, explicit API base URL and a non-empty OIDC token file before issuing even a readiness request. It rejects production, accepts no inline token, never reads provider credentials, never accesses the database and never directly calls a provider URL.

The runner executes one controlled Draft-to-Understanding flow and exactly one same-key replay. It verifies Product API OIDC scope, source revision identity, non-empty provider/model provenance, `v2`/`v1` provenance, legal nullable usage, latency/retry ranges, and unchanged authoritative replay/revision count. Its output is sanitized to safe identifiers and metadata.

## 4. Internal Verification

| Verification | Exact result |
| --- | --- |
| P6 Todo bootstrap contract/PostgreSQL/Golden Todo tests | **13/13 PASS** in `2.830 s`; direct Golden Todo **9/9 PASS** plus factory-issued cleanup, OID-replacement, owner-mismatch and strict wrong-owner-with-`CREATE` rejection. |
| Provider adapter/registry/version tests | **10/10 PASS** |
| Smoke runner injected fake-transport tests | **10/10 PASS**; no real network used |
| FastAPI E2 error-envelope tests | **2/2 PASS** |
| Focused E1/E2/E2.x/FH-1/FastAPI/OIDC/Product API suite | **86/86 PASS** in `4.309 s` |
| Recovery permission/runtime-role suite | **6/6 PASS** in `3.777 s` |
| P6 standalone autonomous acceptance | **1/1 PASS** in `105.839 s` with unique strict owner-plus-`CREATE` Todo database plus factory-issued name/OID/owner cleanup and verified no-residue cleanup. |
| P0–P5 no-DB discovery | **575 run, 333 skipped, 0 failures** in `1.280 s` |
| Full Runtime regression | **575 run, 12 skipped, 0 failures** in `293.539 s` |
| Frontend Vitest | **33/33 PASS** in `1.33 s` |
| Frontend build | **PASS** in `342 ms` |
| Frontend lint | **PASS — 0 warnings / 0 errors** |

The full regression's twelve skips are established external-prerequisite cases for OTLP, Docker, S3 and Vault. They are not converted into PASS and do not conceal a failure.

## 5. Live Execution Decision

The authorized local Docker non-production execution completed once after zero-request preflight checks confirmed the release, target class, OIDC token/JWKS binding, server-side provider secret boundary and runner guards. The runner used the Product API only; it did not read a provider credential or contact a provider endpoint directly.

| Live condition | Result |
| --- | --- |
| Explicit egress guard | Present and exactly `true` |
| Explicit target class | `non-production` |
| Product API request budget | **9 / 9**; no second run |
| Logical Understanding generation | **1 / 1** |
| Same-key replay | **1 / 1**; same authoritative result and no new revision |
| Provider adapter attempts | **1 / 3** total |
| Live Provider Verification | **PASS — NON-PRODUCTION** |
| Sanitized live evidence | Retained below; no token, credential, endpoint, raw prompt or raw response. |

## 6. Protected-Path and Secret Boundary

No migration, P6 Recovery production source, P6 permission/runtime-role authority test, E1/E2 state machine, receipt/idempotency behavior, frontend provider configuration, Project/Plan/Approval authority or live provider configuration was changed. The authorized P6 standalone test lifecycle and Golden Todo fixture were updated solely to bootstrap a disposable role-owned test database; no authority semantics were changed. No secret was added to code, documentation, output or persisted data. The final manifest records SHA-256 values, secret scan result, diff check and the recommended commit candidate list.

## 7. Final E2.x Status

| Dimension | Final status |
| --- | --- |
| E2.x Auditable Baseline Seal | **PASS** |
| E2.x Repository Smoke Delivery | **PASS** |
| E2.x Live Provider Verification | **PASS — NON-PRODUCTION** |
| E2.x Phase | **COMPLETE / LIVE VERIFIED** |
| P6 Authority Gate | **CLOSED** |
| P6 Phase | **COMPLETE / REVALIDATED** |

The authorized non-production smoke passed all Product API, provenance, replay and secret-boundary criteria. No E3 work is included. A future live failure remains subject to stable-code reporting and must not trigger automatic prompt, authority, retry or validation changes.

## References

[1]: ./E2X_LIVE_PROVIDER_SMOKE_RUNBOOK.md "Controlled smoke runbook"
[2]: ./PROTEUS_E2X_P6_BASELINE_MANIFEST.md "Commit-ready baseline manifest"
[3]: ./E2X_PRODUCER_INTEGRATION_DESIGN.md "E2.x design snapshot"
[4]: ./E2X_PRODUCER_INTEGRATION_IMPLEMENTATION.md "E2.x implementation snapshot"
[5]: ./P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md "P6 closed-gate evidence"

## 8. Authorized Non-Production PASS Evidence

> **Execution scope:** one user-authorized fixed-budget run against the local Docker `non-production` target. The runner stopped after the one governed flow and did not enter E3.

| Evidence field | Sanitized value |
| --- | --- |
| Execution UTC | `2026-08-20T03:14:47Z` |
| Merged release commit | `ebc9e6e8d80ad07a48f8274f7d686444941e0604` |
| Target class | `non-production` |
| Product API request count | `9 / 9` |
| Draft / source revision | `ed-90adc0942dd04299a342c39fde030bbf` / `edr-3f1adc2180ac41e88e98baf90b30b753` |
| Understanding / authoritative revision | `eun-5e5bab6b0be543799d2138ec94f985e4` / `eur-b92d2e9fc3ae4711bca70f1d12700852` |
| Provider / model | `openai-compatible` / `deepseek-chat` |
| Provider request identifier | `8555da4d-b22a-4de3-b09b-5026c9ddc53d` |
| Prompt / schema version | `v2` / `v1` |
| Usage | `325` input tokens, `117` output tokens, `442` total tokens |
| Latency / retry count | `1805 ms` / `0` |
| Replay result | `same_authoritative_result_no_new_revision` |
| Stable failure code | None; run passed. |

The fixed route surface was readiness, Draft create/submit, one Understanding generate/read/revisions sequence, and one same-key replay/read/revisions sequence. It did not invoke Proposal, Plan, Project, Task, Execution or P6 routes. The full runtime baseline was not re-run; its sealed `575 run / 12 skipped / 0 failures` evidence remains historical current baseline support.
