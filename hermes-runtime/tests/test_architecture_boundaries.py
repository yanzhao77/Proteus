import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "src" / "hermes_runtime"


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_domain_has_no_infrastructure_or_framework_imports(self):
        forbidden = {"psycopg", "sqlalchemy", "fastapi", "docker"}
        violations = []
        for path in (SOURCE / "domain").glob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name.split(".")[0] for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in forbidden:
                        violations.append("{} imports {}".format(path.name, name))
        self.assertEqual([], violations)

    def test_no_generic_task_state_mutator_exists(self):
        forbidden = {
            "update_task_status",
            "set_task_passed",
            "set_task_failed",
            "set_project_state",
        }
        definitions = set()
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            definitions.update(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        self.assertTrue(forbidden.isdisjoint(definitions), definitions & forbidden)

    def test_only_controlled_postgres_stores_contain_task_update_sql(self):
        offenders = []
        for path in SOURCE.rglob("*.py"):
            text = path.read_text().upper()
            if "UPDATE TASKS" in text and path.name not in {
                "postgres.py",
                "postgres_graph.py",
            }:
                offenders.append(str(path.relative_to(SOURCE)))
        self.assertEqual([], offenders)

    def test_only_project_store_contains_project_update_sql(self):
        offenders = []
        for path in SOURCE.rglob("*.py"):
            text = path.read_text().upper()
            if "UPDATE PROJECTS" in text and path.name != "postgres_project.py":
                offenders.append(str(path.relative_to(SOURCE)))
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
