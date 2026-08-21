from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from hermes_runtime.application.commands import ApplyWorkGraphPatch, CreateProject, CreateVerificationPlan
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.domain.graph import AddTaskDependency, CreateTask, GraphPatch, GraphTask
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope, VerificationPlan, VerificationPlanCheck


class BridgeRepository(Protocol):
    def get_approval(self, creator_subject: str, draft_id: str) -> Mapping[str, object]: ...
    def record_child_step(self, bridge_id: str, step: str, command_id: str, receipt: Mapping[str, object]) -> None: ...
    def transition(self, bridge_id: str, status: str, reason: str) -> None: ...
    def materialize(self, bridge_id: str, project_id: str) -> None: ...


@dataclass
class ApprovalBridgeSaga:
    control_plane: ControlPlane
    bridge_repository: BridgeRepository

    @staticmethod
    def _actor() -> Actor:
        return Actor(ActorType.CONTROL_PLANE, "e4-approval-bridge")

    def _envelope(
        self, command_id: str, command_type: str, project_id: str, reason: str,
        expected_version: int = 0,
    ) -> CommandEnvelope:
        return CommandEnvelope(command_id, command_type, command_id, expected_version, self._actor(), reason, project_id)

    def materialize(self, bridge: Mapping[str, Any]) -> Mapping[str, Any]:
        """Advance only via existing child command ports; caller reconciles deterministic receipts before each retry."""
        blueprint = bridge["compiled_blueprint"]
        bridge_id = bridge["bridge_id"]
        project_id = blueprint["project_id"]
        if bridge["status"] == "PROCESSING":
            receipt = self.control_plane.create_project(CreateProject(
                self._envelope(blueprint["project_command_id"], "project.create", project_id, "E4 approved entry plan"),
                blueprint["source"]["draft_id"], self._actor(),
            ))
            self.bridge_repository.record_child_step(bridge_id, "CREATE_PROJECT", blueprint["project_command_id"], receipt.__dict__)
            self.bridge_repository.transition(bridge_id, "PROJECT_CREATED", receipt.result_code)
        if bridge["status"] in {"PROCESSING", "PROJECT_CREATED"}:
            operations = []
            for task in blueprint["tasks"]:
                operations.append(CreateTask(GraphTask(task["task_id"], "entry-plan", task["title"])))
            for dependency in blueprint["dependencies"]:
                operations.append(AddTaskDependency(dependency["task_id"], dependency["depends_on_task_id"]))
            receipt = self.control_plane.apply_work_graph_patch(ApplyWorkGraphPatch(
                self._envelope(blueprint["graph_command_id"], "work_graph.apply_patch", project_id, "E4 deterministic plan lowering"),
                GraphPatch(0, bridge_id, tuple(operations)),
            ))
            self.bridge_repository.record_child_step(bridge_id, "APPLY_GRAPH", blueprint["graph_command_id"], receipt.__dict__)
            self.bridge_repository.transition(bridge_id, "GRAPH_APPLIED", receipt.result_code)
        self.bridge_repository.transition(bridge_id, "VERIFICATION_APPLYING", "E4_VERIFICATION_POLICY")
        for task in blueprint["tasks"]:
            plan = VerificationPlan(
                task["verification_plan_id"], task["task_id"], project_id, 1, "ACTIVE", ("current-artifact",),
                "all_required_pass", "worker_context_excluded", self._actor(),
                (VerificationPlanCheck(
                    f"check-{task['verification_plan_id']}", "artifact-policy", "e4-v1", True, 300,
                    "artifact satisfies frozen E4 verification policy", "E4", 1,
                ),),
            )
            receipt = self.control_plane.create_verification_plan(CreateVerificationPlan(
                self._envelope(
                    task["create_command_id"], "verification_plan.create", project_id,
                    "E4 verification policy", task["verification_expected_task_version"],
                ), plan
            ))
            self.bridge_repository.record_child_step(bridge_id, "CREATE_VERIFICATION_PLAN", task["create_command_id"], receipt.__dict__)
        self.bridge_repository.materialize(bridge_id, project_id)
        return {"bridge_id": bridge_id, "status": "MATERIALIZED", "project_id": project_id}
