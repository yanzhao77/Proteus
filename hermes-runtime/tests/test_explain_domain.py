import unittest

from hermes_runtime.domain.explain import (
    ExplainEdge,
    ExplainNode,
    ExplainNodeStatus,
    ExplainRejected,
    ExplainSnapshotInput,
    RedactionClass,
    build_explain_snapshot,
)


def _snapshot(**overrides):
    values = dict(
        project_id="project-1",
        source_type="decision",
        source_id="decision-1",
        source_version=1,
        source_hash="sha256:decision",
        schema_version="decision-explain/1.0",
        producer_version="explain-runtime/1.0",
        summary={"why": "diagnosis evidence gain", "selected": "repair"},
        nodes=(
            ExplainNode(
                "situation-1",
                "Situation",
                "situation-1",
                1,
                "sha256:situation",
                safe_summary={"why": "triggered by verification failure"},
            ),
            ExplainNode(
                "decision-1",
                "DecisionRecord",
                "decision-1",
                1,
                "sha256:decision",
                safe_summary={"selected": "repair"},
            ),
        ),
        edges=(ExplainEdge("situation-1", "decision-1", "caused"),),
        redaction_class=RedactionClass.INTERNAL,
        retention_policy="p3-standard-90d",
        authorization_scope={"tenant_id": "tenant-1", "project_id": "project-1"},
    )
    values.update(overrides)
    return ExplainSnapshotInput(**values)


class ExplainDomainTests(unittest.TestCase):
    def test_snapshot_hash_is_deterministic_under_node_and_edge_order(self):
        first = build_explain_snapshot(_snapshot())
        second = build_explain_snapshot(
            _snapshot(
                nodes=tuple(reversed(_snapshot().nodes)),
                edges=tuple(reversed(_snapshot().edges)),
            )
        )
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])
        self.assertEqual(first["ref_graph_hash"], second["ref_graph_hash"])

    def test_missing_link_is_explicit_and_never_fabricated(self):
        result = build_explain_snapshot(
            _snapshot(
                nodes=(
                    ExplainNode(
                        "missing-gate",
                        "HumanGateDecision",
                        "gate-missing",
                        0,
                        "",
                        ExplainNodeStatus.MISSING,
                        "gate decision was not retained",
                    ),
                ),
                edges=(),
            )
        )
        self.assertEqual(
            [{"node_id": "missing-gate", "node_type": "HumanGateDecision", "missing_reason": "gate decision was not retained"}],
            result["missing_links"],
        )
        with self.assertRaisesRegex(ExplainRejected, "MISSING_IMMUTABLE_FACT_LINK"):
            build_explain_snapshot(
                _snapshot(
                    nodes=(
                        ExplainNode(
                            "missing-gate",
                            "HumanGateDecision",
                            "gate-missing",
                            0,
                            "",
                            ExplainNodeStatus.MISSING,
                            "",
                        ),
                    ),
                    edges=(),
                )
            )

    def test_cycle_duplicate_and_unknown_edge_fail_closed(self):
        with self.assertRaisesRegex(ExplainRejected, "EXPLAIN_SNAPSHOT_CONFLICT"):
            build_explain_snapshot(
                _snapshot(
                    edges=(
                        ExplainEdge("situation-1", "decision-1", "caused"),
                        ExplainEdge("decision-1", "situation-1", "explains"),
                    )
                )
            )
        with self.assertRaisesRegex(ExplainRejected, "EXPLAIN_SNAPSHOT_CONFLICT"):
            build_explain_snapshot(
                _snapshot(
                    nodes=(_snapshot().nodes[0], _snapshot().nodes[0]),
                    edges=(),
                )
            )
        with self.assertRaisesRegex(ExplainRejected, "MISSING_IMMUTABLE_FACT_LINK"):
            build_explain_snapshot(
                _snapshot(edges=(ExplainEdge("situation-1", "missing", "caused"),))
            )

    def test_secret_like_values_are_rejected_before_snapshot(self):
        with self.assertRaisesRegex(ExplainRejected, "RETENTION_REDACTION_VIOLATION"):
            build_explain_snapshot(_snapshot(summary={"raw": "password=super-secret"}))


if __name__ == "__main__":
    unittest.main()
