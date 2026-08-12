import argparse
import os

from hermes_runtime.application.delivery import OutboxRelay
from hermes_runtime.infrastructure.postgres_delivery import (
    PostgresDeliveryStore,
    PostgresLocalPublisher,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one Hermes Outbox batch")
    parser.add_argument("--dsn", default=os.environ.get("HERMES_DATABASE_URL"))
    parser.add_argument("--owner", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()
    if not args.dsn:
        parser.error("--dsn or HERMES_DATABASE_URL is required")
    store = PostgresDeliveryStore(args.dsn)
    relay = OutboxRelay(
        store,
        PostgresLocalPublisher(args.dsn),
        args.owner,
        lease_seconds=args.lease_seconds,
        max_attempts=args.max_attempts,
    )
    result = relay.run_once(args.batch_size)
    print(
        "claimed={0.claimed} published={0.published} retried={0.retried} "
        "dead_lettered={0.dead_lettered} stale={0.stale_confirmations}".format(
            result
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
