"""Pytest fixtures: isolated PostgreSQL test database per test run.

The app reads DATABASE_URL at import time, so we set the test DSN before
importing app.main.
"""

import os

import pytest
import sqlalchemy

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://todo:todo@localhost:5432/todo_test"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app import models  # noqa: E402
from app.main import app, engine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def test_engine():
    url = sqlalchemy.engine.url.make_url(TEST_DATABASE_URL)
    admin_url = url.set(database="postgres", username="postgres", password="hermes")
    admin_engine = sqlalchemy.create_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    db_name = url.database
    with admin_engine.connect() as conn:
        exists = conn.execute(
            sqlalchemy.text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            conn.execute(sqlalchemy.text('CREATE DATABASE "{}"'.format(db_name)))
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
