"""P6 integration test: the autonomous production trial really runs.

Uses a dedicated PostgreSQL database (created and dropped by the test) and the
golden-todo test database. Runs the full harness and asserts every
acceptance-matrix row PASSes. No mocks: real authority commands, real
worker/verifier subprocesses, real pytest, real PostgreSQL.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import psycopg  # noqa: F401
except ImportError:
    psycopg = None

from hermes_runtime.trial.harness import run_trial
from hermes_runtime.trial.test_database_bootstrap import (
    create_disposable_todo_database,
)


BASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")
TODO_DATABASE_URL = os.environ.get(
    "HERMES_P6_TODO_DATABASE_URL",
    "postgresql+psycopg://todo:todo@127.0.0.1:55432/todo_test",
)


def _admin_connect(dsn: str):
    # connect to the maintenance database to create/drop the trial database
    return psycopg.connect(dsn.rsplit("/", 1)[0] + "/postgres")


@unittest.skipUnless(
    BASE_URL and psycopg,
    "requires real PostgreSQL and explicit HERMES_TEST_DATABASE_URL",
)
class P6AutonomousTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin = _admin_connect(BASE_URL)
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute("DROP DATABASE IF EXISTS hermes_p6_ci")
            cursor.execute("CREATE DATABASE hermes_p6_ci")
        admin.close()
        cls.database_url = BASE_URL.rsplit("/", 1)[0] + "/hermes_p6_ci"
        cls.addClassCleanup(cls._drop_control_database)
        cls.todo_database = create_disposable_todo_database(BASE_URL, TODO_DATABASE_URL)
        cls.addClassCleanup(cls.todo_database.cleanup)

    @classmethod
    def _drop_control_database(cls):
        admin = _admin_connect(BASE_URL)
        admin.autocommit = True
        try:
            with admin.cursor() as cursor:
                cursor.execute("DROP DATABASE IF EXISTS hermes_p6_ci")
        finally:
            admin.close()

    def test_full_autonomous_trial_acceptance_matrix_all_pass(self):
        with tempfile.TemporaryDirectory(prefix="p6-workspaces-") as workspace_tmp, \
                tempfile.TemporaryDirectory(prefix="p6-evidence-") as evidence_tmp:
            result = run_trial(
                self.database_url,
                Path(workspace_tmp),
                Path(evidence_tmp),
                self.todo_database.runtime_todo_dsn,
            )
        self.assertEqual("PASS", result["verdict"], result)
        failed = [row for row in result["rows"] if row["outcome"] != "PASS"]
        self.assertEqual([], failed, result)
        self.assertTrue(len(result["rows"]) >= 8, result)


if __name__ == "__main__":
    unittest.main()
