import os
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_delivery import PostgresDeliveryStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def role_dsn(base_dsn, user, password):
    parsed = urlsplit(base_dsn)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        host = "{}:{}".format(host, parsed.port)
    return urlunsplit(
        (parsed.scheme, "{}:{}@{}".format(user, password, host), parsed.path, "", "")
    )


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "requires real PostgreSQL and role creation privileges",
)
class DeliveryPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresDeliveryStore(DATABASE_URL)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-delivery-role-test"
        cls.roles = {
            "relay": "hermes_test_relay_" + uuid.uuid4().hex[:8],
            "consumer": "hermes_test_consumer_" + uuid.uuid4().hex[:8],
            "operator": "hermes_test_operator_" + uuid.uuid4().hex[:8],
            "worker": "hermes_test_delivery_worker_" + uuid.uuid4().hex[:8],
            "reader": "hermes_test_delivery_reader_" + uuid.uuid4().hex[:8],
        }
        memberships = {
            "relay": "hermes_outbox_relay_runtime",
            "consumer": "hermes_consumer_runtime",
            "operator": "hermes_redrive_operator_runtime",
            "worker": "hermes_worker_runtime",
            "reader": "hermes_read_only_runtime",
        }
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for key, role in cls.roles.items():
                connection.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role), psycopg.sql.Literal(cls.password)
                    )
                )
                connection.execute(
                    psycopg.sql.SQL("GRANT {} TO {}").format(
                        psycopg.sql.Identifier(memberships[key]),
                        psycopg.sql.Identifier(role),
                    )
                )

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for role in cls.roles.values():
                connection.execute(
                    psycopg.sql.SQL("DROP ROLE IF EXISTS {}").format(
                        psycopg.sql.Identifier(role)
                    )
                )

    def setUp(self):
        self.store.reset_for_test()

    def connect_as(self, key):
        return psycopg.connect(role_dsn(DATABASE_URL, self.roles[key], self.password))

    def test_relay_can_claim_guarded_but_cannot_modify_event_or_outbox_directly(self):
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        with self.connect_as("relay") as connection:
            self.assertEqual(
                [],
                connection.execute(
                    "SELECT * FROM public.hermes_claim_outbox(%s,%s,30,10,5)",
                    ("relay-runtime", now),
                ).fetchall(),
            )
        for statement in (
            "UPDATE event_log SET event_type='forged'",
            "UPDATE outbox_messages SET status='PUBLISHED'",
            "INSERT INTO outbox_delivery_attempts(attempt_id,message_id,event_id,attempt_number,lease_owner,claim_token,outcome) VALUES ('x','x','x',1,'x','x','CLAIMED')",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("relay") as connection:
                        connection.execute(statement)

    def test_consumer_cannot_modify_project_task_event_or_grants(self):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """
                INSERT INTO command_receipts(
                    command_id,project_id,command_type,idempotency_key,
                    request_hash,status,result,completed_at
                ) VALUES ('permission-event-command','permission-project',
                          'test.permission','permission-event','hash',
                          'APPLIED','{}',now());
                INSERT INTO event_log(
                    event_id,event_type,schema_version,producer_type,producer_id,
                    project_id,partition_key,command_id,correlation_id,payload
                ) VALUES ('permission-event','test.permission','1.0',
                          'control_plane','test','permission-project',
                          'permission-project','permission-event-command',
                          'permission-event','{}')
                """
            )
        for statement in (
            "UPDATE tasks SET state='PASSED'",
            "UPDATE projects SET state='ACCEPTED'",
            "UPDATE event_log SET event_type='forged'",
            "UPDATE consumer_checkpoints SET last_sequence=999",
            "INSERT INTO consumer_effects(consumer_id,event_id,effect_count) VALUES ('x','permission-event',1)",
            "CREATE TABLE forbidden_consumer_table(id int)",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("consumer") as connection:
                        connection.execute(statement)

    def test_worker_and_reader_cannot_claim_or_redrive(self):
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        for role in ("worker", "reader"):
            with self.subTest(role=role):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            "SELECT * FROM public.hermes_claim_outbox('x',%s,30,1,5)",
                            (now,),
                        )
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            "SELECT public.hermes_redrive_outbox('x',0,'x','system_operator','x','x','x',true,%s)",
                            (now,),
                        )

    def test_public_cannot_execute_sensitive_delivery_functions(self):
        signatures = (
            "hermes_claim_outbox(text,timestamptz,integer,integer,integer)",
            "hermes_mark_outbox_published(text,text,text,timestamptz)",
            "hermes_mark_outbox_failure(text,text,text,timestamptz,boolean,text,text,timestamptz,integer)",
            "hermes_redrive_outbox(text,bigint,text,text,text,text,text,boolean,timestamptz)",
            "hermes_consumer_park_gap(text,text,text,bigint,jsonb,integer)",
            "hermes_consumer_commit_next(text,text,text,bigint,text,jsonb,jsonb,text)",
            "hermes_consumer_quarantine(text,text,text,bigint,jsonb,text,text)",
        )
        with psycopg.connect(DATABASE_URL) as connection:
            for signature in signatures:
                with self.subTest(signature=signature):
                    allowed = connection.execute(
                        "SELECT has_function_privilege('public', %s, 'EXECUTE')",
                        (signature,),
                    ).fetchone()[0]
                    self.assertFalse(allowed)

    def test_operator_has_no_direct_outbox_or_authority_write(self):
        for statement in (
            "UPDATE outbox_messages SET status='PENDING'",
            "UPDATE tasks SET state='PASSED'",
            "UPDATE projects SET state='ACCEPTED'",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as("operator") as connection:
                        connection.execute(statement)


if __name__ == "__main__":
    unittest.main()
