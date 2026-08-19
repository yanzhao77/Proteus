"""Pytest fixtures for a role-owned PostgreSQL test database.

The application reads ``DATABASE_URL`` at import time, so the test DSN is fixed
before importing ``app.main``. A missing test database is created only as the
application role's own database. An existing incorrectly bootstrapped database
is never silently repaired with broad grants or an owner alteration.
"""

import os

import psycopg
from psycopg import sql
import pytest
import sqlalchemy


BOOTSTRAP_ERROR = "GOLDEN_TODO_TEST_DATABASE_BOOTSTRAP_INVALID"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://todo:todo@localhost:5432/todo_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import models  # noqa: E402
from app.main import app, engine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _bootstrap_failure(database_name: str, role: str) -> None:
    pytest.fail(
        f"{BOOTSTRAP_ERROR}: database {database_name!r} for application role {role!r} "
        "does not meet the required owner-plus-public-CREATE boundary",
        pytrace=False,
    )


def _require_test_database_name(url: sqlalchemy.engine.URL) -> None:
    name = str(url.database or "")
    if name in {"postgres", "template0", "template1"} or not any(
        marker in name.lower() for marker in ("test", "ci")
    ):
        _bootstrap_failure(name, str(url.username))


def _admin_url(url: sqlalchemy.engine.URL) -> sqlalchemy.engine.URL:
    return url.set(database="postgres", username="postgres", password="hermes")


def _psycopg_url(url: sqlalchemy.engine.URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _create_database_for_application_role(url: sqlalchemy.engine.URL) -> None:
    """Create a missing database owned by its application role using quoted IDs."""
    admin_url = _admin_url(url)
    connection = psycopg.connect(_psycopg_url(admin_url))
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname, rolsuper FROM pg_roles WHERE rolname = %s",
                (url.username,),
            )
            role = cursor.fetchone()
            if role is None or role[1]:
                _bootstrap_failure(str(url.database), str(url.username))
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(str(url.database)),
                    sql.Identifier(str(url.username)),
                )
            )
    finally:
        connection.close()


def _verify_existing_database_boundary(url: sqlalchemy.engine.URL) -> None:
    connection = psycopg.connect(_psycopg_url(url))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database "
                "WHERE datname = current_database()"
            )
            owner = cursor.fetchone()[0]
            cursor.execute(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
            )
            has_create = bool(cursor.fetchone()[0])
    finally:
        connection.close()
    if owner != url.username or not has_create:
        _bootstrap_failure(str(url.database), str(url.username))


@pytest.fixture(scope="session")
def test_engine():
    url = sqlalchemy.engine.url.make_url(TEST_DATABASE_URL)
    _require_test_database_name(url)
    admin_engine = sqlalchemy.create_engine(
        _admin_url(url).render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sqlalchemy.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
        if not exists:
            _create_database_for_application_role(url)
        _verify_existing_database_boundary(url)
    finally:
        admin_engine.dispose()
    engine.dispose()
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(test_engine):
    models.Base.metadata.drop_all(bind=test_engine)
    models.Base.metadata.create_all(bind=test_engine)
    yield
    models.Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/auth/register",
        json={"username": "tester", "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": "Bearer " + token}
