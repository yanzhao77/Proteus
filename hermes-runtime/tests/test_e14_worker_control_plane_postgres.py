import json
import os
import unittest
import uuid

from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope
from hermes_runtime.infrastructure.postgres_worker_control_plane_read_model import PostgresWorkerControlPlaneReadModel

try:
    import psycopg
except Exception:  # pragma: no cover - real-PG dependency not present in all lanes
    psycopg = None

DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")

ALICE = "e14-alice"
BOB = "e14-bob"


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+ via HERMES_TEST_DATABASE_URL")
class E14WorkerControlPlanePostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn = DATABASE_URL
        self.scope = PostgresCreatorActorProjectScope(self.dsn)
        self.model = PostgresWorkerControlPlaneReadModel(self.dsn, self.scope)

    def _unverified(self, subject=ALICE):
        return {"actor_type": "user", "actor_id": subject, "identity_verified": False, "identity_subject": subject}

    def _verified(self, subject=ALICE):
        return {"actor_type": "user", "actor_id": subject, "identity_verified": True, "identity_subject": subject}

    def test_unverified_scope_is_never_resolved(self):
        self.assertIsNone(self.scope.project_ids_for(self._unverified(ALICE)))
        self.assertIsNone(self.scope.project_ids_for(self._unverified(BOB)))

    def test_list_workers_is_creator_scoped_and_leaks_no_sensitive_fields(self):
        result = self.model.list_workers(self._verified(ALICE))
        self.assertEqual("CURRENT", result["availability"])
        alice_ids = {item["worker_id"] for item in result["items"]}
        bob_ids = {item["worker_id"] for item in self.model.list_workers(self._verified(BOB))["items"]}

        serialized = json.dumps(result)
        self.assertNotIn("fencing_token", serialized)
        self.assertNotIn("dsn", serialized.lower())
        self.assertNotIn("postgres://", serialized)
        self.assertNotIn("password", serialized.lower())

        if alice_ids or bob_ids:
            self.assertEqual(set(), alice_ids & bob_ids)
            for worker_id in alice_ids:
                detail = self.model.worker_detail(worker_id, self._verified(ALICE))
                self.assertEqual("CURRENT", detail["availability"])
                self.assertNotIn("fencing_token", json.dumps(detail))
                self.assertNotIn("dsn", json.dumps(detail).lower())

    def test_foreign_worker_detail_is_not_disclosed(self):
        alice_ids = {item["worker_id"] for item in self.model.list_workers(self._verified(ALICE))["items"]}
        bob_ids = {item["worker_id"] for item in self.model.list_workers(self._verified(BOB))["items"]}
        if not alice_ids or not bob_ids:
            self.skipTest("seed data absent: cannot exercise cross-scope isolation")
        foreign = next(iter(bob_ids - alice_ids))
        result = self.model.worker_detail(foreign, self._verified(ALICE))
        self.assertEqual("NOT_AVAILABLE", result["availability"])

    def test_execution_queue_safe_payload_has_no_sensitive_fields(self):
        result = self.model.execution_queue(self._verified(ALICE))
        self.assertIn(result["availability"], ("CURRENT", "DEGRADED"))
        serialized = json.dumps(result)
        self.assertNotIn("dsn", serialized.lower())
        self.assertNotIn("postgres://", serialized)
        self.assertNotIn("password", serialized.lower())

    def test_unknown_worker_detail_fails_closed(self):
        result = self.model.worker_detail("no-such-worker-" + uuid.uuid4().hex, self._verified(ALICE))
        self.assertEqual("NOT_AVAILABLE", result["availability"])


if __name__ == "__main__":
    unittest.main()
