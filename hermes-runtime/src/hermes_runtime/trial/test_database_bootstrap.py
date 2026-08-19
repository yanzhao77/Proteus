"""Disposable PostgreSQL bootstrap for the P6 Golden Todo test environment.

This module is test-only infrastructure. It creates exactly one uniquely named
Todo database owned by the Todo application role, verifies the PostgreSQL 15/16
``pg_database_owner`` authority boundary, and drops only the exact database
issued by this module's private factory capability. It does not alter shared
schemas, roles, grants, migrations, or production topology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql


TEST_DATABASE_PREFIX = "todo_p6_ci_"
BOOTSTRAP_ERROR = "GOLDEN_TODO_TEST_DATABASE_BOOTSTRAP_INVALID"
MAX_POSTGRES_IDENTIFIER_LENGTH = 63
_RESERVED_DATABASE_NAMES = {"postgres", "template0", "template1"}
_ALLOWED_SUFFIX_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
_FACTORY_CAPABILITY = object()


class TodoDatabaseBootstrapError(RuntimeError):
    """Fail-closed bootstrap error with a redacted, stable public code."""

    def __init__(self, detail: str):
        super().__init__(f"{BOOTSTRAP_ERROR}: {detail}")


@dataclass(frozen=True)
class _CleanupAuthorization:
    """Private, immutable creation record; public evidence never authorizes DROP."""

    database_name: str
    database_oid: int
    database_owner: str
    capability: object


def _parse_dsn(dsn: str, label: str) -> Any:
    try:
        parsed = urlsplit(dsn)
    except ValueError as exc:
        raise TodoDatabaseBootstrapError(f"invalid {label} URL") from exc
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise TodoDatabaseBootstrapError(f"{label} must use a PostgreSQL URL")
    if not parsed.hostname or parsed.port is None or not parsed.username:
        raise TodoDatabaseBootstrapError(
            f"{label} must include host, port, and application role"
        )
    database = parsed.path.lstrip("/")
    if not database or "/" in database:
        raise TodoDatabaseBootstrapError(f"{label} must contain exactly one database name")
    return parsed


def _native_postgres_scheme(parsed: Any) -> str:
    return "postgresql" if parsed.scheme == "postgresql+psycopg" else parsed.scheme


def _native_dsn(parsed: Any, database: str) -> str:
    return urlunsplit(
        (_native_postgres_scheme(parsed), parsed.netloc, "/" + database, parsed.query, parsed.fragment)
    )


def _same_cluster(admin: Any, todo: Any) -> bool:
    return (
        _native_postgres_scheme(admin) == _native_postgres_scheme(todo)
        and admin.hostname == todo.hostname
        and admin.port == todo.port
    )


def _redacted_identity(parsed: Any) -> Mapping[str, str | int]:
    return {
        "driver": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "role": parsed.username,
        "source_database": parsed.path.lstrip("/"),
    }


def validate_database_name(database_name: str) -> str:
    """Return a safe disposable target name before any database operation."""
    if not isinstance(database_name, str):
        raise TodoDatabaseBootstrapError("database target name is invalid")
    if (
        database_name in _RESERVED_DATABASE_NAMES
        or not database_name.startswith(TEST_DATABASE_PREFIX)
        or len(database_name) > MAX_POSTGRES_IDENTIFIER_LENGTH
    ):
        raise TodoDatabaseBootstrapError("database target name is invalid")
    suffix = database_name[len(TEST_DATABASE_PREFIX):]
    if (
        not suffix
        or not database_name.isascii()
        or any(character not in _ALLOWED_SUFFIX_CHARACTERS for character in suffix)
    ):
        raise TodoDatabaseBootstrapError("database target name is invalid")
    return database_name


def generate_database_name(random_suffix: str | None = None) -> str:
    """Return one validated fixed-prefix, test-only PostgreSQL identifier."""
    suffix = random_suffix if random_suffix is not None else secrets.token_hex(8)
    return validate_database_name(TEST_DATABASE_PREFIX + suffix)


def replace_database_component(todo_dsn: str, database_name: str) -> str:
    """Preserve all URL components except one validated database path."""
    parsed = _parse_dsn(todo_dsn, "Todo")
    safe_name = validate_database_name(database_name)
    return urlunsplit((parsed.scheme, parsed.netloc, "/" + safe_name, parsed.query, parsed.fragment))


@dataclass
class DisposableTodoDatabase:
    """The sole database created by one P6 standalone test lifecycle.

    ``evidence`` is intentionally mutable audit output. Cleanup authorization is
    held separately in a factory-issued private record and cannot be recreated
    through the normal public constructor.
    """

    admin_dsn: str
    todo_dsn: str
    name: str
    role: str
    created_at: str
    evidence: dict[str, Any]
    cleanup_attempted: bool = False
    cleanup_completed: bool = False
    _authorization: _CleanupAuthorization | None = field(default=None, repr=False, compare=False)

    @property
    def runtime_todo_dsn(self) -> str:
        return replace_database_component(self.todo_dsn, self.name)

    def _validated_cleanup_record(self) -> tuple[str, _CleanupAuthorization]:
        """Validate identity fully before opening an administrator connection."""
        safe_name = validate_database_name(self.name)
        authorization = self._authorization
        if (
            not isinstance(authorization, _CleanupAuthorization)
            or authorization.capability is not _FACTORY_CAPABILITY
            or authorization.database_name != safe_name
            or authorization.database_owner != self.role
            or not isinstance(authorization.database_oid, int)
            or authorization.database_oid <= 0
        ):
            raise TodoDatabaseBootstrapError("cleanup target is not a factory-issued bootstrap instance")
        return safe_name, authorization

    def cleanup(self) -> None:
        """Drop only the factory-issued database whose name, OID and owner match.

        All destructive authorization derives from the private immutable factory
        record, not from public evidence. If the original database is absent,
        repeated cleanup is a successful idempotent completion. If a same-name
        replacement or owner change is observed, cleanup fails before session
        termination or ``DROP DATABASE``.
        """
        safe_name, authorization = self._validated_cleanup_record()
        self.cleanup_attempted = True
        admin = _admin_connect(self.admin_dsn)
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                    (safe_name,),
                )
                current = cursor.fetchone()
                if current is None:
                    self.cleanup_completed = True
                    self.evidence["cleanup_attempted"] = True
                    self.evidence["cleanup_completed"] = True
                    return
                current_oid, current_owner = int(current[0]), str(current[1])
                if (
                    current_oid != authorization.database_oid
                    or current_owner != authorization.database_owner
                ):
                    raise TodoDatabaseBootstrapError(
                        "cleanup target no longer matches the factory creation record"
                    )
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (safe_name,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(safe_name)))
            self.cleanup_completed = True
            self.evidence["cleanup_attempted"] = True
            self.evidence["cleanup_completed"] = True
        finally:
            admin.close()


def _admin_connect(admin_dsn: str):
    parsed = _parse_dsn(admin_dsn, "administrator")
    maintenance_dsn = _native_dsn(parsed, "postgres")
    connection = psycopg.connect(maintenance_dsn)
    connection.autocommit = True
    return connection


def _issue_disposable_database(
    *,
    admin_dsn: str,
    todo_dsn: str,
    name: str,
    role: str,
    database_oid: int,
    evidence: dict[str, Any],
) -> DisposableTodoDatabase:
    """Return the only public object form allowed to authorize cleanup."""
    authorization = _CleanupAuthorization(
        database_name=name,
        database_oid=database_oid,
        database_owner=role,
        capability=_FACTORY_CAPABILITY,
    )
    return DisposableTodoDatabase(
        admin_dsn=admin_dsn,
        todo_dsn=todo_dsn,
        name=name,
        role=role,
        created_at=str(evidence["created_at"]),
        evidence=evidence,
        _authorization=authorization,
    )


def _note_cleanup_failure(original: Exception, cleanup_error: Exception) -> None:
    """Preserve the creation error while recording only the stable cleanup code."""
    try:
        original.add_note(f"bootstrap cleanup also failed: {BOOTSTRAP_ERROR}")
    except AttributeError:
        pass


def create_disposable_todo_database(admin_dsn: str, todo_dsn: str) -> DisposableTodoDatabase:
    """Create and verify one application-role-owned disposable Todo database."""
    admin_parsed = _parse_dsn(admin_dsn, "administrator")
    todo_parsed = _parse_dsn(todo_dsn, "Todo")
    if not _same_cluster(admin_parsed, todo_parsed):
        raise TodoDatabaseBootstrapError(
            "administrator and Todo URLs must target the same PostgreSQL host and port"
        )
    source_database = todo_parsed.path.lstrip("/")
    if (
        source_database in _RESERVED_DATABASE_NAMES
        or source_database.startswith(TEST_DATABASE_PREFIX)
        or not any(marker in source_database.lower() for marker in ("test", "ci"))
    ):
        raise TodoDatabaseBootstrapError(
            "Todo source database is not an approved non-production template name"
        )

    name = validate_database_name(generate_database_name())
    role = str(todo_parsed.username)
    admin = _admin_connect(admin_dsn)
    issued: DisposableTodoDatabase | None = None
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT rolname, rolsuper FROM pg_roles WHERE rolname = %s", (role,))
            role_row = cursor.fetchone()
            if role_row is None:
                raise TodoDatabaseBootstrapError(f"Todo role {role!r} does not exist")
            if role_row[1]:
                raise TodoDatabaseBootstrapError(f"Todo role {role!r} must not be superuser")
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier(role)
                )
            )
            cursor.execute(
                "SELECT oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (name,),
            )
            created_record = cursor.fetchone()
        if created_record is None:
            raise TodoDatabaseBootstrapError("created database creation record is unavailable")
        database_oid, database_owner = int(created_record[0]), str(created_record[1])
        if database_owner != role:
            raise TodoDatabaseBootstrapError("created database owner does not match Todo application role")

        evidence = {
            "admin": _redacted_identity(admin_parsed),
            "todo": _redacted_identity(todo_parsed),
            "database_name": name,
            "database_oid": database_oid,
            "database_owner": database_owner,
            "todo_role": role,
            "todo_role_superuser": False,
            "postgres_image_digest": "NOT_AVAILABLE",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cleanup_attempted": False,
            "cleanup_completed": False,
        }
        issued = _issue_disposable_database(
            admin_dsn=admin_dsn,
            todo_dsn=todo_dsn,
            name=name,
            role=role,
            database_oid=database_oid,
            evidence=evidence,
        )

        runtime_dsn = _native_dsn(todo_parsed, name)
        todo_connection = psycopg.connect(runtime_dsn)
        try:
            with todo_connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                database, current_role = cursor.fetchone()
                cursor.execute("SHOW server_version")
                postgres_server_version = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
                )
                runtime_oid, runtime_owner = cursor.fetchone()
                cursor.execute(
                    "SELECT pg_get_userbyid(nspowner), "
                    "has_schema_privilege(current_user, 'public', 'USAGE'), "
                    "has_schema_privilege(current_user, 'public', 'CREATE') "
                    "FROM pg_namespace WHERE nspname = 'public'"
                )
                schema_owner, schema_usage, schema_create = cursor.fetchone()
        finally:
            todo_connection.close()

        if (
            database != name
            or current_role != role
            or int(runtime_oid) != database_oid
            or str(runtime_owner) != role
            or not schema_create
        ):
            raise TodoDatabaseBootstrapError(
                "created database did not establish required Todo owner/schema CREATE boundary"
            )
        evidence.update(
            {
                "schema_owner": schema_owner,
                "todo_schema_usage": bool(schema_usage),
                "todo_schema_create": bool(schema_create),
                "postgres_server_version": postgres_server_version,
            }
        )
        return issued
    except Exception as original_error:
        if issued is not None:
            try:
                issued.cleanup()
            except Exception as cleanup_error:
                _note_cleanup_failure(original_error, cleanup_error)
        raise
    finally:
        admin.close()


def validate_existing_todo_database(todo_dsn: str) -> None:
    """Require exact Todo ownership and public-schema CREATE for one safe target."""
    parsed = _parse_dsn(todo_dsn, "Todo")
    database_name = validate_database_name(parsed.path.lstrip("/"))
    try:
        connection = psycopg.connect(_native_dsn(parsed, database_name))
    except Exception as exc:
        raise TodoDatabaseBootstrapError("Todo test database is unavailable") from exc
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
            )
            owner = cursor.fetchone()[0]
            cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            has_create = bool(cursor.fetchone()[0])
    finally:
        connection.close()
    if owner != parsed.username or not has_create:
        raise TodoDatabaseBootstrapError(
            "existing database does not meet the required Todo owner-plus-public-CREATE boundary"
        )
