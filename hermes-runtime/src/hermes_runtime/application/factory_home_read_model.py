"""Read-only Factory Home Product API contracts.

These contracts are deliberately separate from Project/Task/Execution authority.
They expose source-derived presentation projections only; no command is defined.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, Sequence


class ActorProjectScope(Protocol):
    """Returns authenticated actor-visible Project IDs, or None when unavailable."""

    def project_ids_for(self, actor_scope: Mapping[str, Any]) -> Optional[Sequence[str]]:
        ...


class FactoryHomeReadModel(Protocol):
    def factory_home_snapshot(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def production_portfolio(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def production_snapshot(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def gate_attention(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def production_drafts(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def factory_status(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


def unavailable_module(reason: str) -> Mapping[str, Any]:
    return {
        "availability": "NOT_AVAILABLE",
        "reason": reason,
        "as_of": None,
        "freshness": "NOT_AVAILABLE",
        "source": None,
        "source_version": None,
        "items": [],
    }


class UnavailableFactoryHomeReadModel:
    """Safe default when no authenticated source-derived composition is wired."""

    def factory_home_snapshot(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": "FACTORY_HOME_READ_MODEL_NOT_CONFIGURED",
            "as_of": None,
            "cursor": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "actor_scope": "NOT_AVAILABLE",
            "attention": [],
            "continuations": [],
            "outcomes": [],
            "factory_status": self.factory_status(actor_scope),
            "drafts": self.production_drafts(actor_scope),
        }

    def production_portfolio(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return unavailable_module("PORTFOLIO_READ_MODEL_NOT_CONFIGURED")

    def production_snapshot(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return unavailable_module("PRODUCTION_SNAPSHOT_READ_MODEL_NOT_CONFIGURED")

    def gate_attention(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return unavailable_module("GATE_ATTENTION_READ_MODEL_NOT_CONFIGURED")

    def production_drafts(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_IMPLEMENTED",
            "reason": "ENTRY_DRAFT_AUTHORITY_NOT_IMPLEMENTED",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "items": [],
        }

    def factory_status(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "NOT_AVAILABLE",
            "reason": "FACTORY_STATUS_SOURCE_NOT_IMPLEMENTED",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "control_plane": "NOT_AVAILABLE",
            "workforce": "NOT_AVAILABLE",
            "event_stream": "NOT_AVAILABLE",
            "degraded_reasons": ["FACTORY_STATUS_SOURCE_NOT_IMPLEMENTED"],
        }
