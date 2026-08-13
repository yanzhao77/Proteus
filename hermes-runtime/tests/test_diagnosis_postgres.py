import threading
import unittest
from pathlib import Path

import os

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:
    psycopg = None
    Jsonb = None

from hermes_runtime.application.diagnoses import DiagnosisEngine, RunDiagnosis
from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.handlers import ControlPlane
from hermes_runtime.application.commands import CreateProject
from hermes_runtime.domain.models import Actor, ActorType, CommandEnvelope
from hermes_runtime.infrastructure.postgres_diagnosis import (
    DiagnosisFaultPoint,
    PostgresDiagnosisStore,
)
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_situation import PostgresSituationStore


DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires real PostgreSQL 14+")
class DiagnosisPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresDiagnosisStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.engine = DiagnosisEngine(self.store)

    def create_fixture(
        self, suffix="ok", finding_codes=("TEST_ASSERTION_FAILURE",),
        evidence_refs=("evidence-ok",), evidence_valid=True,
        evidence_sequence=0, evidence_project="project-1",
        evidence_task="task-1", evidence_artifact="artifact-1",
        evidence_hash="sha256:artifact", evidence_producer="verifier-1",
        invalidated=False,
    ):
        self.create_project("project-1")
        with psycopg.connect(DATABASE_URL) as connection:
            if evidence_project != "project-1":
                self.create_project(evidence_project)
            connection.execute(
                """INSERT INTO tasks(task_id,project_id,state,version)
                   VALUES (%s,%s,'COMPLETION_CLAIMED',1)""",
                ("task-1", "project-1"),
            )
            if evidence_task != "task-1":
                connection.execute(
                    """INSERT INTO tasks(task_id,project_id,state,version)
                       VALUES (%s,%s,'COMPLETION_CLAIMED',1)""",
                    (evidence_task, evidence_project),
                )
            connection.execute(
                """INSERT INTO verifier_identities(verifier_id,active)
                   VALUES ('verifier-1', true)"""
            )
            for command_id in (
                "cmd-run-" + suffix,
                "cmd-plan-" + suffix,
            ):
                connection.execute(
                    """INSERT INTO command_receipts(
                       command_id,project_id,command_type,idempotency_key,
                       request_hash,status,result,completed_at)
                       VALUES (%s,'project-1','test.seed',%s,'fixture',
                               'APPLIED','{}',now())""",
                    (command_id, command_id),
                )
            connection.execute(
                """INSERT INTO agent_runs(
                   run_id,project_id,task_id,run_kind,agent_identity,
                   context_identity,status,created_by,command_id)
                   VALUES ('verifier-run-1','project-1','task-1','VERIFIER',
                           'verifier-1','verifier-context-1','ADMITTED',
                           'fixture',%s)""",
                ("cmd-run-" + suffix,),
            )
            connection.execute(
                """INSERT INTO verification_plans(
                   verification_plan_id,task_id,project_id,version,status,
                   artifact_selectors,aggregation_rule,independence,created_by,
                   command_id)
                   VALUES ('plan-1','task-1','project-1',1,'ACTIVE',
                           '["artifact-1"]','all_required_pass',
                           'worker_context_excluded','fixture',%s)""",
                ("cmd-plan-" + suffix,),
            )
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,'project-1','verification.record',%s,'fixture',
                           'APPLIED','{}',now())""",
                ("cmd-verification-" + suffix, "key-verification-" + suffix),
            )
            connection.execute(
                """INSERT INTO artifacts(
                   artifact_id,task_id,content_hash,media_type,produced_by)
                   VALUES (%s,%s,%s,'text/plain','worker-1')""",
                ("artifact-1", "task-1", "sha256:artifact"),
            )
            if evidence_artifact != "artifact-1":
                connection.execute(
                    """INSERT INTO artifacts(
                       artifact_id,task_id,content_hash,media_type,produced_by)
                       VALUES (%s,%s,%s,'text/plain','worker-2')""",
                    (evidence_artifact, evidence_task, evidence_hash),
                )
            for evidence_id in evidence_refs:
                connection.execute(
                    """INSERT INTO evidence(
                       evidence_id,artifact_id,artifact_hash,producer_identity,
                       valid,observed_at_sequence,invalidated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,
                               CASE WHEN %s THEN now() ELSE NULL END)""",
                    (evidence_id, evidence_artifact, evidence_hash,
                     evidence_producer, evidence_valid, evidence_sequence,
                     invalidated),
                )
            connection.execute(
                """INSERT INTO verification_results(
                   verification_id,task_id,artifact_id,artifact_hash,
                   verifier_identity,criteria,verdict,correlation_id,
                   occurred_at,command_id,authority_status,plan_id,
                   plan_version,project_id,verifier_run_id,started_at,completed_at)
                   VALUES (%s,'task-1','artifact-1','sha256:artifact',
                           'verifier-1','plan-1:1','FAIL',%s,now(),%s,
                           'AUTHORITATIVE','plan-1',1,'project-1',
                           'verifier-run-1',now(),now())""",
                ("verification-" + suffix, "corr-" + suffix,
                 "cmd-verification-" + suffix),
            )
            connection.execute(
                """INSERT INTO verification_check_results(
                   verification_id,check_id,status,finding_codes,evidence_refs,
                   started_at,completed_at)
                   VALUES (%s,'check-1','FAIL',%s,%s,now(),now())""",
                ("verification-" + suffix, Jsonb(list(finding_codes)),
                 Jsonb(list(evidence_refs))),
            )
            for evidence_id in evidence_refs:
                connection.execute(
                    """INSERT INTO verification_evidence(verification_id,evidence_id)
                       VALUES (%s,%s)""",
                    ("verification-" + suffix, evidence_id),
                )
            payload = {
                "verification_id": "verification-" + suffix,
                "task_id": "task-1",
                "artifact_id": "artifact-1",
                "artifact_hash": "sha256:artifact",
                "artifact_refs": ["artifact-1"],
                "evidence_refs": list(evidence_refs),
                "verdict": "FAIL",
                "failure_type": finding_codes[0] if finding_codes else "unknown",
                "severity": "HIGH",
                "affected_components": ["component:test"],
            }
            connection.execute(
                """INSERT INTO event_log(
                   event_id,event_type,schema_version,producer_type,producer_id,
                   project_id,partition_key,command_id,correlation_id,task_id,payload)
                   VALUES (%s,'verification.recorded','1.0','verification_engine',
                           'verifier-1','project-1','project-1',%s,%s,'task-1',%s)""",
                ("evt-verification-" + suffix, "cmd-verification-" + suffix,
                 "corr-" + suffix, Jsonb(payload)),
            )
        situation_result = PostgresSituationStore(
            DATABASE_URL
        ).analyze_logged_event("evt-verification-" + suffix)
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT s.situation_id,s.version,s.analysis_context_id,c.context_hash
                   FROM situations s JOIN analysis_contexts c
                     ON c.analysis_context_id=s.analysis_context_id
                   WHERE s.situation_id=%s""",
                (situation_result["situation_id"],),
            ).fetchone()
        return {
            "situation_id": row[0],
            "version": row[1],
            "analysis_context_id": row[2],
            "context_hash": row[3],
        }

    def create_project(self, project_id):
        receipt = ControlPlane(PostgresProjectStore(DATABASE_URL)).create_project(
            CreateProject(
                CommandEnvelope(
                    "cmd-create-" + project_id, "project.create",
                    "key-create-" + project_id, 0,
                    Actor(ActorType.CONTROL_PLANE, "project-manager"),
                    "diagnosis fixture", project_id,
                ),
                "Diagnosis test project", Actor(ActorType.USER, "user-1"),
            )
        )
        PostgresSituationStore(DATABASE_URL).analyze_logged_event(receipt.event_ids[0])

    def command(self, fixture, suffix="1", **overrides):
        data = {
            "command_id": "cmd-diagnosis-" + suffix,
            "idempotency_key": "key-diagnosis-" + suffix,
            "project_id": "project-1",
            "situation_id": fixture["situation_id"],
            "situation_version": fixture["version"],
            "analysis_context_id": fixture["analysis_context_id"],
            "analysis_context_hash": fixture["context_hash"],
        }
        data.update(overrides)
        return RunDiagnosis(**data)

    def counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(
                "SELECT count(*) FROM " + table
            ).fetchone()[0] for table in (
                "diagnoses", "diagnosis_evidence", "diagnosis_hypotheses",
                "diagnosis_evidence_requests", "current_diagnoses",
                "event_log", "outbox_messages", "command_receipts",
            ))

    def test_confirmed_root_cause_commits_event_outbox_receipt(self):
        fixture = self.create_fixture()
        result = self.engine.run(self.command(fixture))
        self.assertEqual("CONFIRMED", result["root_cause_status"])
        self.assertEqual("test_assertion_failure", result["root_cause"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                """SELECT d.root_cause_status, d.root_cause, c.diagnosis_id,
                          e.event_type, o.event_id, r.status
                   FROM diagnoses d
                   JOIN current_diagnoses c ON c.diagnosis_id=d.diagnosis_id
                   JOIN command_receipts r ON r.command_id=d.command_id
                   JOIN event_log e ON e.event_id=%s
                   JOIN outbox_messages o ON o.event_id=e.event_id""",
                (result["event_id"],),
            ).fetchone()
        self.assertEqual(("CONFIRMED", "test_assertion_failure",
                          result["diagnosis_id"], "diagnosis.completed",
                          result["event_id"], "APPLIED"), row)

    def test_unknown_null_root_cause_is_valid(self):
        fixture = self.create_fixture(
            "unknown", finding_codes=("UNRECOGNIZED_FINDING",),
            evidence_refs=(),
        )
        result = self.engine.run(self.command(fixture, "unknown"))
        self.assertEqual("UNKNOWN", result["root_cause_status"])
        self.assertIsNone(result["root_cause"])
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT root_cause FROM diagnoses WHERE diagnosis_id=%s",
                (result["diagnosis_id"],),
            ).fetchone()
        self.assertIsNone(row[0])

    def test_exact_context_and_version_rejections(self):
        fixture = self.create_fixture("reject")
        cases = (
            ("version", {"situation_version": fixture["version"] + 1},
             "DIAGNOSIS_SITUATION_VERSION_CONFLICT"),
            ("hash", {"analysis_context_hash": "sha256:" + "0" * 64},
             "DIAGNOSIS_CONTEXT_HASH_MISMATCH"),
        )
        for label, overrides, code in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(CommandRejected, code):
                    self.engine.run(self.command(fixture, label, **overrides))

    def test_situation_not_open_rejected(self):
        fixture = self.create_fixture("resolved")
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """UPDATE situations SET status='RESOLVED', resolved_at=now(),
                   version=version+1 WHERE situation_id=%s""",
                (fixture["situation_id"],),
            )
        with self.assertRaisesRegex(CommandRejected, "DIAGNOSIS_SITUATION_NOT_OPEN"):
            self.engine.run(self.command(fixture, "resolved"))

    def test_future_wrong_scope_invalid_and_worker_evidence_rejected(self):
        cases = (
            ("future", {"evidence_sequence": 999}, "DIAGNOSIS_CONTEXT_FUTURE_FACT"),
            ("other_project", {"evidence_project": "project-2", "evidence_task": "task-2",
                               "evidence_artifact": "artifact-2"},
             "DIAGNOSIS_EVIDENCE_PROJECT_MISMATCH"),
            ("other_task", {"evidence_task": "task-2", "evidence_artifact": "artifact-2"},
             "DIAGNOSIS_EVIDENCE_TASK_MISMATCH"),
            ("artifact_hash", {"evidence_hash": "sha256:other"},
             "DIAGNOSIS_EVIDENCE_ARTIFACT_MISMATCH"),
            ("invalid", {"evidence_valid": False}, "DIAGNOSIS_EVIDENCE_INVALID"),
            ("invalidated", {"invalidated": True}, "DIAGNOSIS_EVIDENCE_INVALID"),
            ("worker", {"evidence_producer": "worker-1"}, "DIAGNOSIS_EVIDENCE_INVALID"),
        )
        for label, kwargs, code in cases:
            with self.subTest(label=label):
                self.store.reset_for_test()
                self.engine = DiagnosisEngine(self.store)
                fixture = self.create_fixture(label, **kwargs)
                with self.assertRaisesRegex(CommandRejected, code):
                    self.engine.run(self.command(fixture, label))

    def test_idempotent_retry_returns_same_diagnosis_and_conflict_is_stable(self):
        fixture = self.create_fixture("idem")
        first = self.engine.run(self.command(fixture, "idem"))
        second = self.engine.run(self.command(fixture, "idem"))
        self.assertEqual(first["diagnosis_id"], second["diagnosis_id"])
        with self.assertRaisesRegex(CommandRejected, "DIAGNOSIS_IDEMPOTENCY_CONFLICT"):
            self.engine.run(self.command(
                fixture, "idem-conflict",
                command_id="cmd-diagnosis-idem-other",
                idempotency_key="key-diagnosis-idem",
                analysis_context_hash="sha256:" + "1" * 64,
            ))

    def test_concurrent_same_input_creates_one_equivalent_diagnosis(self):
        fixture = self.create_fixture("concurrent")
        barrier = threading.Barrier(2)
        results = []
        failures = []

        def run(index):
            try:
                barrier.wait()
                results.append(DiagnosisEngine(PostgresDiagnosisStore(
                    DATABASE_URL
                )).run(self.command(fixture, "concurrent-" + str(index))))
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0]["diagnosis_id"], results[1]["diagnosis_id"])
        with psycopg.connect(DATABASE_URL) as connection:
            self.assertEqual(
                1, connection.execute("SELECT count(*) FROM diagnoses").fetchone()[0]
            )

    def test_fault_injection_rolls_back_before_commit_and_commit_ack_is_idempotent(self):
        for point in DiagnosisFaultPoint:
            with self.subTest(point=point.value):
                self.store.reset_for_test()
                self.engine = DiagnosisEngine(self.store)
                fixture = self.create_fixture("fault-" + point.value[:8])
                before = self.counts()
                self.store.fail_diagnosis_once(point)
                with self.assertRaises(RuntimeError):
                    self.engine.run(self.command(fixture, "fault-" + point.value[:8]))
                self.assertEqual(before, self.counts())
        self.store.reset_for_test()
        self.engine = DiagnosisEngine(self.store)
        fixture = self.create_fixture("ack")
        result = self.engine.run(self.command(fixture, "ack"))
        retry = self.engine.run(self.command(fixture, "ack"))
        self.assertEqual(result["diagnosis_id"], retry["diagnosis_id"])

    def test_diagnosis_is_immutable_and_does_not_modify_situation_or_task(self):
        fixture = self.create_fixture("immutable")
        with psycopg.connect(DATABASE_URL) as connection:
            before = connection.execute(
                """SELECT s.version,s.status,t.state,t.version
                   FROM situations s JOIN tasks t ON t.task_id=s.task_id
                   WHERE s.situation_id=%s""",
                (fixture["situation_id"],),
            ).fetchone()
        result = self.engine.run(self.command(fixture, "immutable"))
        with psycopg.connect(DATABASE_URL) as connection:
            after = connection.execute(
                """SELECT s.version,s.status,t.state,t.version
                   FROM situations s JOIN tasks t ON t.task_id=s.task_id
                   WHERE s.situation_id=%s""",
                (fixture["situation_id"],),
            ).fetchone()
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "UPDATE diagnoses SET confidence_basis_points=1 WHERE diagnosis_id=%s",
                    (result["diagnosis_id"],),
                )
        self.assertEqual(before, after)

    def test_new_situation_version_produces_new_diagnosis(self):
        fixture = self.create_fixture("newversion")
        first = self.engine.run(self.command(fixture, "newversion-1"))
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """UPDATE situations SET version=version+1
                   WHERE situation_id=%s""", (fixture["situation_id"],)
            )
            version = connection.execute(
                "SELECT version FROM situations WHERE situation_id=%s",
                (fixture["situation_id"],),
            ).fetchone()[0]
        fixture["version"] = version
        second = self.engine.run(self.command(fixture, "newversion-2"))
        self.assertNotEqual(first["diagnosis_id"], second["diagnosis_id"])


if __name__ == "__main__":
    unittest.main()
