"""Read-only Worker Control Plane Product API contracts.

These contracts are deliberately separate from Worker/Scheduler/Execution authority.
They expose source-derived presentation projections only; no command is defined.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class WorkerControlPlaneReadModel(Protocol):
    def list_workers(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def worker_detail(self, worker_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def execution_queue(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class UnavailableWorkerControlPlaneReadModel:
    """Safe default when no authenticated source-derived composition is wired."""

    def list_workers(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": "WORKER_CONTROL_PLANE_READ_MODEL_NOT_CONFIGURED",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "items": [],
        }

    def worker_detail(self, worker_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": "WORKER_CONTROL_PLANE_READ_MODEL_NOT_CONFIGURED",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "item": None,
        }

    def execution_queue(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": "WORKER_CONTROL_PLANE_READ_MODEL_NOT_CONFIGURED",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "items": [],
        }
