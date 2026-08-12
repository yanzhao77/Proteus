from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.ports import EventPublisher
from hermes_runtime.domain.models import EventEnvelope, OutboxClaim, RedriveOutbox


class PublishFailure(RuntimeError):
    def __init__(self, category: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class RelayRunResult:
    claimed: int
    published: int
    retried: int
    dead_lettered: int
    stale_confirmations: int


class OutboxRelay:
    def __init__(
        self,
        store,
        publisher: EventPublisher,
        owner: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        lease_seconds: int = 30,
        max_attempts: int = 5,
        backoff_seconds: Callable[[int], int] = lambda attempt: min(300, 2 ** attempt),
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._owner = owner
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    def run_once(self, batch_size: int = 100) -> RelayRunResult:
        now = self._clock()
        claims = self._store.claim_outbox(
            self._owner, now, self._lease_seconds, batch_size, self._max_attempts
        )
        published = retried = dead_lettered = stale = 0
        for claim in claims:
            try:
                self._publisher.publish(claim.envelope)
            except PublishFailure as exc:
                next_attempt_at = now + timedelta(
                    seconds=self._backoff_seconds(claim.attempt_count)
                )
                outcome = self._store.mark_outbox_failure(
                    claim,
                    self._owner,
                    now,
                    exc.retryable,
                    exc.category,
                    str(exc),
                    next_attempt_at,
                    self._max_attempts,
                )
                retried += outcome == "PENDING"
                dead_lettered += outcome == "DEAD_LETTERED"
                stale += outcome == "STALE_CLAIM"
                continue
            if self._store.mark_outbox_published(claim, self._owner, now):
                published += 1
            else:
                stale += 1
        return RelayRunResult(len(claims), published, retried, dead_lettered, stale)

    def recover_expired_leases(self, batch_size: int = 100) -> RelayRunResult:
        return self.run_once(batch_size)

    def redrive(self, command: RedriveOutbox):
        return self._store.redrive_outbox(command, self._clock())

    def reconcile_once(self) -> Mapping[str, int]:
        return self._store.delivery_metrics(self._clock())
