import os
from pathlib import Path

from hermes_runtime.config import env_or_file
from hermes_runtime.infrastructure.postgres import PostgresStore


def main() -> int:
    dsn = env_or_file("HERMES_DATABASE_URL")
    if not dsn:
        raise RuntimeError("HERMES_DATABASE_URL_REQUIRED")
    migrations = sorted(Path(__file__).parents[2].joinpath("migrations").glob("*.sql"))
    store = PostgresStore(dsn)
    for migration in migrations:
        store.apply_migration(migration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
