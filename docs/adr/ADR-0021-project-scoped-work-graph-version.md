# ADR-0021: Project-Scoped Work Graph Version

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime Design V1.2 §6.3](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#63-dag-改写)

## Context

ADR-0009 requires optimistic versions but left Work Graph version granularity open. A Graph Patch may create multiple Tasks and typed edges, and concurrent dependency patches must never combine into a Task DAG cycle.

## Decision

Maintain one monotonic Work Graph version per Project. Every successful Graph Patch locks that Project version row, validates `base_graph_version`, evaluates the complete proposed Task dependency graph, applies all operations and increments the version exactly once in one PostgreSQL transaction. A rejected or replayed Patch does not increment the graph version.

Only `Task -DEPENDS_ON-> Task` edges participate in the DAG cycle check and READY calculation. Other typed Work Graph edges share the atomic patch and graph version but may form semantic cycles.

## Alternatives Considered

Per-Task versions cannot serialize multi-Task cycle creation without more complex locking. A global version creates unrelated cross-project contention. Serializable transactions alone do not express the client-visible `base_graph_version` contract.

## Consequences

Graph mutation within one Project is intentionally serialized for P0. This provides a simple cross-connection correctness boundary; later partitioning requires a superseding ADR and equivalent cycle-safety evidence.

## Validation

CT-008 integration tests use independent PostgreSQL connections to propose opposite dependencies at the same base version. Exactly one Patch succeeds and the resulting Task DAG remains acyclic.

## Open Questions

Graph snapshot compaction and safe partitioning thresholds remain open.
