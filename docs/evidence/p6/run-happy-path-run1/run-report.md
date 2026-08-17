# P6 Autonomous Run Report: happy-path-run1

- scenario: happy-path
- final project state: **ACCEPTED**
- task state: **PASSED**
- recovery attempt: {"result_code": "RECOVERY_ATTEMPT_COMPLETED"}
- diagnosis: {"diagnosis_id": "diag-f280be14310d16e64c7f0c477da3a956", "input_hash": "sha256:51854ada48e3f5a18dba9999c63bfc23b5b84a95e1d3c02a0c31c65bb268c3f2", "root_cause_status": "PROBABLE", "root_cause": "test_assertion_failure"}
- independent verifier: "PASS"
- events recorded: 113

## Authority chain exercised (real services)

- project.created evt-9ea817a7-2c94-419d-9367-904b4af9a681
- work_graph.patch.applied evt-13f5eb67-d5c9-45da-a029-ed2ae7350339
- situation.detected evt-57d34884-ce1e-4d42-8e54-ac4a558bb5ee
- action.candidates_planned evt-5964d961-0361-4066-9405-315f450a00e7
- verification_plan.created evt-720890b0-1baa-48f2-98dd-e1d6b66337f9
- budget.account_created evt-f429d78a-3b21-4baa-a45c-c751afc6c3e7
- capability.schema_registered evt-9c3dcd1e-addd-4a36-8b29-5c8dede733c8
- capability.schema_registered evt-db80bdcf-d24a-4004-8880-55245a75b5cf
- worker_template.revision_created evt-6faa2ae8-771b-4d50-9bae-95eee5c11896
- worker_template.availability_changed evt-c5ec620c-6092-43ab-92c6-63df0759bd7a
- policy.evaluated evt-3796a2bf-a22d-467f-aef9-2f617c43b6cd
- risk.assessed evt-abd09b80-09ca-4c26-b1cf-8221544e113e
- ... (113 total)
