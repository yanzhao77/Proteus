"""E4 durable approval bridge evidence against a real disposable PostgreSQL database.

Every child side effect uses the repository ControlPlane backed by
PostgresProjectStore.  The only fault injector is a wrapper that calls that real
port first and then simulates a process interruption at the acknowledgement
boundary; recovery always uses a newly-created orchestrator and store instance.
"""
import inspect
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:
    psycopg = None

from hermes_runtime.application.commands import CreateProject
from hermes_runtime.application.durable_approval_bridge_orchestrator import DurableApprovalBridgeOrchestrator
from hermes_runtime.application.entry_approval_bridge_saga import ApprovalBridgeSaga
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.entry_approval_bridge import EntryE4Rejected, preview_approval
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_entry_approval_bridge import PostgresEntryApprovalBridgeStore
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
try:
    # Direct module execution from hermes-runtime uses the tests namespace.
    from tests.test_e3_proposal_master_plan_postgres import E3ProposalMasterPlanPostgresTests
except ModuleNotFoundError:
    # Repository-root CI discovery sets hermes-runtime/tests as the top-level.
    from test_e3_proposal_master_plan_postgres import E3ProposalMasterPlanPostgresTests

DATABASE_URL = os.getenv("HERMES_TEST_DATABASE_URL")


class SimulatedProcessCrash(RuntimeError):
    """Raised only after a real ControlPlane child command has committed."""


class FaultInjectingControlPlane:
    """Wrap a real child authority and interrupt after exactly one committed call."""

    def __init__(self, actual, boundary):
        self.actual = actual
        self.boundary = boundary
        self.verification_calls = 0
        self.fired = False

    def _after(self, boundary, invoke):
        receipt = invoke()
        if not self.fired and self.boundary == boundary:
            self.fired = True
            raise SimulatedProcessCrash("simulated process crash after {} commit".format(boundary))
        return receipt

    def create_project(self, command):
        return self._after("PROJECT", lambda: self.actual.create_project(command))

    def apply_work_graph_patch(self, command):
        return self._after("GRAPH", lambda: self.actual.apply_work_graph_patch(command))

    def create_verification_plan(self, command):
        self.verification_calls += 1
        return self._after("VERIFICATION_{}".format(self.verification_calls), lambda: self.actual.create_verification_plan(command))


