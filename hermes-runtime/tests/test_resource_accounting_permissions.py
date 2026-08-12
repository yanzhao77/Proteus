import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.accounting import ResourceAccounting
from hermes_runtime.application.commands import (
    CreateProject,
    CreateResourceAccount,
    ReserveResources,
)
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_accounting import (
    PostgresResourceAccountingStore,
)


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
    DATABASE_URL and psycopg, "requires real PostgreSQL and role creation privileges"
)
class ResourceAccountingPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = PostgresResourceAccountingStore(DATABASE_URL)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            cls.admin.apply_migration(migration)
        cls.password = "hermes-accounting-role-test"
        cls.roles = {
            key: "hermes_test_{}_{}".format(key, uuid.uuid4().hex[:8])
            for key in ("accounting", "worker", "control", "reader", "public")
        }
        memberships = {
            "accounting": "hermes_accounting_runtime",
            "worker": "hermes_worker_runtime",
            "control": "hermes_control_plane_runtime",
            "reader": "hermes_read_only_runtime",
        }
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for key, role in cls.roles.items():
                connection.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role), psycopg.sql.Literal(cls.password)
                    )
                )
                if key in memberships:
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
        self.admin.reset_for_test()
        actor = Actor(ActorType.CONTROL_PLANE, "control")
        ControlPlane(self.admin).create_project(CreateProject(
            CommandEnvelope("cmd-project", "project.create", "key-project", 0,
                            actor, "permission test", "project-1"),
            "Permissions", Actor(ActorType.USER, "user-1"),
        ))

    def connect_as(self, key):
        return psycopg.connect(
            role_dsn(DATABASE_URL, self.roles[key], self.password)
        )

    def accounting(self):
        return ResourceAccounting(PostgresResourceAccountingStore(
            role_dsn(DATABASE_URL, self.roles["accounting"], self.password)
        ))

    @staticmethod
    def envelope(command_type, suffix, version):
        return CommandEnvelope(
            "cmd-" + suffix, command_type, "key-" + suffix, version,
            Actor(ActorType.CONTROL_PLANE, "accounting"),
            "permission test", "project-1",
        )

    def test_accounting_role_executes_controlled_commands_but_cannot_update_balance(self):
        accounting = self.accounting()
        accounting.create_account(CreateResourceAccount(
            self.envelope("resource_account.create", "account", 0),
            "account-1", "project", "project-1", {"llm_tokens": 100},
        ))
        accounting.reserve(ReserveResources(
            self.envelope("resource.reserve", "reserve", 0),
            "account-1", "reservation-1", "action", "action-1",
            {"llm_tokens": 20},
        ))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("accounting") as connection:
                connection.execute(
                    "UPDATE resource_balances SET reserved_amount=99"
                )
        self.assertEqual(20, self.admin.scalar(
            "SELECT reserved_amount FROM resource_balances WHERE account_id='account-1'"
        ))

    def test_worker_control_reader_and_public_cannot_write_accounting_authority(self):
        accounting = self.accounting()
        accounting.create_account(CreateResourceAccount(
            self.envelope("resource_account.create", "account", 0),
            "account-1", "project", "project-1", {"llm_tokens": 100},
        ))
        for key in ("worker", "control", "reader", "public"):
            with self.subTest(role=key):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(
                            """INSERT INTO resource_reservations(
                               reservation_id,account_id,project_id,owner_type,
                               owner_id,status,account_version,command_id)
                               VALUES ('forged','account-1','project-1','action',
                               'forged','ACTIVE',1,'cmd-project')"""
                        )
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.connect_as(key) as connection:
                        connection.execute(
                            """INSERT INTO project_budget_facts(
                               budget_fact_id,project_id,project_version,from_state,
                               to_state,status,authority,budget_scope_id,version)
                               VALUES ('forged','project-1',0,'CREATED','INTAKE',
                               'OK','budget_engine','forged',0)"""
                        )

    def test_public_cannot_execute_sensitive_accounting_functions(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.connect_as("public") as connection:
                connection.execute(
                    """SELECT public.hermes_reserve_resources_authority(
                       'missing','project-1',0,'forged','action','forged',NULL,
                       NULL,'{}'::jsonb,'cmd-project','control_plane')"""
                )

    def test_security_definer_search_path_cannot_be_shadowed(self):
        accounting = self.accounting()
        with self.connect_as("accounting") as connection:
            connection.execute(
                """CREATE TEMP TABLE resource_accounts(
                   account_id text, project_id text, version bigint,
                   threshold_status text)"""
            )
        accounting.create_account(CreateResourceAccount(
            self.envelope("resource_account.create", "account", 0),
            "account-1", "project", "project-1", {"llm_tokens": 100},
        ))
        self.assertEqual(1, self.admin.scalar(
            "SELECT count(*) FROM public.resource_accounts WHERE account_id='account-1'"
        ))


if __name__ == "__main__":
    unittest.main()
