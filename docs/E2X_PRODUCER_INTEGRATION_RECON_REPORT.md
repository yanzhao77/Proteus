# E2.x Producer Integration Recon Report

**状态：Recon complete；尚未实施。** 本报告仅基于本地 Proteus 工作树的只读检查形成。根据任务指令，本阶段在本报告交付后停止，等待进一步授权后才进行代码、迁移、依赖或配置改动。

## 1. Recon Summary

当前 E2 已有一个安全但未生产化的边界：`PostgresEntryUnderstandingStore` 在持久化 receipt lookup 后调用 `UnderstandingProducer`，再执行结构与领域校验，并仅由 E2 authority 写入 revision、clarification、assumption 与 audit fact。默认 `api_main` 仍装配 `UnavailableEntryUnderstandingApi`，因此 live E2 generation 的真实结果是 `NOT_IMPLEMENTED`。这说明 **authority 方向正确，但生产 producer integration 缺失**。

现有 `UnderstandingProducer` 只接受/返回松散 `Mapping`。它没有 provider registry、server-only provider configuration、HTTP error 分类、bounded retry、request metadata、prompt/schema version 或 first-class provenance。因此现有 protocol 不足以承担 production provider，需做**窄的 typed contract 升级**；E2 authority 不应认识 HTTP、API key、OpenAI protocol、OIDC、FastAPI、Product API、Project 或 P6。

| Recon 问题 | 本地代码结论 | E2.x 决策 |
| --- | --- | --- |
| 通用 LLM provider | 未发现。 | 新增最小 provider adapter。 |
| OpenAI-compatible provider | 未发现。 | 可新增 server-only `openai-compatible` adapter。 |
| HTTP inference client | 未发现推理专用 client；已有 HTTP/timeout 形态仅用于其他基础设施。 | 新增注入式 HTTP transport；不复用 OTLP/Planner/P6 语义。 |
| 模型配置 abstraction | 未发现。 | 新增 E2.x-only immutable config dataclass。 |
| retry/timeout abstraction | 未发现可直接复用的 inference retry。 | Adapter 内实现 bounded exponential retry；不迁移 P6/recovery retry。 |
| secret/config abstraction | `env_or_file` 已用于 server composition。 | 复用 `env_or_file` 读取 server-side key；绝不使用 `VITE_*`。 |
| E2 producer protocol | 仅 `generate(request: Mapping) -> Mapping`。 | 替换为 typed request/candidate + narrow adapter boundary。 |

## 2. Existing Provider Findings

`hermes-runtime/requirements.txt` 没有 OpenAI、Anthropic、LiteLLM、Ollama 或其他 LLM SDK。现有 Python 构建不需要为 E2.x 引入大型 SDK；一个最小注入式 HTTP transport 足以实现 OpenAI-compatible JSON request/response。`config.env_or_file` 是可复用的 server-side secret reader，当前已经被 `api_main` 用于 OIDC JWKS/数据库配置；它适合读取 provider API key，但 key 不能被打印、持久化、返回或写入文档。

`postgres_entry_understanding.py` 已正确实现 **receipt-before-producer**：E2 receipt lookup 必须继续发生在任何 provider 调用前。同一 creator、command、idempotency key、request hash 的 replay 只能返回 persisted result，不能产生第二次 model request。当前 `_validate` 已拒绝 unknown output fields、空 intent、错误 array/object、错误 confidence 与 malformed clarification/assumption；E2.x 应保留它作为 domain validation 的后一层，而不是让 provider JSON 直接进入 persistence。

当前 revision 已保存 source Draft ID/revision number/raw input、`generated_at`、nullable confidence 和 generic `provider_metadata`。但它没有 first-class `source_draft_revision_id`、producer/provider/model/model version/request ID/prompt version/schema version/usage/duration 字段。这些不能从 metadata 猜测，因而需要一个唯一、独立的 **`0027_e2x_producer_provenance.sql`** migration，且只 `ALTER` E2 revision/provenance 表，不修改 E1、Project 或 P6 schema。

## 3. Reuse / Do-not-reuse Matrix

