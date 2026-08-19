# E2.x Live Provider Smoke Runbook

> **Scope:** This runbook is for one **non-production** controlled smoke only. It creates durable non-production E1/E2 evidence. It must never be used for production, provider experimentation, bulk generation or automated retries.

## 1. Deployment Administrator Responsibilities

The deployment administrator, not the smoke operator, configures the server-side provider, model, base URL and server-only credential. The smoke runner neither reads nor accepts a provider key. The administrator must also deploy a Product API with OIDC identity verification and a readiness endpoint.

| Required responsibility | Boundary |
| --- | --- |
| Configure provider/model/base URL/key on the server | Keep all provider credentials server-only. |
| Expose Product API and OIDC verification | Smoke uses verified public Product API routes only. |
| Provide a non-production API target | Production targets are rejected by the runner. |
| Provide a scoped OIDC token file path | Do not supply a token inline, in a command argument, chat message or repository file. |
| Review durable evidence retention | The smoke creates one Draft and one Understanding lineage. |

## 2. Preconditions and Guards

All conditions below are mandatory. If any one is absent or invalid, the runner exits before making an HTTP request with `SMOKE_PRECONDITION_NOT_MET`; a production target returns `SMOKE_TARGET_REJECTED`.

| Guard | Required value |
| --- | --- |
| `HERMES_E2X_SMOKE_ALLOW_EXTERNAL` | Exactly `true`. |
| `HERMES_E2X_SMOKE_TARGET_CLASS` | Exactly `non-production`. |
| `HERMES_E2X_SMOKE_API_BASE_URL` | Explicit HTTP(S) Product API base URL. |
| `HERMES_E2X_SMOKE_OIDC_TOKEN_FILE` | Readable, non-empty token file. |
| API readiness | `/readyz` returns a ready Product API. |
| Identity | Token must pass the deployed OIDC verifier as a creator-scoped user. |
| Server provider configuration | Administrator has configured provider, model, base URL and server-only key. |

The runner does not accept an inline OIDC token. It does not read `PROTEUS_LLM_API_KEY`, `PROTEUS_LLM_API_KEY_FILE`, provider headers, a database DSN or an upstream provider base URL.

## 3. Execution

Use the deployment's Python runtime and invoke the script without echoing a token or printing environment values.

```bash
cd hermes-runtime
PYTHONPATH=src .venv/bin/python scripts/e2x_live_provider_smoke.py
```

The fixed non-sensitive fixture is a non-production task tracker API idea with explicit requirements for task create, list and completion, and explicit no-integration/no-production constraints. The runner derives unique Draft title and idempotency keys internally.

## 4. Call Budget and Durable Effects

The runner performs this exact sequence:

```text
GET /readyz
POST /production-drafts
POST /production-drafts/{draft_id}/submit
POST /production-drafts/{draft_id}/understanding      # one logical generate
GET  /production-drafts/{draft_id}/understanding
GET  /production-drafts/{draft_id}/understanding/revisions
POST /production-drafts/{draft_id}/understanding      # same idempotency-key replay
GET  /production-drafts/{draft_id}/understanding
GET  /production-drafts/{draft_id}/understanding/revisions
```

It creates one Draft and one authoritative Understanding path. It creates no Project, Task, Plan, Execution, P6 fact or additional Draft. Provider-internal attempts remain subject to the server adapter's existing maximum of three total attempts. The runner never creates a second Draft after failure and never loops generation.

## 5. Result Interpretation

| Outcome | Meaning | Required next action |
| --- | --- | --- |
| `PASS` | All Product API, provenance and replay checks passed. | Preserve only sanitized evidence; assess E2.x phase with full regression evidence. |
| `BLOCKED / SMOKE_PRECONDITION_NOT_MET` | A mandatory external guard or token-file precondition was absent. | Do not call any external service; have the deployment administrator supply the missing non-production guard. |
| `BLOCKED / SMOKE_TARGET_REJECTED` | Target was not non-production. | Stop. Do not redirect to production. |
| `FAIL / stable provider or API code` | A real governed failure occurred. | Stop. Record the stable code; begin a new phase assessment rather than changing authority/prompt/retry semantics automatically. |
| `FAIL / SMOKE_REPLAY_MISMATCH` or provenance code | Product API result did not satisfy immutable replay/provenance expectations. | Stop and assess; do not create a replacement Draft. |

## 6. Sanitized Evidence and Retention

A PASS record may retain timestamp, target class, Draft/Understanding/revision identifiers, provider/model, optional provider request ID, `prompt_version`, `schema_version`, nullable usage, latency, retry count, replay comparison and secret-scan result. Do **not** retain or publish the OIDC token, any provider key, raw Authorization header, raw provider prompt, raw provider response or user-sensitive Draft content.

Retention and cleanup of the durable non-production Draft/Understanding evidence are deployment-governance decisions. Do not delete records by bypassing E1/E2 authority. Never paste a credential into chat, source control, documentation or a bug report.

## References

[1]: ../hermes-runtime/scripts/e2x_live_provider_smoke.py "Smoke runner implementation"
[2]: ./E2X_LIVE_PROVIDER_SMOKE_DELIVERY_REPORT.md "Smoke delivery evidence"
[3]: ./E2X_PRODUCER_INTEGRATION_DESIGN.md "E2.x authority and prompt/schema design"
