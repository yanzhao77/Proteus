import unittest

from hermes_runtime.application.entry_approval_bridge_saga import ApprovalBridgeSaga
from hermes_runtime.domain.models import CommandReceipt


class _ControlPlane:
    def __init__(self): self.calls = []
    def create_project(self, command):
        self.calls.append(("project", command)); return CommandReceipt(command.envelope.command_id, "SUCCEEDED", "PROJECT_CREATED", 1, (), {"project_id": command.envelope.project_id})
    def apply_work_graph_patch(self, command):
        self.calls.append(("graph", command)); return CommandReceipt(command.envelope.command_id, "SUCCEEDED", "GRAPH_APPLIED", 1, (), {})
    def create_verification_plan(self, command):
        self.calls.append(("verification", command)); return CommandReceipt(command.envelope.command_id, "SUCCEEDED", "VERIFICATION_CREATED", 1, (), {})


class _Repo:
    def __init__(self): self.steps=[]; self.transitions=[]; self.materialized=[]
    def record_child_step(self, *args): self.steps.append(args)
    def transition(self, *args): self.transitions.append(args)
    def materialize(self, *args): self.materialized.append(args)


class E4SagaTests(unittest.TestCase):
    def test_materializes_only_through_control_plane_ports(self):
        cp, repo = _ControlPlane(), _Repo()
        saga = ApprovalBridgeSaga(cp, repo)
        bridge = {"bridge_id":"bridge", "status":"PROCESSING", "compiled_blueprint": {
            "project_id":"project", "project_command_id":"project-c", "graph_command_id":"graph-c", "source":{"draft_id":"draft"},
            "tasks":[{"task_id":"task-a","title":"A","verification_plan_id":"vp-a","create_command_id":"vpc-a"},{"task_id":"task-b","title":"B","verification_plan_id":"vp-b","create_command_id":"vpc-b"}],
            "dependencies":[{"task_id":"task-b","depends_on_task_id":"task-a"}],
        }}
        result = saga.materialize(bridge)
        self.assertEqual(result, {"bridge_id":"bridge","status":"MATERIALIZED","project_id":"project"})
        self.assertEqual([kind for kind, _ in cp.calls], ["project","graph","verification","verification"])
        graph = cp.calls[1][1].patch
        self.assertEqual(graph.base_graph_version, 0)
        self.assertEqual(graph.operations[-1].task_id, "task-b")
        self.assertEqual(graph.operations[-1].depends_on_task_id, "task-a")
        self.assertEqual(repo.materialized, [("bridge", "project")])
        self.assertNotIn("worker", str(cp.calls).lower())
        self.assertNotIn("scheduler", str(cp.calls).lower())
