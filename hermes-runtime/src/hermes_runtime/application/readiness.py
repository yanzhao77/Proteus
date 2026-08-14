from dataclasses import dataclass
from typing import Mapping, Protocol


class ReadinessCheck(Protocol):
    def check(self) -> Mapping[str, object]:
        ...


@dataclass(frozen=True)
class StaticReadinessCheck:
    database_ready: bool = True
    migration_compatible: bool = True
    dependencies_ready: bool = True
    supervisor_ready: bool = True

    def check(self) -> Mapping[str, object]:
        ready = all(
            (
                self.database_ready,
                self.migration_compatible,
                self.dependencies_ready,
                self.supervisor_ready,
            )
        )
        return {
            "ready": ready,
            "database": "READY" if self.database_ready else "NOT_READY",
            "migrations": "COMPATIBLE" if self.migration_compatible else "INCOMPATIBLE",
            "dependencies": "READY" if self.dependencies_ready else "NOT_READY",
            "supervisor": "READY" if self.supervisor_ready else "NOT_READY",
        }
