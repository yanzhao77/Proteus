"""Contract and PostgreSQL integration coverage for P6 Todo disposable bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from hermes_runtime.trial.test_database_bootstrap import (
    BOOTSTRAP_ERROR,
    MAX_POSTGRES_IDENTIFIER_LENGTH,
    TEST_DATABASE_PREFIX,
    DisposableTodoDatabase,
    TodoDatabaseBootstrapError,
    create_disposable_todo_database,
    generate_database_name,
    replace_database_component,
    validate_database_name,
    validate_existing_todo_database,
)


ADMIN_DSN = os.environ.get("HERMES_TEST_DATABASE_URL", "")
TODO_DSN = os.environ.get(
    "HERMES_P6_TODO_DATABASE_URL",
    "postgresql+psycopg://todo:todo@127.0.0.1:55432/todo_test",
)


def _with_netloc(dsn: str, *, username: str | None = None, port: int | None = None) -> str:
    parsed = urlsplit(dsn)
    host = parsed.hostname or ""
    user = username if username is not None else (parsed.username or "")
    password = parsed.password or ""
    selected_port = port if port is not None else parsed.port
    auth = user
    if password:
        auth += ":" + password
    netloc = auth + "@" + host
    if selected_port is not None:
        netloc += ":" + str(selected_port)
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _admin_connect():
    parsed = urlsplit(ADMIN_DSN)
    return psycopg.connect(urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment)))


class P6TodoDatabaseBootstrapContractTests(unittest.TestCase):
    def test_generated_name_is_test_only_and_unique(self):
        first = generate_database_name("alpha123")
        second = generate_database_name("beta456")
        self.assertEqual(TEST_DATABASE_PREFIX + "alpha123", first)
        self.assertTrue(first.startswith(TEST_DATABASE_PREFIX))
        self.assertNotEqual(first, second)

    def test_url_replacement_preserves_credentials_host_port_and_query(self):
        source = "postgresql+psycopg://todo:p%40ss@db.test:55432/todo_test?sslmode=disable"
        replaced = replace_database_component(source, TEST_DATABASE_PREFIX + "abc123")
        before = urlsplit(source)
        after = urlsplit(replaced)
        self.assertEqual(before.scheme, after.scheme)
        self.assertEqual(before.username, after.username)
        self.assertEqual(before.password, after.password)
        self.assertEqual(before.hostname, after.hostname)
        self.assertEqual(before.port, after.port)
        self.assertEqual(before.query, after.query)
        self.assertEqual("/" + TEST_DATABASE_PREFIX + "abc123", after.path)

    def test_every_unsafe_target_name_is_rejected_without_secret_disclosure(self):
        source = "postgresql+psycopg://todo:only-for-test@db.test:55432/todo_test"
        invalid_names = (
            TEST_DATABASE_PREFIX,
            TEST_DATABASE_PREFIX + "slash/path",
            TEST_DATABASE_PREFIX + "back\\\\path",
            TEST_DATABASE_PREFIX + "quote'",
            TEST_DATABASE_PREFIX + 'quote"',
            TEST_DATABASE_PREFIX + "space value",
            TEST_DATABASE_PREFIX + "line\\nfeed",
            TEST_DATABASE_PREFIX + "upperCASE",
            TEST_DATABASE_PREFIX + "unicode_é",
            TEST_DATABASE_PREFIX + ("a" * MAX_POSTGRES_IDENTIFIER_LENGTH),
            "postgres",
            "template0",
            "template1",
        )
        for invalid_name in invalid_names:
            with self.subTest(invalid_name=repr(invalid_name)):
                with self.assertRaises(TodoDatabaseBootstrapError) as raised:
                    validate_database_name(invalid_name)
                message = str(raised.exception)
                self.assertIn(BOOTSTRAP_ERROR, message)
                self.assertNotIn("only-for-test", message)
                self.assertNotIn(source, message)
                with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
                    replace_database_component(source, invalid_name)

    def test_manual_or_invalid_cleanup_instance_does_not_connect(self):
        valid_name = generate_database_name("cleanupok")
        forged = DisposableTodoDatabase(
            admin_dsn="postgresql://admin:secret@db.test:55432/postgres",
            todo_dsn="postgresql://todo:only-for-test@db.test:55432/todo_test",
            name=valid_name,
            role="todo",
            created_at="now",
            evidence={
                "database_name": valid_name,
                "database_oid": 12345,
                "database_owner": "todo",
            },
        )
        invalid = DisposableTodoDatabase(
            admin_dsn="postgresql://admin:secret@db.test:55432/postgres",
            todo_dsn="postgresql://todo:only-for-test@db.test:55432/todo_test",
            name=TEST_DATABASE_PREFIX + "bad/path",
            role="todo",
            created_at="now",
            evidence={"database_name": TEST_DATABASE_PREFIX + "bad/path"},
        )
        with mock.patch("hermes_runtime.trial.test_database_bootstrap._admin_connect") as admin_connect:
            for target in (forged, invalid):
                with self.subTest(target=target.name):
                    with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR) as raised:
                        target.cleanup()
                    self.assertNotIn("secret", str(raised.exception))
                    self.assertNotIn("only-for-test", str(raised.exception))
            admin_connect.assert_not_called()

    @unittest.skipUnless(ADMIN_DSN, "requires HERMES_TEST_DATABASE_URL")
    def test_mismatched_cluster_rejected_before_database_creation(self):
        mismatched = _with_netloc(TODO_DSN, port=(urlsplit(TODO_DSN).port or 5432) + 1)
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
            create_disposable_todo_database(ADMIN_DSN, mismatched)

    @unittest.skipUnless(ADMIN_DSN, "requires HERMES_TEST_DATABASE_URL")
    def test_missing_or_superuser_role_fails_closed_without_creating_database(self):
        missing = _with_netloc(TODO_DSN, username="p6_missing_role")
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
            create_disposable_todo_database(ADMIN_DSN, missing)

        superuser = _with_netloc(TODO_DSN, username="postgres")
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
            create_disposable_todo_database(ADMIN_DSN, superuser)


@unittest.skipUnless(ADMIN_DSN, "requires real PostgreSQL and HERMES_TEST_DATABASE_URL")
class P6TodoDatabaseBootstrapPostgresTests(unittest.TestCase):
    def _database_exists(self, name: str) -> bool:
        connection = _admin_connect()
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def test_created_database_is_role_owned_has_create_and_cleanup_is_idempotent(self):
        disposable = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        self.addCleanup(disposable.cleanup)
        self.assertTrue(disposable.name.startswith(TEST_DATABASE_PREFIX))
        self.assertEqual("todo", disposable.evidence["database_owner"])
        self.assertFalse(disposable.evidence["todo_role_superuser"])
        self.assertTrue(disposable.evidence["todo_schema_usage"])
        self.assertTrue(disposable.evidence["todo_schema_create"])
        self.assertEqual("NOT_AVAILABLE", disposable.evidence["postgres_image_digest"])

        todo_url = urlsplit(disposable.runtime_todo_dsn)
        self.assertEqual(urlsplit(TODO_DSN).username, todo_url.username)
        self.assertEqual(urlsplit(TODO_DSN).hostname, todo_url.hostname)
        self.assertEqual(urlsplit(TODO_DSN).port, todo_url.port)
        self.assertEqual(urlsplit(TODO_DSN).query, todo_url.query)

        parsed = urlsplit(disposable.runtime_todo_dsn)
        native = urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        connection = psycopg.connect(native)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE TABLE {} (id integer)").format(sql.Identifier("bootstrap_probe")))
            connection.commit()
        finally:
            connection.close()

        disposable.cleanup()
        disposable.cleanup()
        self.assertTrue(disposable.cleanup_attempted)
        self.assertTrue(disposable.cleanup_completed)
        self.assertFalse(self._database_exists(disposable.name))

    def test_golden_todo_direct_suite_passes_on_new_role_owned_database(self):
        disposable = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        self.addCleanup(disposable.cleanup)
        repository_root = Path(__file__).resolve().parents[2]
        golden_root = repository_root / "examples" / "golden-todo"
        environment = dict(os.environ)
        environment.update({
            "TEST_DATABASE_URL": disposable.runtime_todo_dsn,
            "DATABASE_URL": disposable.runtime_todo_dsn,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "PIP_NO_INDEX": "1",
        })
        completed = subprocess.run(
            [str(golden_root / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=str(golden_root),
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("9 passed", completed.stdout)
        self.assertNotIn("permission denied for schema public", completed.stdout)

    def test_factory_issued_cleanup_is_idempotent_and_public_evidence_cannot_redirect_it(self):
        first = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        second = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        self.addCleanup(second.cleanup)
        self.addCleanup(first.cleanup)
        first_name = first.name
        self.assertNotEqual(first_name, second.name)
        self.assertIsInstance(first.evidence["database_oid"], int)

        first.evidence["database_name"] = second.name
        first.evidence["database_oid"] = second.evidence["database_oid"]
        first.evidence["database_owner"] = "postgres"
        first.cleanup()
        self.assertFalse(self._database_exists(first_name))
        self.assertTrue(self._database_exists(second.name))
        first.cleanup()
        self.assertTrue(first.cleanup_completed)
        second.cleanup()
        self.assertFalse(self._database_exists(second.name))

    def test_public_name_mutation_is_rejected_before_administrator_connection(self):
        first = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        second = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        first_name = first.name
        self.addCleanup(self._drop_database, first_name)
        self.addCleanup(self._drop_database, second.name)
        first.name = second.name
        with mock.patch("hermes_runtime.trial.test_database_bootstrap._admin_connect") as admin_connect:
            with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
                first.cleanup()
            admin_connect.assert_not_called()
        self.assertTrue(self._database_exists(first_name))
        self.assertTrue(self._database_exists(second.name))

    def test_same_name_replacement_oid_mismatch_fails_closed_and_preserves_replacement(self):
        disposable = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        name = disposable.name
        original_oid = disposable.evidence["database_oid"]
        self.addCleanup(self._drop_database, name)
        self._drop_database(name)
        self._create_database(name, owner="todo")
        replacement_oid, replacement_owner = self._database_oid_owner(name)
        self.assertNotEqual(original_oid, replacement_oid)
        self.assertEqual("todo", replacement_owner)
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
            disposable.cleanup()
        self.assertTrue(self._database_exists(name))

    def test_owner_mismatch_fails_closed_and_preserves_database(self):
        disposable = create_disposable_todo_database(ADMIN_DSN, TODO_DSN)
        name = disposable.name
        self.addCleanup(self._drop_database, name)
        connection = _admin_connect()
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(name), sql.Identifier("postgres")
                ))
        finally:
            connection.close()
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR):
            disposable.cleanup()
        oid, owner = self._database_oid_owner(name)
        self.assertEqual(disposable.evidence["database_oid"], oid)
        self.assertEqual("postgres", owner)
        self.assertTrue(self._database_exists(name))

    def test_wrong_owner_with_explicit_create_is_rejected_by_helper_and_golden_fixture(self):
        name = generate_database_name("wrongownercreate")
        membership_before = self._todo_membership_snapshot()
        connection = _admin_connect()
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier("postgres")
                ))
        finally:
            connection.close()
        self.addCleanup(self._revoke_and_drop_database, name)

        target = replace_database_component(TODO_DSN, name)
        admin_target = self._native_psycopg_dsn(target, username="postgres", password="hermes")
        connection = psycopg.connect(admin_target)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier("todo")))
        finally:
            connection.close()

        owner_before, create_before, acl_before = self._database_authority_snapshot(name)
        self.assertEqual("postgres", owner_before)
        self.assertTrue(create_before)
        with self.assertRaisesRegex(TodoDatabaseBootstrapError, BOOTSTRAP_ERROR) as raised:
            validate_existing_todo_database(target)
        self.assertNotIn("postgresql", str(raised.exception))
        self.assertNotIn(TODO_DSN, str(raised.exception))

        repository_root = Path(__file__).resolve().parents[2]
        golden_root = repository_root / "examples" / "golden-todo"
        environment = dict(os.environ)
        environment.update({
            "TEST_DATABASE_URL": target,
            "DATABASE_URL": target,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "PIP_NO_INDEX": "1",
        })
        completed = subprocess.run(
            [str(golden_root / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=str(golden_root),
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn(BOOTSTRAP_ERROR, completed.stdout + completed.stderr)

        owner_after, create_after, acl_after = self._database_authority_snapshot(name)
        self.assertEqual(owner_before, owner_after)
        self.assertEqual(create_before, create_after)
        self.assertEqual(acl_before, acl_after)
        self.assertEqual(membership_before, self._todo_membership_snapshot())

    def _create_database(self, name: str, *, owner: str) -> None:
        connection = _admin_connect()
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier(owner)
                ))
        finally:
            connection.close()

    def _database_oid_owner(self, name: str):
        connection = _admin_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                    (name,),
                )
                oid, owner = cursor.fetchone()
                return int(oid), str(owner)
        finally:
            connection.close()

    def _native_psycopg_dsn(self, dsn: str, *, username: str, password: str) -> str:
        parsed = urlsplit(dsn)
        netloc = username + ":" + password + "@" + (parsed.hostname or "")
        if parsed.port is not None:
            netloc += ":" + str(parsed.port)
        return urlunsplit(("postgresql", netloc, parsed.path, parsed.query, parsed.fragment))

    def _database_authority_snapshot(self, name: str):
        target = replace_database_component(TODO_DSN, name)
        connection = psycopg.connect(self._native_psycopg_dsn(target, username="postgres", password="hermes"))
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")
                owner = cursor.fetchone()[0]
                cursor.execute("SELECT has_schema_privilege('todo', 'public', 'CREATE')")
                has_create = bool(cursor.fetchone()[0])
                cursor.execute("SELECT COALESCE(nspacl::text, '') FROM pg_namespace WHERE nspname = 'public'")
                acl = cursor.fetchone()[0]
                return owner, has_create, acl
        finally:
            connection.close()

    def _todo_membership_snapshot(self):
        connection = _admin_connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_userbyid(roleid), pg_get_userbyid(member) "
                    "FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'todo') "
                    "ORDER BY 1, 2"
                )
                return tuple(cursor.fetchall())
        finally:
            connection.close()

    def _revoke_and_drop_database(self, name: str) -> None:
        target = replace_database_component(TODO_DSN, name)
        connection = psycopg.connect(self._native_psycopg_dsn(target, username="postgres", password="hermes"))
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier("todo")))
        finally:
            connection.close()
        self._drop_database(name)

    def _drop_database(self, name: str) -> None:
        connection = _admin_connect()
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
