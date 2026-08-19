import os
import unittest
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

from hermes_runtime.domain.recovery import hash_payload
from hermes_runtime.infrastructure.postgres_recovery import PostgresRecoveryStore

try:
    from . import test_recovery_postgres as recovery_fixtures
except ImportError:
    import test_recovery_postgres as recovery_fixtures


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class P6RecoveryRuntimeLeastPrivilegeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresRecoveryStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.admin.apply_migration(migration)

    def setUp(self):
        # Reuse the existing Recovery PostgreSQL fixture so the command is invoked
        # against an unchanged, legal failed-execution authority state.
        self.fixture_case = recovery_fixtures.RecoveryPostgresTests(
            "test_feedback_diagnosis_planning_recovery_attempt_and_independent_pass"
        )
        self.fixture_case.store = self.admin
        self.fixture_case.setUp()
        self.failed_result = self.fixture_case.submit_failed_execution_result("runtime-role")
        self.assertEqual("result-runtime-role", self.failed_result["result_id"])

    def _feedback_args(self, command_id, idempotency_key, feedback_id, fault_point=None):
        payload = {
            "command": "recovery.emit_feedback",
            "project_id": "project-1",
            "result_id": self.failed_result["result_id"],
            "feedback_id": feedback_id,
            "repair_task_id": "repair-task-runtime-role",
            "max_attempts": 2,
            "actor_type": "recovery_controller",
            "actor_id": "recovery-controller",
            "reason": "emit execution failure feedback",
        }
        return (
            "project-1",
            self.failed_result["result_id"],
            feedback_id,
            "repair-task-runtime-role",
            2,
            command_id,
            idempotency_key,
            hash_payload(payload),
            "recovery_controller",
            "recovery-controller",
            "emit execution failure feedback",
            fault_point,
        )

    @staticmethod
    def _feedback_sql():
        return """SELECT public.hermes_emit_execution_feedback(
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        ) AS result"""

    def _assert_literal_direct_update_forbidden(self):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("BEGIN")
            connection.execute("SET LOCAL ROLE hermes_recovery_runtime")
            with self.assertRaises(psycopg.Error) as raised:
                # Literal assignment is deliberate: it requires UPDATE, not SELECT.
                connection.execute("UPDATE public.tasks SET state = 'PASSED' WHERE FALSE")
            self.assertEqual("42501", raised.exception.sqlstate)
            connection.rollback()

    def _counts(self, command_id, feedback_id):
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(
                """SELECT
                    (SELECT count(*) FROM execution_feedback_records WHERE feedback_id=%s),
                    (SELECT count(*) FROM recovery_cycles WHERE feedback_id=%s),
                    (SELECT count(*) FROM command_receipts WHERE command_id=%s),
                    (SELECT count(*) FROM event_log WHERE command_id=%s),
                    (SELECT state FROM tasks WHERE task_id='task-1')""",
                (feedback_id, feedback_id, command_id, command_id),
            ).fetchone()

    def _runtime_emit(self, args):
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
            connection.execute("BEGIN")
            connection.execute("SET LOCAL ROLE hermes_recovery_runtime")
            first = connection.execute(self._feedback_sql(), args).fetchone()["result"]
            replay = connection.execute(self._feedback_sql(), args).fetchone()["result"]
            connection.execute("RESET ROLE")
            state = connection.execute(
                "SELECT state FROM public.tasks WHERE task_id='task-1'"
            ).fetchone()["state"]
            connection.commit()
        return dict(first), dict(replay), state

    def test_runtime_command_reenters_task_without_direct_table_update_and_replays(self):
        self._assert_literal_direct_update_forbidden()
        command_id = "cmd-runtime-role-feedback"
        feedback_id = "feedback-runtime-role"
        first, replay, state = self._runtime_emit(
            self._feedback_args(command_id, "key-runtime-role-feedback", feedback_id)
        )
        self.assertEqual("RECOVERY_FEEDBACK_EMITTED", first["result_code"])
        self.assertEqual(first, replay)
        self.assertEqual("READY", state)
        self.assertEqual((1, 1, 1, 3, "READY"), self._counts(command_id, feedback_id))
        self._assert_literal_direct_update_forbidden()

    def test_runtime_command_fault_rolls_back_without_partial_authority_state(self):
        command_id = "cmd-runtime-role-fault"
        feedback_id = "feedback-runtime-role-fault"
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("BEGIN")
            connection.execute("SET LOCAL ROLE hermes_recovery_runtime")
            with self.assertRaises(psycopg.Error):
                connection.execute(
                    self._feedback_sql(),
                    self._feedback_args(
                        command_id,
                        "key-runtime-role-fault",
                        feedback_id,
                        "after_feedback_record",
                    ),
                )
            connection.rollback()
        self.assertEqual((0, 0, 0, 0, "RUNNING"), self._counts(command_id, feedback_id))
        self._assert_literal_direct_update_forbidden()


if __name__ == "__main__":
    unittest.main()
