import os

from hermes_runtime.application.supervisor import OneShotCallableRole, RuntimeSupervisor, ServiceLoopConfig, SupervisedServiceLoop


def noop_role(_batch_size, stop_event):
    stop_event.set()
    return {"processed": 0, "reason": "entrypoint configured; durable services require database adapters"}


def build_supervisor() -> RuntimeSupervisor:
    config = ServiceLoopConfig(
        batch_size=int(os.getenv("HERMES_SERVICE_BATCH_SIZE", "100")),
        poll_interval_seconds=float(os.getenv("HERMES_SERVICE_POLL_SECONDS", "1.0")),
    )
    roles = (
        "relay",
        "consumer-checkpoint",
        "scheduler-lease",
        "docker-worker",
        "reconcile",
    )
    return RuntimeSupervisor(tuple(SupervisedServiceLoop(OneShotCallableRole(role, noop_role), config) for role in roles))


def main() -> int:
    supervisor = build_supervisor()
    supervisor.start()
    supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
