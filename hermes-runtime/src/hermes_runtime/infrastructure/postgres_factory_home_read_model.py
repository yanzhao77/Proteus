"""Source-derived, GET-only Factory Home projections over existing authority tables."""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.factory_home_read_model import ActorProjectScope, FactoryHomeReadModel, UnavailableFactoryHomeReadModel


class DenyAllActorProjectScope:
    """Safe production default until a verified identity-to-scope adapter is wired."""

    def project_ids_for(self, actor_scope: Mapping[str, Any]) -> Optional[Sequence[str]]:
        return None


class PostgresCreatorActorProjectScope:
    """Conservative read scope: projects requested by this verified OIDC subject.

    The Project table has no membership/ownership model. The initial transition
    record is the smallest existing authority fact that binds a user requester to
    a Project. This is not an RBAC system and never falls back to global access.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def project_ids_for(self, actor_scope: Mapping[str, Any]) -> Optional[Sequence[str]]:
        subject = actor_scope.get("identity_subject")
        actor_id = actor_scope.get("actor_id")
        if actor_scope.get("identity_verified") is not True or not isinstance(subject, str) or not subject:
            return None
        if actor_id != subject:
            return None
        query = """
            SELECT DISTINCT owned.project_id
            FROM (
              SELECT binding.project_id
              FROM public.entry_approval_materialized_bindings binding
              JOIN public.entry_approval_bridges bridge ON bridge.bridge_id = binding.bridge_id
              WHERE bridge.creator_subject = %s
                AND bridge.status = 'MATERIALIZED'
              UNION
              SELECT transition.project_id
              FROM public.project_transition_records transition
              WHERE transition.previous_state IS NULL
                AND transition.requested_by_type = 'user'
                AND transition.requested_by_id = %s
            ) AS owned
            ORDER BY owned.project_id ASC
        """
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(query, (subject, subject)).fetchall()
            return tuple(str(row["project_id"]) for row in rows)
        except Exception:
            return None


class PostgresFactoryHomeReadModel(FactoryHomeReadModel):
    """Reads existing Project and Human Gate facts without issuing authority commands."""

    def __init__(self, dsn: str, actor_project_scope: ActorProjectScope, draft_reader: Any = None) -> None:
        self._dsn = dsn
        self._actor_project_scope = actor_project_scope
        self._draft_reader = draft_reader

    def factory_home_snapshot(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = self._scope(actor_scope)
        if scope is None:
            return UnavailableFactoryHomeReadModel().factory_home_snapshot(actor_scope)
        portfolio = self._portfolio_for(scope)
        gates = self._gates_for(scope)
        if portfolio["availability"] == "DEGRADED" or gates["availability"] == "DEGRADED":
            availability = "DEGRADED"
        else:
            availability = "CURRENT"
        all_items = list(portfolio["items"])
        continuations = [item for item in all_items if item["display_state"] not in {"ACCEPTED", "FAILED", "CANCELLED"}]
        outcomes = [item for item in all_items if item["display_state"] in {"ACCEPTED", "FAILED", "CANCELLED"}]
        return {
            "availability": availability,
            "reason": None,
            "as_of": None,
            "cursor": None,
            "freshness": "NOT_AVAILABLE",
            "source": "projects,human_gate_requests",
            "source_version": None,
            "actor_scope": "SCOPED",
            "attention": gates["items"],
            "continuations": continuations,
            "outcomes": outcomes,
            "factory_status": self.factory_status(actor_scope),
            "drafts": self.production_drafts(actor_scope),
        }

    def production_portfolio(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = self._scope(actor_scope)
        if scope is None:
            return UnavailableFactoryHomeReadModel().production_portfolio(actor_scope)
        return self._portfolio_for(scope)

    def production_snapshot(self, project_id: str, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = self._scope(actor_scope)
        if scope is None:
            return UnavailableFactoryHomeReadModel().production_snapshot(project_id, actor_scope)
        if project_id not in set(scope):
            return {
                "availability": "NOT_AVAILABLE",
                "reason": "PRODUCTION_NOT_AVAILABLE",
                "as_of": None,
                "freshness": "NOT_AVAILABLE",
                "source": None,
                "source_version": None,
                "item": None,
            }
        portfolio = self._portfolio_for(scope)
        if portfolio["availability"] != "CURRENT":
            return {**portfolio, "item": None}
        item = next((row for row in portfolio["items"] if row["project_id"] == project_id), None)
        return {
            "availability": "CURRENT" if item else "NOT_AVAILABLE",
            "reason": None if item else "PRODUCTION_NOT_AVAILABLE",
            "as_of": item["as_of"] if item else None,
            "freshness": "NOT_AVAILABLE",
            "source": "projects" if item else None,
            "source_version": item["source_version"] if item else None,
            "item": item,
        }

    def gate_attention(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = self._scope(actor_scope)
        if scope is None:
            return UnavailableFactoryHomeReadModel().gate_attention(actor_scope)
        return self._gates_for(scope)

    def production_drafts(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        subject = actor_scope.get("identity_subject")
        if actor_scope.get("identity_verified") is not True or actor_scope.get("actor_id") != subject or not isinstance(subject, str) or not subject:
            return UnavailableFactoryHomeReadModel().production_drafts(actor_scope)
        if self._draft_reader is None:
            return UnavailableFactoryHomeReadModel().production_drafts(actor_scope)
        try:
            return self._draft_reader.list(subject)
        except Exception:
            return self._degraded("DRAFT_SOURCE_UNAVAILABLE")

    def factory_status(self, actor_scope: Mapping[str, Any]) -> Mapping[str, Any]:
        # There is no separate Factory lifecycle authority. Report the absence of
        # a health fact explicitly rather than inferring health from the browser
        # or from a successful read query.
        scope = self._scope(actor_scope)
        if scope is None:
            return UnavailableFactoryHomeReadModel().factory_status(actor_scope)
        return {
            "availability": "DEGRADED",
            "reason": "FACTORY_STATUS_FACTS_NOT_AVAILABLE",
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": "project_scope",
            "source_version": None,
            "control_plane": "UNKNOWN",
            "workforce": "UNKNOWN",
            "event_stream": "UNKNOWN",
            "degraded_reasons": ["FACTORY_STATUS_FACTS_NOT_AVAILABLE"],
        }

    def _scope(self, actor_scope: Mapping[str, Any]) -> Optional[tuple[str, ...]]:
        project_ids = self._actor_project_scope.project_ids_for(actor_scope)
        if project_ids is None:
            return None
        return tuple(sorted({str(project_id) for project_id in project_ids if str(project_id)}))

    def _portfolio_for(self, project_ids: Sequence[str]) -> Mapping[str, Any]:
        if not project_ids:
            return {
                "availability": "CURRENT",
                "reason": None,
                "as_of": None,
                "freshness": "NOT_AVAILABLE",
                "source": "projects",
                "source_version": None,
                "items": [],
            }
        query = """
            SELECT p.project_id, p.title, p.state, p.version, p.updated_at,
                   binding.master_plan_revision_id,
                   (SELECT COUNT(*) FROM public.human_gate_requests g
                    WHERE g.project_id = p.project_id AND g.request_state = 'REQUESTED') AS gate_count
            FROM public.projects p
            LEFT JOIN public.entry_approval_materialized_bindings binding ON binding.project_id = p.project_id
            WHERE p.project_id = ANY(%s)
            ORDER BY p.updated_at DESC, p.project_id ASC
        """
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(query, (list(project_ids),)).fetchall()
            return {
                "availability": "CURRENT",
                "reason": None,
                "as_of": None,
                "freshness": "NOT_AVAILABLE",
                "source": "projects,entry_approval_materialized_bindings",
                "source_version": None,
                "items": [self._production_card(row) for row in rows],
            }
        except Exception:
            return self._degraded("PORTFOLIO_SOURCE_UNAVAILABLE")

    def _gates_for(self, project_ids: Sequence[str]) -> Mapping[str, Any]:
        if not project_ids:
            return {
                "availability": "CURRENT",
                "reason": None,
                "as_of": None,
                "freshness": "NOT_AVAILABLE",
                "source": "human_gate_requests",
                "source_version": None,
                "items": [],
            }
        query = """
            SELECT g.gate_request_id, g.project_id, p.title, g.action_scope, g.reason,
                   g.expires_at, g.request_state, g.version, g.updated_at
            FROM public.human_gate_requests g
            JOIN public.projects p ON p.project_id = g.project_id
            WHERE g.project_id = ANY(%s) AND g.request_state = 'REQUESTED'
            ORDER BY g.expires_at ASC, g.gate_request_id ASC
        """
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(query, (list(project_ids),)).fetchall()
            return {
                "availability": "CURRENT",
                "reason": None,
                "as_of": None,
                "freshness": "NOT_AVAILABLE",
                "source": "human_gate_requests",
                "source_version": None,
                "items": [self._gate_card(row) for row in rows],
            }
        except Exception:
            return self._degraded("GATE_ATTENTION_SOURCE_UNAVAILABLE")

    @staticmethod
    def _production_card(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "production_id": row["project_id"],
            "project_id": row["project_id"],
            "display_name": row["title"],
            "display_state": row["state"],
            "phase": row["state"],
            "current_summary": None,
            "progress": None,
            "progress_basis": "NOT_AVAILABLE",
            "owner": None,
            "gate_count": int(row["gate_count"]),
            "plan_revision": row.get("master_plan_revision_id"),
            "last_updated": str(row["updated_at"]),
            "as_of": str(row["updated_at"]),
            "freshness": "NOT_AVAILABLE",
            "source": "projects,entry_approval_materialized_bindings",
            "source_version": int(row["version"]),
            "links": {"overview": "/factory-home/productions/{}".format(row["project_id"])},
        }

    @staticmethod
    def _gate_card(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "gate_id": row["gate_request_id"],
            "production_ref": row["project_id"],
            "production_name": row["title"],
            "action_summary": row["action_scope"],
            "risk": None,
            "reason": row["reason"],
            "evidence_count": None,
            "expires_at": str(row["expires_at"]),
            "status": row["request_state"],
            "as_of": str(row["updated_at"]),
            "freshness": "NOT_AVAILABLE",
            "source": "human_gate_requests",
            "source_version": int(row["version"]),
            "review_link": "/human-gates/{}".format(row["gate_request_id"]),
        }

    @staticmethod
    def _degraded(reason: str) -> Mapping[str, Any]:
        return {
            "availability": "DEGRADED",
            "reason": reason,
            "as_of": None,
            "freshness": "NOT_AVAILABLE",
            "source": None,
            "source_version": None,
            "items": [],
        }
