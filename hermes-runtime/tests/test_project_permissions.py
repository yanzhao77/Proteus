import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore


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
class ProjectPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresProjectStore(DATABASE_URL)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-role-test"
        cls.roles = {
            "worker": "hermes_test_worker_" + uuid.uuid4().hex[:8],
            "reader": "hermes_test_reader_" + uuid.uuid4().hex[:8],
            "control": "hermes_test_control_" + uuid.uuid4().hex[:8],
        }
        memberships = {
            "worker": "hermes_worker_runtime",
            "reader": "hermes_read_only_runtime",
            "control": "hermes_control_plane_runtime",
        }
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for key, role in cls.roles.items():
                connection.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role),
                        psycopg.sql.Literal(cls.password),
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
        return psycopg.connect(
            role_dsn(DATABASE_URL, self.roles[key], self.password)
        )

    def test_worker_and_read_only_roles_cannot_write_project_authority(self):
        for role in ("worker", "reader"):
            with self.subTest(role=role):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            """
                            INSERT INTO projects
                              (project_id, title, state, version, last_command_id)
                            VALUES ('forged', 'forged', 'ACCEPTED', 9, 'missing')
                            """
                        )
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            "UPDATE projects SET state = 'ACCEPTED', version = 99"
                        )

    def test_worker_cannot_insert_authoritative_event(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("worker") as connection:
                connection.execute(
                    """
                    INSERT INTO event_log
                      (event_id, event_type, schema_version, producer_type, producer_id,
                       project_id, partition_key, command_id, correlation_id, payload)
                    VALUES ('forged-event', 'project.state_transition.applied', '1.0',
                            'worker', 'worker-1', 'project-1', 'project-1',
                            'forged-command', 'forged', '{}'::jsonb)
                    """
                )

    def _insert_guard_facts_as_admin(self, project_id, version, from_state, to_state, suffix):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """
                INSERT INTO project_evidence_facts
                  (evidence_fact_id, project_id, project_version, from_state, to_state,
                   result, authority, subject_ref)
                VALUES (%s, %s, %s, %s, %s, 'VALID', 'verification_engine', %s);
                """,
                (
                    "evidence-" + suffix,
                    project_id,
                    version,
                    from_state,
                    to_state,
                    "subject-" + suffix,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_policy_decision_facts
                  (policy_decision_id, project_id, project_version, from_state,
                   to_state, result, authority, policy_bundle_version, input_hash)
                VALUES (%s, %s, %s, %s, %s, 'ALLOW', 'policy_engine',
                        'policy-test', %s);
                """,
                (
                    "policy-" + suffix,
                    project_id,
                    version,
                    from_state,
                    to_state,
                    "sha256:" + uuid.uuid4().hex,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_budget_facts
                  (budget_fact_id, project_id, project_version, from_state, to_state,
                   status, authority, budget_scope_id, version)
                VALUES (%s, %s, %s, %s, %s, 'OK', 'budget_engine', %s, 1)
                """,
                (
                    "budget-" + suffix,
                    project_id,
                    version,
                    from_state,
                    to_state,
                    "budget-" + project_id,
                ),
            )

    def test_control_plane_role_cannot_update_directly_but_can_execute_guarded_function(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("control") as connection:
                connection.execute(
                    "UPDATE projects SET state = 'ACCEPTED', version = 99"
                )
        with self.connect_as("control") as connection:
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result)
                VALUES ('runtime-create', 'runtime-project', 'project.create',
                        'runtime-create', 'hash', 'PROCESSING', '{}'::jsonb)
                """
            )
            connection.execute(
                """
                SELECT hermes_create_project_authority(
                    'runtime-project', 'Runtime Project', 'runtime-create',
                    'control_plane', 'runtime-control', 'user', 'user-runtime',
                    'runtime controlled path'
                )
                """
            )
            sequence = connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('runtime-project-created', 'project.created', '1.0',
                        'control_plane', 'runtime-control', 'runtime-project',
                        'runtime-project', 'runtime-create', 'runtime-create',
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                RETURNING sequence
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                VALUES ('runtime-project-message', 'runtime-project-created',
                        'hermes.runtime.events', 'runtime-project', %s,
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                """,
                (sequence,),
            )
            connection.execute(
                """
                UPDATE command_receipts
                SET status = 'APPLIED', result = '{"result_code": "PROJECT_CREATED"}'::jsonb,
                    completed_at = now()
                WHERE command_id = 'runtime-create'
                """
            )
        self.assertEqual(
            "CREATED",
            self.store.scalar(
                "SELECT state FROM projects WHERE project_id = 'runtime-project'"
            ),
        )

    def test_owner_direct_state_change_without_event_is_rejected_at_commit(self):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result)
                VALUES ('owner-seed', 'project-1', 'project.create', 'owner-seed',
                        'hash', 'PROCESSING', '{}'::jsonb)
                """
            )
            connection.execute(
                """
                SELECT hermes_create_project_authority(
                    'project-1', 'Project', 'owner-seed', 'control_plane',
                    'seed', 'user', 'user-1', 'seed project'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('owner-seed-event', 'project.created', '1.0', 'control_plane',
                        'seed', 'project-1', 'project-1', 'owner-seed', 'seed',
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                """
            )
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                SELECT 'owner-seed-message', 'owner-seed-event',
                       'hermes.runtime.events', 'project-1', sequence,
                       '{"project_version": 0, "new_state": "CREATED"}'::jsonb
                FROM event_log WHERE event_id = 'owner-seed-event'
                """
            )
        connection = psycopg.connect(DATABASE_URL)
        try:
            with self.assertRaisesRegex(
                psycopg.errors.RaiseException,
                "PROJECT_STATE_EVENT_INVARIANT_VIOLATION",
            ):
                connection.execute(
                    "UPDATE projects SET state = 'INTAKE', version = 1 WHERE project_id = 'project-1'"
                )
                connection.commit()
        finally:
            connection.close()

    def test_control_plane_role_cannot_bypass_database_transition_guard(self):
        with self.connect_as("control") as connection:
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result)
                VALUES ('guard-create', 'guard-project', 'project.create',
                        'guard-create', 'hash', 'PROCESSING', '{}'::jsonb)
                """
            )
            connection.execute(
                """
                SELECT hermes_create_project_authority(
                    'guard-project', 'Guard Project', 'guard-create',
                    'control_plane', 'runtime-control', 'user', 'user-runtime',
                    'create guard project'
                )
                """
            )
            sequence = connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('guard-created', 'project.created', '1.0', 'control_plane',
                        'runtime-control', 'guard-project', 'guard-project',
                        'guard-create', 'guard-create',
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                RETURNING sequence
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                VALUES ('guard-created-message', 'guard-created',
                        'hermes.runtime.events', 'guard-project', %s,
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                """,
                (sequence,),
            )

        with self.assertRaisesRegex(
            psycopg.errors.RaiseException, "ILLEGAL_PROJECT_TRANSITION"
        ):
            with self.connect_as("control") as connection:
                connection.execute(
                    """
                    INSERT INTO command_receipts
                      (command_id, project_id, command_type, idempotency_key,
                       request_hash, status, result)
                    VALUES ('guard-illegal', 'guard-project',
                            'project.request_transition', 'guard-illegal',
                            'hash', 'PROCESSING', '{}'::jsonb)
                    """
                )
                connection.execute(
                    """
                    SELECT hermes_transition_project_authority(
                        'guard-project', 0, 'CREATED', 'ACCEPTED', NULL,
                        'guard-illegal', 'control_plane', 'runtime-control',
                        'main_hermes', 'main-runtime', 'skip all states', NULL,
                        NULL, NULL, NULL, NULL
                    )
                    """
                )

        with self.assertRaisesRegex(
            psycopg.errors.RaiseException, "PROJECT_COMMAND_SEMANTICS_MISMATCH"
        ):
            with self.connect_as("control") as connection:
                connection.execute(
                    """
                    INSERT INTO command_receipts
                      (command_id, project_id, command_type, idempotency_key,
                       request_hash, status, result)
                    VALUES ('guard-wrong-command', 'guard-project',
                            'project.cancel', 'guard-wrong-command',
                            'hash', 'PROCESSING', '{}'::jsonb)
                    """
                )
                connection.execute(
                    """
                    SELECT hermes_transition_project_authority(
                        'guard-project', 0, 'CREATED', 'INTAKE', NULL,
                        'guard-wrong-command', 'control_plane', 'runtime-control',
                        'main_hermes', 'main-runtime', 'wrong semantics', NULL,
                        NULL, NULL, NULL, NULL
                    )
                    """
                )

    def test_runtime_roles_cannot_write_guard_facts_or_modify_authority_objects(self):
        for role in ("worker", "control", "reader"):
            with self.subTest(role=role, action="insert_guard_fact"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            """
                            INSERT INTO project_policy_decision_facts
                              (policy_decision_id, project_id, project_version,
                               from_state, to_state, result, authority,
                               policy_bundle_version, input_hash)
                            VALUES ('forged-policy', 'project-1', 0, 'CREATED',
                                    'INTAKE', 'ALLOW', 'policy_engine',
                                    'forged', 'sha256:forged')
                            """
                        )
            with self.subTest(role=role, action="disable_trigger"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            "ALTER TABLE projects DISABLE TRIGGER projects_require_event"
                        )
            with self.subTest(role=role, action="alter_function"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(role) as connection:
                        connection.execute(
                            """
                            ALTER FUNCTION hermes_transition_project_authority(
                                TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
                                TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
                            ) OWNER TO CURRENT_USER
                            """
                        )

    def test_public_cannot_execute_guarded_project_functions(self):
        with self.connect_as("reader") as connection:
            connection.execute("SET ROLE NONE")
            allowed = connection.execute(
                """
                SELECT has_function_privilege(
                    current_user,
                    'public.hermes_transition_project_authority(text,bigint,text,text,text,text,text,text,text,text,text,text,text,text,text,text)',
                    'EXECUTE'
                )
                """
            ).fetchone()[0]
        self.assertFalse(allowed)

    def test_search_path_and_same_name_objects_cannot_hijack_guarded_function(self):
        with self.connect_as("control") as connection:
            connection.execute("CREATE TEMP TABLE projects(project_id text, state text)")
            connection.execute(
                """
                CREATE FUNCTION pg_temp.gen_random_uuid()
                RETURNS uuid
                LANGUAGE sql
                AS 'SELECT ''00000000-0000-0000-0000-000000000000''::uuid'
                """
            )
            connection.execute("SET search_path = pg_temp, public")
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result)
                VALUES ('shadow-create', 'shadow-project', 'project.create',
                        'shadow-create', 'hash', 'PROCESSING', '{}'::jsonb)
                """
            )
            connection.execute(
                """
                SELECT public.hermes_create_project_authority(
                    'shadow-project', 'Shadow Project', 'shadow-create',
                    'control_plane', 'runtime-control', 'user', 'user-runtime',
                    'shadow safe create'
                )
                """
            )
            sequence = connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('shadow-project-created', 'project.created', '1.0',
                        'control_plane', 'runtime-control', 'shadow-project',
                        'shadow-project', 'shadow-create', 'shadow-create',
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                RETURNING sequence
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                VALUES ('shadow-project-message', 'shadow-project-created',
                        'hermes.runtime.events', 'shadow-project', %s,
                        '{"project_version": 0, "new_state": "CREATED"}'::jsonb)
                """,
                (sequence,),
            )
            connection.execute(
                """
                UPDATE command_receipts
                SET status = 'APPLIED', result = '{"result_code": "PROJECT_CREATED"}'::jsonb,
                    completed_at = now()
                WHERE command_id = 'shadow-create'
                """
            )
        self._insert_guard_facts_as_admin(
            "shadow-project", 0, "CREATED", "INTAKE", "shadow"
        )
        with self.connect_as("control") as connection:
            connection.execute("SET search_path = pg_temp, public")
            connection.execute(
                """
                INSERT INTO command_receipts
                  (command_id, project_id, command_type, idempotency_key,
                   request_hash, status, result)
                VALUES ('shadow-transition', 'shadow-project',
                        'project.request_transition', 'shadow-transition',
                        'hash', 'PROCESSING', '{}'::jsonb)
                """
            )
            version = connection.execute(
                """
                SELECT public.hermes_transition_project_authority(
                    'shadow-project', 0, 'CREATED', 'INTAKE', NULL,
                    'shadow-transition', 'control_plane', 'runtime-control',
                    'main_hermes', 'main-runtime', 'shadow safe transition', NULL,
                    'evidence-shadow', 'policy-shadow', 'budget-shadow', NULL
                )
                """
            ).fetchone()[0]
            sequence = connection.execute(
                """
                INSERT INTO event_log
                  (event_id, event_type, schema_version, producer_type, producer_id,
                   project_id, partition_key, command_id, correlation_id, payload)
                VALUES ('shadow-project-transitioned',
                        'project.state_transition.applied', '1.0',
                        'control_plane', 'runtime-control', 'shadow-project',
                        'shadow-project', 'shadow-transition', 'shadow-transition',
                        '{"project_version": 1, "new_state": "INTAKE"}'::jsonb)
                RETURNING sequence
                """
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO outbox_messages
                  (message_id, event_id, topic, partition_key, sequence, payload)
                VALUES ('shadow-transition-message', 'shadow-project-transitioned',
                        'hermes.runtime.events', 'shadow-project', %s,
                        '{"project_version": 1, "new_state": "INTAKE"}'::jsonb)
                """,
                (sequence,),
            )
            connection.execute(
                """
                UPDATE command_receipts
                SET status = 'APPLIED',
                    result = '{"result_code": "PROJECT_TRANSITION_APPLIED"}'::jsonb,
                    completed_at = now()
                WHERE command_id = 'shadow-transition'
                """
            )
        self.assertEqual(1, version)
        self.assertEqual(
            "INTAKE",
            self.store.scalar(
                "SELECT state FROM projects WHERE project_id = 'shadow-project'"
            ),
        )

    def test_security_definer_owner_is_not_runtime_role(self):
        owner = self.store.scalar(
            """
            SELECT pg_get_userbyid(p.proowner)
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname = 'hermes_transition_project_authority'
              AND pg_get_function_arguments(p.oid) LIKE '%p_gate_decision_id text%'
            """
        )
        self.assertEqual("hermes_authority_owner", owner)
        self.assertNotIn(
            owner,
            {
                "hermes_control_plane_runtime",
                "hermes_worker_runtime",
                "hermes_read_only_runtime",
            },
        )


if __name__ == "__main__":
    unittest.main()
