# Golden Todo — Production-Ready Todo Management API

A minimal, production-shaped Todo Management API used as the **P6 Golden
Project** for the Proteus Autonomous Software Factory trial.

It proves the factory loop: a real software request → autonomous run →
planning → execution → verification → delivery. The API itself is intentionally
small; its purpose is to be verifiable (pytest), runnable (Docker Compose),
authenticated (JWT), documented (OpenAPI + README) and CI-checked.

## Stack

- Python 3.11+ / FastAPI / Pydantic v2
- PostgreSQL 16 (SQLAlchemy 2.x)
- JWT authentication (PyJWT) with bcrypt password hashing
- pytest (unit + API tests) with a dedicated test database
- OpenAPI at `/docs`
- Docker + Docker Compose (app + postgres)
- GitHub Actions CI (pytest + compose config)

## Quick start

```bash
# 1) boot the full system (app + postgres)
docker compose up --build

# 2) health
curl http://localhost:8000/livez

# 3) create a user, get a token, use the API
curl -s -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo-password-123"}'
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo-password-123"}'
curl -s http://localhost:8000/todos -H "Authorization: Bearer TOKEN"
```

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# needs a local PostgreSQL; use the compose db or set DATABASE_URL
pytest -q
```

## Configuration

All secrets/config come from environment variables (see `.env.example`).
No credentials are committed to this repository.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://todo:todo@localhost:5432/todo` | SQLAlchemy DSN |
| `JWT_SECRET` | (dev default only) | HS256 signing secret |
| `JWT_ALGORITHM` | `HS256` | signing algorithm |
| `TOKEN_EXPIRE_MINUTES` | `60` | access token TTL |

In Compose, `JWT_SECRET` is set to a non-secret dev value for local runs;
production deployments must override it.
