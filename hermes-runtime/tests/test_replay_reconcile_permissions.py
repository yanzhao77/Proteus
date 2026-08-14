import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.infrastructure.postgres_replay_reconcile import PostgresReplayReconcileStore


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
    "requires real PostgreSQL 14+",
)
class ReplayReconcilePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresReplayReconcileStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)
        cls.password = "hermes-p3-replay-role-test"
        cls.roles = {
            "replay": "hermes_test_replay_" + uuid.uuid4().hex[:8],
            "reconcile": "hermes_test_reconcile_" + uuid.uuid4().hex[:8],
            "apply": "hermes_test_reconcile_apply_" + uuid.uuid4().hex[:8],
            "worker": "hermes_test_replay_worker_" + uuid.uuid4().hex[:8],
            "reader": "hermes_test_replay_reader_" + uuid.uuid4().hex[:8],
        }
        memberships = {
            "replay": "hermes_replay_runtime",
            "reconcile": "hermes_reconcile_runtime",
            "apply": "hermes_reconcile_apply_runtime",
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

    def test_execute_surfaces_are_separated(self):
        with self.connect_as("replay") as connection:
            connection.execute(
                """
                SELECT public.hermes_request_replay_session(
                    'cmd-r','idem-r','replay-r','consumer','hermes.runtime.events',
                    'project-1','generation-production','generation-shadow',1,1,
                    'consumer/1','1.0','READ_MODEL_REBUILD',false,0,
                    'system_operator','operator','reason','authz'
                )
                """
            )
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("replay") as connection:
                connection.execute(
                    """
                    SELECT public.hermes_observe_reconcile_findings(
                        'cmd-o','idem-o','project-1','system_operator',
                        'operator','reason','authz',NULL,NULL
                    )
                    """
                )
        with self.connect_as("reconcile") as connection:
            connection.execute(
                """
                SELECT public.hermes_observe_reconcile_findings(
                    'cmd-o2','idem-o2','project-1','system_operator',
                    'operator','reason','authz',NULL,NULL
                )
                """
            )
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("reconcile") as connection:
                connection.execute(
                    """
                    SELECT public.hermes_apply_reconcile_plan(
                        'cmd-a','idem-a','missing',1,'system_operator',
                        'operator','reason','authz',NULL
                    )
                    """
                )

    def test_runtime_roles_cannot_directly_patch_authority_or_replay_tables(self):
        statements = (
            "UPDATE public.consumer_checkpoints SET last_sequence=999",
            "INSERT INTO public.replay_generations(generation_id,consumer_id,stream_name,partition_key,source_generation_id,status,start_sequence,end_sequence) VALUES ('g','c','s','p','src','VERIFIED',1,1)",
            "INSERT INTO public.reconcile_findings(finding_id,finding_kind,scope_id,scope_hash) VALUES ('f','CHECKPOINT_CORRUPT','s','sha256:x')",
            "UPDATE public.projects SET state='FAILED'",
            "DELETE FROM public.event_log",
        )
        for role in ("replay", "reconcile", "apply", "worker", "reader"):
            for statement in statements:
                with self.subTest(role=role, statement=statement):
                    with self.assertRaises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)):
                        with self.connect_as(role) as connection:
                            connection.execute(statement)

    def test_owner_is_nologin_public_has_no_execute_and_search_path_hardened(self):
        with psycopg.connect(DATABASE_URL) as connection:
            owner = connection.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='hermes_replay_reconcile_owner'"
            ).fetchone()[0]
            self.assertFalse(owner)
            public_execute = connection.execute(
                """
                SELECT count(*) FROM information_schema.routine_privileges
                WHERE routine_schema='public'
                  AND grantee='PUBLIC'
                  AND routine_name LIKE 'hermes_%replay%'
                  AND privilege_type='EXECUTE'
                """
            ).fetchone()[0]
            self.assertEqual(0, public_execute)
            insecure = connection.execute(
                """
                SELECT count(*) FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname='public'
                  AND p.proname IN (
                    'hermes_request_replay_session',
                    'hermes_execute_replay_session',
                    'hermes_activate_replay_generation',
                    'hermes_observe_reconcile_findings',
                    'hermes_create_reconcile_plan',
                    'hermes_apply_reconcile_plan'
                  )
                  AND (NOT p.prosecdef OR array_to_string(p.proconfig, ',') NOT LIKE '%search_path=pg_catalog%')
                """
            ).fetchone()[0]
            self.assertEqual(0, insecure)


if __name__ == "__main__":
    unittest.main()