@unittest.skipUnless(psycopg is not None and DATABASE_URL, "requires HERMES_TEST_DATABASE_URL")
class E4ApprovalBridgePostgresDurabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        E3ProposalMasterPlanPostgresTests.setUpClass()

    def setUp(self):
        # E4 derives deterministic bridge/child IDs from an E3 plan revision.
        # Start every matrix scenario from an isolated durable authority history.
        PostgresProjectStore(DATABASE_URL).reset_for_test()
        with psycopg.connect(DATABASE_URL) as c:
            c.execute(
                "TRUNCATE TABLE public.entry_approval_materialized_bindings, "
                "public.entry_approval_bridge_transitions, "
                "public.entry_approval_bridge_steps, "
                "public.entry_approval_bridges, "
                "public.entry_approval_command_receipts CASCADE"
            )
        E3ProposalMasterPlanPostgresTests.setUp(self)
        self.e4 = PostgresEntryApprovalBridgeStore(DATABASE_URL)
        self.store.generate_proposal(self.alice, self.draft_id, 0, "e4-durable-proposal", "E4 durable source")
        self.store.generate_master_plan(self.alice, self.draft_id, 0, "e4-durable-plan", "E4 durable plan")
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            self.source = self.e4._source(c, self.alice, self.draft_id)
        self.preview = preview_approval(self.source)

    def _payload(self, key, **overrides):
        source = self.source
        payload = {
            "reason": "durable PostgreSQL approval",
            "idempotency_key": key,
            "expected_draft_version": source.draft_version,
            "master_plan_id": source.plan_id,
            "expected_plan_version": source.plan_version,
            "plan_revision_id": source.plan_revision_id,
            "approved_plan_content_hash": source.plan_content_hash,
            "proposal_revision_id": source.proposal_revision_id,
            "proposal_content_hash": source.proposal_content_hash,
            "compiled_blueprint_hash": self.preview.compiled_blueprint_hash,
            "acknowledgements": list(self.preview.required_acknowledgements),
            "correlation_id": "e4-durable-correlation",
        }
        payload.update(overrides)
        return payload

    def _fresh_orchestrator(self, control_plane=None):
        bridge_store = PostgresEntryApprovalBridgeStore(DATABASE_URL)
        port = control_plane or ControlPlane(PostgresProjectStore(DATABASE_URL))
        return DurableApprovalBridgeOrchestrator(bridge_store, ApprovalBridgeSaga(port, bridge_store))

    def _bridge(self):
        return PostgresEntryApprovalBridgeStore(DATABASE_URL).load_bridge(self.alice, self.draft_id)

    def _rows(self, bridge_id):
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            bridge = c.execute(
                "SELECT * FROM public.entry_approval_bridges WHERE bridge_id=%s", (bridge_id,)
            ).fetchone()
            child_ids = [bridge["project_command_id"], bridge["graph_command_id"]]
            child_ids.extend(task["create_command_id"] for task in bridge["compiled_blueprint"]["tasks"])
            return {
                "receipt": c.execute(
                    "SELECT * FROM public.entry_approval_command_receipts "
                    "WHERE creator_subject=%s ORDER BY created_at DESC LIMIT 1", (self.alice,)
                ).fetchone(),
                "bridge": bridge,
                "steps": list(c.execute(
                    "SELECT * FROM public.entry_approval_bridge_steps WHERE bridge_id=%s ORDER BY created_at,step_id", (bridge_id,)
                )),
                "transitions": list(c.execute(
                    "SELECT * FROM public.entry_approval_bridge_transitions WHERE bridge_id=%s ORDER BY created_at,transition_id", (bridge_id,)
                )),
                "bindings": list(c.execute(
                    "SELECT * FROM public.entry_approval_materialized_bindings WHERE bridge_id=%s", (bridge_id,)
                )),
                "projects": c.execute("SELECT count(*) AS n FROM public.projects WHERE project_id=%s", (bridge["intended_project_id"],)).fetchone()["n"],
                "tasks": c.execute("SELECT count(*) AS n FROM public.tasks WHERE project_id=%s", (bridge["intended_project_id"],)).fetchone()["n"],
                "dependencies": c.execute("SELECT count(*) AS n FROM public.task_dependencies WHERE project_id=%s", (bridge["intended_project_id"],)).fetchone()["n"],
                "plans": c.execute("SELECT count(*) AS n FROM public.verification_plans WHERE project_id=%s", (bridge["intended_project_id"],)).fetchone()["n"],
                "child_receipts": c.execute(
                    "SELECT count(*) AS n FROM public.command_receipts WHERE command_id = ANY(%s)", (child_ids,)
                ).fetchone()["n"],
            }

    def _assert_no_child_side_effects(self):
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            self.assertEqual(0, c.execute("SELECT count(*) AS n FROM public.projects").fetchone()["n"])
            self.assertEqual(0, c.execute("SELECT count(*) AS n FROM public.tasks").fetchone()["n"])
            self.assertEqual(0, c.execute("SELECT count(*) AS n FROM public.verification_plans").fetchone()["n"])

    def _approve_raw(self, key):
        return self.e4.approve(self.alice, self.draft_id, self._payload(key))

    def _materialize(self, key):
        result = self._fresh_orchestrator().approve(self.alice, self.draft_id, self._payload(key))
        self.assertEqual("MATERIALIZED", result["status"])
        return result

    def _assert_materialized_counts(self, bridge_id):
        rows = self._rows(bridge_id)
        self.assertEqual("MATERIALIZED", rows["bridge"]["status"])
        self.assertEqual(1, rows["projects"])
        self.assertEqual(len(rows["bridge"]["compiled_blueprint"]["tasks"]), rows["tasks"])
        self.assertEqual(len(rows["bridge"]["compiled_blueprint"]["dependencies"]), rows["dependencies"])
        self.assertEqual(len(rows["bridge"]["compiled_blueprint"]["tasks"]), rows["plans"])
        self.assertEqual(4, rows["child_receipts"])
        self.assertEqual(4, len(rows["steps"]))
        self.assertEqual(1, len(rows["bindings"]))
        return rows

    def _assert_after_call_crash_recovers(self, boundary):
        key = "fault-{}".format(boundary.lower())
        fault_port = FaultInjectingControlPlane(ControlPlane(PostgresProjectStore(DATABASE_URL)), boundary)
        accepted = self._fresh_orchestrator(fault_port).approve(self.alice, self.draft_id, self._payload(key))
        self.assertEqual("PROCESSING", accepted["status"])
        self.assertTrue(fault_port.fired)
        bridge_id = accepted["bridge_id"]
        before = self._rows(bridge_id)
        self.assertGreaterEqual(before["child_receipts"], 1)
        result = self._fresh_orchestrator().reconcile(
            self.alice, self.draft_id,
            {"reason": "fresh instance recovery", "idempotency_key": "reconcile-{}".format(boundary), "correlation_id": "recovery"},
        )
        self.assertEqual("MATERIALIZED", result["status"])
        self._assert_materialized_counts(bridge_id)

    def test_01_receipt_commits_before_any_child_side_effect(self):
        accepted = self._approve_raw("receipt-first")
        rows = self._rows(accepted["bridge_id"])
        self.assertEqual("PROCESSING", rows["receipt"]["status"])
        self.assertEqual("PROCESSING", rows["bridge"]["status"])
        self.assertEqual([], rows["steps"])
        self.assertEqual(0, rows["child_receipts"])
        self._assert_no_child_side_effects()

    def test_02_same_idempotency_key_replays_authoritative_receipt(self):
        first = self._approve_raw("approval-replay")
        second = PostgresEntryApprovalBridgeStore(DATABASE_URL).approve(self.alice, self.draft_id, self._payload("approval-replay"))
        self.assertEqual(first, second)
        rows = self._rows(first["bridge_id"])
        self.assertEqual(1, len(rows["transitions"]))
        self.assertEqual(0, rows["child_receipts"])

    def test_03_same_key_changed_request_is_rejected_without_child_effect(self):
        self._approve_raw("approval-conflict")
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_IDEMPOTENCY_CONFLICT"):
            self.e4.approve(self.alice, self.draft_id, self._payload("approval-conflict", reason="changed"))
        self._assert_no_child_side_effects()

    def test_04_blueprint_hash_mismatch_rejects_before_receipt(self):
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_BLUEPRINT_MISMATCH"):
            self.e4.approve(self.alice, self.draft_id, self._payload("bad-blueprint", compiled_blueprint_hash="0" * 64))
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            self.assertEqual(0, c.execute("SELECT count(*) AS n FROM public.entry_approval_command_receipts").fetchone()["n"])
        self._assert_no_child_side_effects()

    def test_05_stale_source_version_rejects_before_receipt(self):
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_VERSION_CONFLICT"):
            self.e4.approve(self.alice, self.draft_id, self._payload("stale", expected_plan_version=99))
        self._assert_no_child_side_effects()

    def test_06_creator_isolation_is_no_leak(self):
        self._approve_raw("creator-isolation")
        result = self.e4.get_approval(self.bob, self.draft_id)
        self.assertEqual("NOT_AVAILABLE", result["availability"])
        self.assertIsNone(result["item"])

    def test_07_raw_store_reconcile_is_fail_closed_pending_saga_adapter(self):
        accepted = self._approve_raw("store-reconcile")
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_RECONCILIATION_REQUIRED"):
            self.e4.reconcile(self.alice, self.draft_id, {"reason": "raw", "idempotency_key": "raw", "correlation_id": "raw"})
        self.assertEqual("PROCESSING", self._rows(accepted["bridge_id"])["bridge"]["status"])

    def test_08_real_control_plane_materializes_frozen_plan(self):
        result = self._materialize("real-materialize")
        self._assert_materialized_counts(result["bridge_id"])

    def test_09_fresh_orchestrator_replay_after_materialization_is_idempotent(self):
        first = self._materialize("materialized-restart")
        replay = self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "restart", "idempotency_key": "restart", "correlation_id": "restart"})
        self.assertEqual(first["project_id"], replay["project_id"])
        self._assert_materialized_counts(first["bridge_id"])

    def test_10_crash_after_receipt_before_project_recovers_on_fresh_instance(self):
        accepted = self._approve_raw("crash-after-receipt")
        result = self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "restart", "idempotency_key": "r10", "correlation_id": "r10"})
        self.assertEqual("MATERIALIZED", result["status"])
        self._assert_materialized_counts(accepted["bridge_id"])

    def test_11_crash_after_real_project_commit_before_e4_ack_recovers(self):
        self._assert_after_call_crash_recovers("PROJECT")

    def test_12_crash_after_real_graph_commit_before_e4_ack_recovers(self):
        self._assert_after_call_crash_recovers("GRAPH")

    def test_13_crash_after_first_real_verification_commit_before_e4_ack_recovers(self):
        self._assert_after_call_crash_recovers("VERIFICATION_1")

    def test_14_crash_after_second_real_verification_commit_before_e4_ack_recovers(self):
        self._assert_after_call_crash_recovers("VERIFICATION_2")

    def test_15_duplicate_fresh_reconcile_creates_zero_extra_children(self):
        accepted = self._approve_raw("duplicate-reconcile")
        first = self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "first", "idempotency_key": "r15a", "correlation_id": "r15"})
        rows_before = self._assert_materialized_counts(accepted["bridge_id"])
        second = self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "second", "idempotency_key": "r15b", "correlation_id": "r15"})
        rows_after = self._assert_materialized_counts(accepted["bridge_id"])
        self.assertEqual(first, second)
        self.assertEqual(rows_before["child_receipts"], rows_after["child_receipts"])
        self.assertEqual(len(rows_before["steps"]), len(rows_after["steps"]))

    def test_16_concurrent_fresh_reconciles_converge_without_duplicate_children(self):
        accepted = self._approve_raw("concurrent-reconcile")
        def reconcile(index):
            return self._fresh_orchestrator().reconcile(
                self.alice, self.draft_id,
                {"reason": "concurrent", "idempotency_key": "r16-{}".format(index), "correlation_id": "r16"},
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reconcile, (1, 2)))
        self.assertTrue(all(result["status"] == "MATERIALIZED" for result in results))
        self._assert_materialized_counts(accepted["bridge_id"])

    def test_17_real_child_project_identity_collision_is_terminal(self):
        accepted = self._approve_raw("terminal-collision")
        bridge = self._bridge()
        actor = Actor(ActorType.CONTROL_PLANE, "e4-terminal-fixture")
        collision = CreateProject(
            CommandEnvelope("terminal-collision-project", "project.create", "terminal-collision-project", 0, actor, "fixture collision", bridge["compiled_blueprint"]["project_id"]),
            "fixture collision", actor,
        )
        ControlPlane(PostgresProjectStore(DATABASE_URL)).create_project(collision)
        terminal = self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "collision", "idempotency_key": "r17", "correlation_id": "r17"})
        self.assertEqual("FAILED_TERMINAL", terminal["status"])
        self.assertEqual("PROJECT_ALREADY_EXISTS", terminal["reason_code"])
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_TERMINAL"):
            self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"reason": "replay", "idempotency_key": "r17b", "correlation_id": "r17"})
        rows = self._rows(accepted["bridge_id"])
        self.assertEqual("FAILED_TERMINAL", rows["bridge"]["status"])
        self.assertEqual(0, rows["tasks"])
        self.assertEqual(0, rows["plans"])

    def test_18_invalid_reconcile_schema_mutates_nothing(self):
        accepted = self._approve_raw("invalid-reconcile")
        with self.assertRaisesRegex(EntryE4Rejected, "ENTRY_APPROVAL_SCHEMA_INVALID"):
            self._fresh_orchestrator().reconcile(self.alice, self.draft_id, {"unexpected": True})
        rows = self._rows(accepted["bridge_id"])
        self.assertEqual("PROCESSING", rows["bridge"]["status"])
        self.assertEqual(0, rows["child_receipts"])

    def test_19_frozen_bridge_identity_and_blueprint_are_database_immutable(self):
        accepted = self._approve_raw("immutable-bridge")
        with psycopg.connect(DATABASE_URL) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_approval_bridges SET compiled_blueprint='{}'::jsonb WHERE bridge_id=%s", (accepted["bridge_id"],))
            c.rollback()

    def test_20_approval_receipt_cannot_be_rewritten_or_deleted(self):
        accepted = self._approve_raw("immutable-receipt")
        with psycopg.connect(DATABASE_URL) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_approval_command_receipts SET result_payload='{}'::jsonb WHERE creator_subject=%s", (self.alice,))
            c.rollback()
            with self.assertRaises(psycopg.Error):
                c.execute("DELETE FROM public.entry_approval_command_receipts WHERE creator_subject=%s", (self.alice,))
            c.rollback()
        self.assertEqual("PROCESSING", self._rows(accepted["bridge_id"])["bridge"]["status"])

    def test_21_child_step_records_are_database_immutable(self):
        result = self._materialize("immutable-step")
        with psycopg.connect(DATABASE_URL) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_approval_bridge_steps SET status='FAILED_TERMINAL' WHERE bridge_id=%s", (result["bridge_id"],))
            c.rollback()

    def test_22_transition_records_are_database_immutable(self):
        result = self._materialize("immutable-transition")
        with psycopg.connect(DATABASE_URL) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("DELETE FROM public.entry_approval_bridge_transitions WHERE bridge_id=%s", (result["bridge_id"],))
            c.rollback()

    def test_23_materialized_binding_is_database_immutable(self):
        result = self._materialize("immutable-binding")
        with psycopg.connect(DATABASE_URL) as c:
            with self.assertRaises(psycopg.Error):
                c.execute("UPDATE public.entry_approval_materialized_bindings SET project_id='forbidden' WHERE bridge_id=%s", (result["bridge_id"],))
            c.rollback()

    def test_24_control_plane_runtime_has_no_direct_child_table_dml_grants(self):
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            count = c.execute(
                "SELECT count(*) AS n FROM information_schema.role_table_grants "
                "WHERE grantee='hermes_control_plane_runtime' "
                "AND privilege_type IN ('INSERT','UPDATE','DELETE') "
                "AND table_name IN ('projects','tasks','task_dependencies','verification_plans')"
            ).fetchone()["n"]
        self.assertEqual(0, count)

    def test_25_control_plane_runtime_direct_project_insert_is_denied(self):
        with psycopg.connect(DATABASE_URL) as c:
            c.execute("SET LOCAL ROLE hermes_control_plane_runtime")
            with self.assertRaises(psycopg.Error):
                c.execute("INSERT INTO public.projects(project_id,title,state,version,last_command_id) VALUES('e4-direct-dml','forbidden','CREATED',0,'e4-direct-dml')")
            c.rollback()

    def test_26_e4_store_source_contains_no_direct_child_authority_dml(self):
        source = inspect.getsource(PostgresEntryApprovalBridgeStore).lower()
        for forbidden in (
            "insert into public.projects", "update public.projects", "delete from public.projects",
            "insert into public.tasks", "update public.tasks", "delete from public.tasks",
            "insert into public.task_dependencies", "insert into public.verification_plans",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