| Area | Safe reuse | Explicitly do not reuse | Reason |
| --- | --- | --- | --- |
| E1/E2 authority | E1 creator scope、E2 receipt/transaction/version/immutable validation patterns。 | Project/Task authority。 | Producer only supplies a candidate; E2 remains persistence authority. |
| API & identity | Product API semantic dispatch、OIDC verifier、verified subject boundary。 | Browser actor headers as identity root、local identity provider。 | Creator scope must use verified server identity. |
| Configuration | `env_or_file` server-side reader。 | Frontend `VITE_*` environment variables。 | Vite values are client-visible. |
| HTTP | Injected transport + explicit timeout style. | OTLP exporter as inference client。 | OTLP has different protocol, observability and redaction semantics. |
| Retry | None beyond generic bounded retry principles. | P6 Scheduler, Worker, Recovery, event/DLQ retry. | Those are execution/governance/persistence semantics, not model HTTP handling. |
| Tests | Minimal injected HTTP fake and current E2 PostgreSQL integration harness. | P6 trial as provider test fixture. | P6 remains a regression target, not E2.x infrastructure. |
| Frontend | Existing typed Product API adapter only. | React direct provider calls/credential storage. | Provider exists server-side only. |

## 4. Proposed Architecture

```text
React
  │ Product API only; no credentials, no provider URL
  ▼
FastAPI + verified OIDC subject
  ▼
ProductApiFacade semantic E2 route
  ▼
PostgresEntryUnderstandingStore
  ├── durable receipt lookup (replay exits here)
  ├── E2 source/creator/version checks
  ▼
UnderstandingProducer (typed request/candidate)
  ▼
ProviderRegistry
  ▼
OpenAICompatibleProviderAdapter
  ├── server-side configuration
  ├── injected HTTP transport
  ├── bounded retry/timeout/error classification
  └── structured response parsing
  ▼
UnderstandingCandidate parser
  ▼
Schema validation → E2 domain/source attribution validation
  ▼
PostgresEntryUnderstandingStore only
  ▼
Immutable E2 revision + provenance
```

The provider adapter has no PostgreSQL, FastAPI, Product API, OIDC, Project, P6 or frontend dependency. The producer receives minimised content only: Draft title/raw input, verified source Draft revision reference, prior explicit requirements if they are E2 source facts, answered clarifications, prior Understanding summary when applicable, and schema/prompt version. It must never receive bearer tokens, keys, browser headers, database credentials, P6 data, unrelated user data or internal authority metadata.

## 5. Proposed Contracts

The current `Mapping` protocol should be replaced by typed values. The minimum request is `UnderstandingGenerationRequest(draft_id, draft_revision_id, draft_revision_number, title, raw_input, explicit_requirements, answered_clarifications, previous_understanding, prompt_version, schema_version)`. The provider-facing result is `ProviderStructuredResponse(candidate_json, provider_metadata, usage, duration_ms)`; the producer converts it into a typed `UnderstandingCandidate` before E2’s existing `_validate`/domain validation.

`ProviderMetadata` must expose only nullable factual fields: `provider`, `model`, `model_version`, `request_id`, `prompt_version`, `schema_version`; `ProviderUsage` has nullable input/output/total token counts. A missing provider field remains `null`; no model, request ID, confidence, token usage or latency is guessed. `UNDERSTANDING_PROMPT_VERSION = "v1"` belongs in one immutable template module, not scattered call-site strings.

## 6. Provider Configuration and Registry

The configuration object should be `UnderstandingProviderConfig(provider, model, base_url, api_key, timeout_seconds, max_retries, schema_version)`. All values are server-only and read at startup with `env_or_file`; safe deployment defaults are **unconfigured/Unavailable**, not a hidden test/local/random provider. Suggested variables are `HERMES_UNDERSTANDING_PROVIDER`, `HERMES_UNDERSTANDING_MODEL`, `HERMES_UNDERSTANDING_BASE_URL`, `HERMES_UNDERSTANDING_API_KEY` or file reference, `HERMES_UNDERSTANDING_TIMEOUT_SECONDS`, `HERMES_UNDERSTANDING_MAX_RETRIES`, and optional schema/prompt version variables. Their values must not be logged, included in error envelopes, persisted into E2 rows or added to frontend examples.

The registry must have exactly two meaningful runtime outcomes: configured `openai-compatible` adapter, or `UnavailableUnderstandingProducer`. `TestProvider` can exist only in isolated test modules/dependency injection; registry/configuration must never silently choose it in production.

