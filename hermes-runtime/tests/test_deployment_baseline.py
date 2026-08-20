import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class DeploymentBaselineTests(unittest.TestCase):
    def test_dockerfile_is_non_root_and_uses_hardened_runtime_shape(self):
        text = (ROOT / "hermes-runtime" / "Dockerfile").read_text()
        self.assertIn("USER hermes", text)
        self.assertIn("--no-cache-dir", text)
        self.assertIn("RUN chmod 0644 /app/migrations/*.sql", text)
        self.assertLess(text.index("RUN chmod 0644 /app/migrations/*.sql"), text.index("USER hermes"))
        self.assertNotIn("USER root\nCMD", text)

    def test_compose_defines_distinct_roles_and_secret_files_without_plain_passwords(self):
        text = (ROOT / "deploy" / "p5" / "docker-compose.single-node.yml").read_text()
        for service in ("postgres:", "migration-bootstrap:", "api:", "runtime-supervisor:", "minio:", "vault:", "otel-collector:"):
            self.assertIn(service, text)
        self.assertIn("read_only: true", text)
        self.assertIn("cap_drop: [\"ALL\"]", text)
        self.assertIn("no-new-privileges:true", text)
        self.assertIn("POSTGRES_PASSWORD_FILE", text)
        self.assertNotIn("POSTGRES_PASSWORD: hermes", text)
        self.assertNotIn("secret_value", text)

    def test_runbook_covers_backup_restore_rotation_and_forbidden_repairs(self):
        text = (ROOT / "docs" / "operations" / "P5_SINGLE_NODE_RUNBOOK.md").read_text()
        for phrase in ("Backup and restore", "Migration and rollback", "Secret rotation", "Forbidden operations"):
            self.assertIn(phrase, text)
        self.assertIn("do not patch authority", text.lower())

    def test_ci_workflow_runs_no_db_and_postgres_regression(self):
        text = (ROOT / ".github" / "workflows" / "hermes-p5.yml").read_text()
        self.assertIn("unittest discover", text)
        self.assertIn("postgres:16-alpine", text)
        self.assertIn("HERMES_TEST_DATABASE_URL", text)


if __name__ == "__main__":
    unittest.main()
