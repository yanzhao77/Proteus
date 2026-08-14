import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Mapping, Optional, Protocol, Tuple


class ServiceCriticality(str, Enum):
    CRITICAL = "CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


class ServiceStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    BACKING_OFF = "BACKING_OFF"
    FAILED = "FAILED"
    STOPPING = "STOPPING"


class RuntimeServiceRole(Protocol):
    name: str
    criticality: ServiceCriticality
    relies_on_database_fencing: bool

    def run_once(self, batch_size: int, stop_event: threading.Event) -> Mapping[str, object]:
        ...


@dataclass(frozen=True)
class ServiceLoopConfig:
    batch_size: int = 100
    poll_interval_seconds: float = 0.1
    initial_backoff_seconds: float = 0.1
    max_backoff_seconds: float = 5.0
    jitter_ratio: float = 0.1
    max_consecutive_failures: int = 3
    max_concurrency: int = 1

    def validate(self) -> None:
        if self.batch_size < 1:
            raise ValueError("SERVICE_BATCH_SIZE_INVALID")
        if self.poll_interval_seconds < 0 or self.initial_backoff_seconds < 0:
            raise ValueError("SERVICE_INTERVAL_INVALID")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("SERVICE_BACKOFF_INVALID")
        if self.max_concurrency != 1:
            raise ValueError("SERVICE_LOCAL_CONCURRENCY_UNSUPPORTED")


@dataclass(frozen=True)
class ServiceSnapshot:
    name: str
    status: ServiceStatus
    criticality: ServiceCriticality
    iterations: int
    consecutive_failures: int
    last_error_code: str
    relies_on_database_fencing: bool


class SupervisedServiceLoop:
    def __init__(
        self,
        role: RuntimeServiceRole,
        config: ServiceLoopConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        config.validate()
        self._role = role
        self._config = config
        self._sleep = sleep
        self._random = random_source
        self._stop_event = threading.Event()
        self._status = ServiceStatus.STOPPED
        self._iterations = 0
        self._consecutive_failures = 0
        self._last_error_code = ""
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._status = ServiceStatus.STARTING
        self._thread = threading.Thread(target=self.run_forever, name=f"hermes-{self._role.name}", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._status = ServiceStatus.STOPPING
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout_seconds)
        self._status = ServiceStatus.STOPPED

    def run_forever(self, max_iterations: Optional[int] = None) -> None:
        backoff = self._config.initial_backoff_seconds
        self._status = ServiceStatus.RUNNING
        while not self._stop_event.is_set():
            if max_iterations is not None and self._iterations >= max_iterations:
                break
            try:
                self._role.run_once(self._config.batch_size, self._stop_event)
                self._iterations += 1
                self._consecutive_failures = 0
                self._last_error_code = ""
                self._status = ServiceStatus.RUNNING
                if self._config.poll_interval_seconds:
                    self._sleep(self._config.poll_interval_seconds)
                backoff = self._config.initial_backoff_seconds
            except Exception as exc:
                self._iterations += 1
                self._consecutive_failures += 1
                self._last_error_code = exc.__class__.__name__
                self._status = ServiceStatus.BACKING_OFF
                if self._role.criticality is ServiceCriticality.CRITICAL and (
                    self._consecutive_failures >= self._config.max_consecutive_failures
                ):
                    self._status = ServiceStatus.FAILED
                    break
                self._sleep(self._with_jitter(backoff))
                backoff = min(self._config.max_backoff_seconds, backoff * 2 if backoff else 0)
        if self._status is not ServiceStatus.FAILED:
            self._status = ServiceStatus.STOPPED if self._stop_event.is_set() else self._status

    def snapshot(self) -> ServiceSnapshot:
        return ServiceSnapshot(
            name=self._role.name,
            status=self._status,
            criticality=self._role.criticality,
            iterations=self._iterations,
            consecutive_failures=self._consecutive_failures,
            last_error_code=self._last_error_code,
            relies_on_database_fencing=self._role.relies_on_database_fencing,
        )

    def _with_jitter(self, seconds: float) -> float:
        spread = seconds * self._config.jitter_ratio
        return max(0.0, seconds - spread + (2 * spread * self._random()))


class RuntimeSupervisor:
    def __init__(self, loops: Tuple[SupervisedServiceLoop, ...]) -> None:
        names = [loop.snapshot().name for loop in loops]
        if len(names) != len(set(names)):
            raise ValueError("SUPERVISOR_DUPLICATE_SERVICE_NAME")
        self._loops: Dict[str, SupervisedServiceLoop] = {loop.snapshot().name: loop for loop in loops}

    def start(self) -> None:
        for loop in self._loops.values():
            loop.start()

    def stop(self) -> None:
        for loop in self._loops.values():
            loop.stop()

    def snapshots(self) -> Tuple[ServiceSnapshot, ...]:
        return tuple(loop.snapshot() for loop in self._loops.values())

    def readiness(self) -> Mapping[str, object]:
        snapshots = self.snapshots()
        failed_critical = [
            snapshot.name
            for snapshot in snapshots
            if snapshot.criticality is ServiceCriticality.CRITICAL and snapshot.status is ServiceStatus.FAILED
        ]
        return {
            "ready": not failed_critical,
            "failed_critical_services": tuple(failed_critical),
            "services": tuple(snapshot.__dict__ for snapshot in snapshots),
        }


@dataclass
class OneShotCallableRole:
    name: str
    handler: Callable[[int, threading.Event], Mapping[str, object]]
    criticality: ServiceCriticality = ServiceCriticality.CRITICAL
    relies_on_database_fencing: bool = True

    def run_once(self, batch_size: int, stop_event: threading.Event) -> Mapping[str, object]:
        return self.handler(batch_size, stop_event)
