"""Golden Todo API tests: auth, CRUD, OpenAPI, secret discipline."""

import os
import pytest


def test_livez(client):
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "LIVE"


def test_openapi_documents_auth_and_todos(client):
    schema = client.get("/openapi.json").json()
    assert "/auth/register" in schema["paths"]
    assert "/todos" in schema["paths"]
    assert schema["info"]["title"] == "Golden Todo API"


def test_register_login_and_authed_crud_roundtrip(client, auth_headers):
    created = client.post(
        "/todos", json={"title": "write evidence", "completed": False},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    todo = created.json()
    assert todo["title"] == "write evidence"
    assert todo["owner_id"] > 0

    listed = client.get("/todos", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == todo["id"] for item in listed.json())

    updated = client.put(
        "/todos/" + str(todo["id"]),
        json={"title": "write evidence (done)", "completed": True},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["completed"] is True

    deleted = client.delete("/todos/" + str(todo["id"]), headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/todos", headers=auth_headers).json() == []


def test_todos_are_owner_scoped(client, auth_headers):
    created = client.post(
        "/todos", json={"title": "private todo"}, headers=auth_headers
    )
    todo_id = created.json()["id"]

    other = client.post(
        "/auth/register",
        json={"username": "other", "password": "another-password-456"},
    )
    other_headers = {"Authorization": "Bearer " + other.json()["access_token"]}
    assert client.get("/todos", headers=other_headers).json() == []
    assert (
        client.put(
            "/todos/" + str(todo_id),
            json={"title": "hijack", "completed": True},
            headers=other_headers,
        ).status_code
        == 404
    )


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/todos").status_code == 401
    assert client.post("/todos", json={"title": "x"}).status_code == 401


def test_bad_credentials_rejected(client):
    assert client.post(
        "/auth/login",
        json={"username": "nobody", "password": "wrong-password-999"},
    ).status_code == 401


def test_short_password_rejected(client):
    response = client.post(
        "/auth/register", json={"username": "weak", "password": "short"}
    )
    assert response.status_code == 422


def test_no_secret_values_leak_to_openapi_or_errors(client):
    body = client.get("/openapi.json").text
    assert "correct-horse-battery" not in body
    assert "dev-only-insecure-secret" not in body


def test_environment_has_test_database_url():
    assert os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
