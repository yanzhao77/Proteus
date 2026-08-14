# Hermes P5 Deployable Product Acceptance Matrix

Date: 2026-08-14

Status: P5-0 contract closure started; implementation rows remain `PENDING`.

| Row | Requirement | Authority invariant | Slice | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| P5-CONTRACT-001 | P5 deployment/product boundary is specified before code. | P5 adds product transport/adapters but no second state authority. | P5-0 | SPECIFIED | `docs/specs/Hermes_P5_Deployable_Product_Normative_Spec_V1.0.md`, ADR-0069 through ADR-0072 |
| P5-CONTRACT-002 | P4 completion summary reflects merged baseline. | P5 starts from `origin/master` after P4 merge, not stale feature branch wording. | P5-0 | SPECIFIED | `docs/Hermes_P4_COMPLETION_SUMMARY.md` |
| P5-API-001 | FastAPI service exposes only allowlisted semantic routes. | API cannot bypass Control Plane or expose generic mutation. | P5-1 | PASS | `fastapi_app.py`, `test_read_routes_are_allowlisted_and_generic_routes_are_absent` |
| P5-API-002 | Authority-changing endpoints validate command metadata and idempotency. | API preserves command_id/idempotency_key/expected_version/actor/reason. | P5-1 | PASS | `GateDecisionDto`, `test_authority_changing_route_requires_content_type_idempotency_and_metadata` |
| P5-API-003 | Error envelope and redaction prevent secret/internal leakage. | Exceptions/log-like payloads do not become covert secret channels. | P5-1 | PASS | `test_errors_are_redacted_and_body_size_is_bounded` |
| P5-API-004 | Live/readiness endpoints are health-only. | Health cannot mutate authority or enqueue repairs. | P5-1 | PASS | `readiness.py`, `/livez`, `/readyz`, `test_livez_readyz_are_health_only` |
| P5-SERVICE-001 | Runtime supervisor loops are bounded, cancellable and readiness-aware. | Loops orchestrate existing services without duplicating authority logic. | P5-2 | PASS | `supervisor.py`, `test_runtime_supervisor.py` |
| P5-SERVICE-002 | Multi-instance safety relies on DB lease/fencing/idempotency. | Process-local locks are not correctness claims. | P5-2 | PASS | `test_multi_instance_roles_declare_database_fencing_not_local_lock_correctness`, P2/P3 PostgreSQL lease/fencing regression |
| P5-IDP-001 | OIDC/JWT verifier validates signature, issuer, audience, subject, time and algorithm. | Identity assertion is scoped fact, not Project resume authority. | P5-3 | PASS | `oidc.py`, `test_oidc_valid_token_maps_to_actor_and_gate_assertion`, `test_oidc_negative_security_cases_fail_closed` |
| P5-IDP-002 | Production profile disables local/test issuer. | Test identity cannot become production bypass. | P5-3 | PASS | `test_production_profile_rejects_local_test_issuer` |
| P5-UI-001 | Human Gate UI presents inbox/detail/evidence/risk/reason/decision/status/explain. | UI can submit Gate Decision only. | P5-3 | PARTIAL | `human_gate_ui.py`, `/ui/human-gates`, `test_human_gate_ui_contains_required_controls_but_no_resume_or_generic_editor`; Playwright/browser screenshot evidence not available in this run |
| P5-UI-002 | UI has no generic editor or direct resume/status controls. | UI cannot mutate Project/Task authority directly. | P5-3 | PARTIAL | `test_human_gate_ui_contains_required_controls_but_no_resume_or_generic_editor`, `test_ui_rejects_secret_payload`; browser evidence pending |
| P5-ART-001 | S3-compatible adapter is immutable and content-addressed. | Verification remains bound to exact hash, not URL/path. | P5-4 | PARTIAL | `s3_artifact_store.py`, local adapter contract tests pass; real MinIO integration not completed in this run |
| P5-SECRET-001 | Secret Manager adapter exposes handle metadata and resolves only at execution boundary. | Secret values do not enter API/UI/Event/Outbox/log/trace/artifact. | P5-4 | PARTIAL | `vault_secrets.py`, local adapter contract tests pass; real Vault integration not completed in this run |
| P5-OBS-001 | OTLP-compatible exporter redacts and bounds backend failure behavior. | Observability cannot authorize, recover, PASS/FAIL or advance checkpoint. | P5-4 | PARTIAL | `otlp_exporter.py`, local exporter contract tests pass; real OTLP backend integration not completed in this run |
| P5-DEPLOY-001 | Single-node deployment baseline defines entrypoints, Compose and hardened container posture. | Deployment roles preserve least privilege and separate migration/bootstrap. | P5-5 | PARTIAL | `Dockerfile`, `docker-compose.single-node.yml`, `api_main.py`, `supervisor_main.py`, `migration_bootstrap.py`, `test_deployment_baseline.py`; Docker build blocked by Docker Hub metadata timeout |
| P5-DEPLOY-002 | Operations runbook covers readiness, backup/restore, migrations, rotation and rollback. | Ops repair does not become generic authority patch. | P5-5 | PASS | `docs/operations/P5_SINGLE_NODE_RUNBOOK.md`, `.github/workflows/hermes-p5.yml`, `test_runbook_covers_backup_restore_rotation_and_forbidden_repairs` |
| P5-E2E-001 | Full P5 E2E/fault-injection hardening passes. | API/OIDC/UI/supervisor/adapters/observability preserve P0-P4 invariants. | P5-6 | PARTIAL | `test_p5_end_to_end_product_hardening.py`, `docs/Hermes_P5_COMPLETION_SUMMARY.md`; full external-container/browser E2E remains blocked |

Skipped or mocked external checks MUST NOT be counted as PASS.