## 7. OpenAI-Compatible Adapter and Retry Policy

The adapter uses a configurable OpenAI-compatible base URL/model and requests strict JSON/schema output where the target supports it. If strict response-format support is unavailable, it parses JSON then applies the same parser/schema/domain validation chain. Unknown fields, malformed JSON, invalid enums, invalid confidence, malformed clarification/assumption, invented source attribution and explicit requirements absent from source context must fail closed.

The adapter maps timeout to `ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT`; connection/transient 5xx to `ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED`; 429 to `ENTRY_UNDERSTANDING_PROVIDER_RATE_LIMITED`; 401/403 to `ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED`; malformed provider response to `ENTRY_UNDERSTANDING_PROVIDER_INVALID_RESPONSE`; and missing config to `ENTRY_UNDERSTANDING_PROVIDER_UNAVAILABLE`. Only timeout, connection errors, 429 and 5xx are retryable. The plan is bounded exponential backoff with a small finite attempt count and a total duration cap. HTTP 400/401/403, parse/schema/domain/configuration failures do not retry.

## 8. Provenance, Privacy and Observability

`0027_e2x_producer_provenance.sql` should add nullable E2-only provenance/usage columns or a 1:1 immutable provenance table. It must record source Draft revision ID, producer, provider, model, model version, prompt/schema version, provider request ID, generated time, nullable usage and duration. Raw prompt, raw response, API key, bearer token, user raw input and credentials must not be put in logs or generic observability. Minimal structured metrics/log hooks may record provider/model/request ID/duration/status/error category/retry count only. No P6 telemetry stack is introduced.

## 9. Required Files if Implementation Is Authorized

| File | Purpose |
| --- | --- |
| `migrations/0027_e2x_producer_provenance.sql` | E2-only provenance/usage persistence. |
| `domain/understanding_producer.py` | Typed request/candidate/metadata/error contract. |
| `infrastructure/openai_compatible_understanding_provider.py` | Server-only protocol adapter, parsing, timeout/retry. |
| `infrastructure/understanding_provider_registry.py` | Minimal configured-or-unavailable factory. |
| `application/understanding_producer_service.py` | Prompt template/version and provider-to-candidate conversion only. |
| `api_main.py` | Safe server composition from environment/config. |
| `infrastructure/postgres_entry_understanding.py` | Typed producer call and E2-only provenance persistence; retain receipt-before-producer. |
| provider contract/unit tests and E2 integration tests | Provider error/retry/provenance/security/idempotency coverage. |
| required E2.x documents | Recon, Design, Delivery reports. |

## 10. Security Risks

The highest risk is accidentally treating provider output as authority. It is mitigated by a typed candidate, strict parser/schema/domain/source validation and persistence exclusively inside `PostgresEntryUnderstandingStore`. The second risk is secret leakage; it is mitigated by server-only `env_or_file`, redacted stable errors and no raw request/response logging. The third risk is duplicate/costly calls; it is mitigated by preserving receipt-before-producer and testing provider call count. The fourth risk is scope leakage; it is mitigated by retaining existing verified OIDC creator checks before E2 source reads. No frontend credential/configuration changes are allowed.

## 11. Acceptance Plan

Implementation must prove configured/missing provider, invalid credentials, timeout, 429, 500, 400, malformed JSON, schema/domain rejection, transient retry success, exhaustion, non-retryable no-retry, provider-once idempotency, metadata/null provenance, secret/token/no-raw-response leakage, producer no-DB authority, E1/E2 regression, frontend test/build/lint, P6 standalone acceptance and protected-path diff audit. E2.x can be labeled **COMPLETE** only if a real production-capable configured adapter exists and all checks pass; otherwise it remains **PARTIAL**.

## 12. Migration Decision

A migration is **required if implementation is authorized** because current E2 revision storage cannot distinguish structured provider provenance/usage fields as first-class, nullable, auditable facts. The only allowed migration is `0027_e2x_producer_provenance.sql`; it must be E2.x-only, reversible only by forward migration, and must not modify existing E1/P6/Project schema.

## 13. Recon Outcome and Required Authorization

Recon and design are complete. Implementation must wait for user authorization. The next task should explicitly authorize E2.x code/migration/provider adapter work and, if a live provider is to be exercised, identify server-side configuration ownership without sending credentials through chat or frontend code.
