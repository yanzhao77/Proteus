# Hermes P4 Productization Acceptance Matrix

Date: 2026-08-14

Status: P4-0 contract closure complete; P4-1 through P4-5 pending until their
implementation commits land.

| Row | Requirement | Authority invariant | Slice | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| P4-CONTRACT-001 | P4 productization boundary is specified before code. | Product API/UI/ports wrap existing authority; no new core authority path. | P4-0 | PASS | `docs/specs/Hermes_P4_Productization_Normative_Spec_V1.0.md`, ADR-0065 through ADR-0068 |
| P4-API-001 | Public API rejects generic patch/state/event/SQL mutation and only exposes semantic wrappers. | API cannot bypass Control Plane, Verification, Gate, Policy/Risk/Budget or Lease/Fencing. | P4-1 | PASS | `product_api.py`, `http_api.py`, `test_public_api_domain.py`, `test_public_api_boundary.py` |
| P4-API-002 | Authority-changing API requests require command metadata and preserve actor/idempotency/expected-version scope. | Product facade does not synthesize facts or mutate state directly. | P4-1 | PASS | `test_human_gate_decision_preserves_actor_scope_and_command_metadata`, `test_missing_idempotency_and_stale_expected_version_shape_are_rejected` |
| P4-GATE-001 | Human Gate product facade separates identity assertion, decision submission and resume application. | Gate Decision is not Project resume; self/unauthorized approval fails closed. | P4-2 | PASS | `identity.py`, `human_gate_product.py`, `local_identity.py`, `test_human_gate_product_boundary.py` |
| P4-GATE-002 | Invalidated Evidence blocks new Gate decisions and existing resume authority. | Product Gate cannot revive stale authorization. | P4-2 | PASS | `test_stale_gate_version_and_invalid_evidence_fail_closed`, `test_present_and_submit_decision_without_resume_authority` |
| P4-ART-001 | Artifact store is immutable, content-addressed and provenance-bound. | Verification binds exact hash, not mutable path. | P4-3 | PASS | `product_artifacts.py`, `local_artifact_store.py`, `test_content_addressed_artifact_is_deterministic_and_immutable` |
| P4-SEC-001 | Secret provider returns handles only and rejects leakage into API/Event/log/export/artifact paths. | Secret values never become authority/audit payload. | P4-3 | PASS | `secret_handles.py`, `local_secrets.py`, `test_secret_handle_provider_never_returns_secret_value_to_payloads` |
| P4-RET-001 | Retention/archive/purge preserves authority metadata and dependency tombstones. | Raw content removal cannot erase Decision/Verification/Gate evidence. | P4-3 | PASS | `test_retention_preserves_tombstone_and_blocks_active_authority_dependency` |
| P4-OBS-001 | Observability/export is read-only diagnostic surface with redaction. | Metrics/traces cannot authorize actions or fabricate missing links. | P4-4 | PASS | `observability.py`, `local_observability.py`, `test_observability_export_boundary.py` |
| P4-E2E-001 | P4 end-to-end productization hardening covers API, Gate, Artifact, Secret, Retention and Observability. | Productization does not bypass P0-P3 authority chain. | P4-5 | PENDING | Pending P4-5 tests |

## Deferred scope

- Production FastAPI/Web UI server.
- Production IdP/OIDC/SAML.
- Cloud object store and production secret manager.
- Production OpenTelemetry backend.
- P3/P4 external irreversible side-effect reconcile beyond existing receipts.
