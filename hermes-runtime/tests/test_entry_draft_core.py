import os
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.entry_draft_api import UnavailableEntryDraftApi
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.entry_draft import EntryDraftRejected
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore

DATABASE_URL = os.environ.get("HERMES_TEST_DATABASE_URL")


class EmptyReadModel:
    def project_status(self, *_args): return {"availability": "NOT_AVAILABLE", "item": None}
    def decision_explain(self, *_args): return {"availability": "NOT_AVAILABLE", "item": None}
    def human_gate_request(self, *_args): return {"availability": "NOT_AVAILABLE", "item": None}
    def replay_reconcile_findings(self, *_args): return {"availability": "NOT_AVAILABLE", "items": []}
    def docker_process_observations(self, *_args): return {"availability": "NOT_AVAILABLE", "items": []}


class RejectingGateway:
    def submit_human_gate_decision(self, _payload): raise AssertionError("not used")


@unittest.skipUnless(DATABASE_URL and psycopg, "requires psycopg and HERMES_TEST_DATABASE_URL")
class EntryDraftCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_store = PostgresProjectStore(DATABASE_URL)
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            project_store.apply_migration(migration)
        cls.store = PostgresEntryDraftStore(DATABASE_URL)

    def setUp(self):
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("TRUNCATE public.entry_drafts, public.entry_draft_command_receipts CASCADE")
        self.alice = "oidc-alice"
        self.bob = "oidc-bob"

    def create(self, subject=None, key="create-1", title="Draft title", idea="Build an auditable system"):
        return self.store.create(subject or self.alice, title=title, raw_input=idea, idempotency_key=key, reason="test create")

    def test_create_read_and_creator_scope(self):
        created = self.create()
        self.assertEqual("DRAFT", created["state"])
        self.assertEqual(1, created["version"])
        self.assertEqual(1, created["latest_revision"])
        self.assertEqual(1, len(created["revisions"]))
        self.assertEqual([created["draft_id"]], [row["draft_id"] for row in self.store.list(self.alice)["items"]])
        hidden = self.store.get(self.bob, created["draft_id"])
        self.assertEqual("NOT_AVAILABLE", hidden["availability"])
        self.assertIsNone(hidden["item"])

    def test_revision_is_append_only_and_increments_version(self):
        created = self.create()
        revised = self.store.revise(self.alice, created["draft_id"], title="Revised", raw_input="Revised idea", expected_version=1, idempotency_key="rev-1", reason="clarify draft")
        self.assertEqual(2, revised["version"])
        self.assertEqual(2, revised["latest_revision"])
        self.assertEqual("Draft title", revised["revisions"][0]["title"])
        self.assertEqual("Revised", revised["revisions"][1]["title"])
        with self.assertRaises(Exception):
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute("UPDATE public.entry_draft_revisions SET title='tampered' WHERE draft_id=%s AND revision_number=1", (created["draft_id"],))

    def test_version_conflict_idempotency_replay_and_conflict(self):
        created = self.create(key="create-replay")
        replay = self.create(key="create-replay")
        self.assertEqual(created["draft_id"], replay["draft_id"])
        with self.assertRaisesRegex(EntryDraftRejected, "ENTRY_DRAFT_IDEMPOTENCY_CONFLICT"):
            self.create(key="create-replay", title="Changed")
        with self.assertRaisesRegex(EntryDraftRejected, "ENTRY_DRAFT_VERSION_CONFLICT"):
            self.store.revise(self.alice, created["draft_id"], title="Nope", raw_input="Nope", expected_version=2, idempotency_key="stale", reason="stale")

    def test_lifecycle_and_archived_mutation_rejection(self):
        created = self.create()
        submitted = self.store.submit(self.alice, created["draft_id"], expected_version=1, idempotency_key="submit", reason="ready for later understanding")
        self.assertEqual("SUBMITTED", submitted["state"])
        archived = self.store.archive(self.alice, created["draft_id"], expected_version=2, idempotency_key="archive", reason="creator archived")
        self.assertEqual("ARCHIVED", archived["state"])
        with self.assertRaisesRegex(EntryDraftRejected, "ENTRY_DRAFT_TRANSITION_FORBIDDEN"):
            self.store.submit(self.alice, created["draft_id"], expected_version=3, idempotency_key="invalid", reason="not allowed")
        with self.assertRaisesRegex(EntryDraftRejected, "ENTRY_DRAFT_TRANSITION_FORBIDDEN"):
            self.store.revise(self.alice, created["draft_id"], title="No", raw_input="No", expected_version=3, idempotency_key="archived-revise", reason="not allowed")

    def test_product_api_routes_are_creator_scoped_and_semantic(self):
        facade = ProductApiFacade(EmptyReadModel(), RejectingGateway(), entry_draft_api=self.store)
        actor = Actor(ActorType.USER, self.alice)
        create = facade.handle(ProductApiRequest("POST", "/production-drafts", {"Idempotency-Key": "api-create"}, {"title": "API draft", "raw_input": "Build via API", "reason": "api create"}, actor, verified_identity_subject=self.alice))
        item = create.body["item"]
        self.assertEqual(201, create.status_code)
        listed = facade.handle(ProductApiRequest("GET", "/production-drafts", {}, {}, actor, verified_identity_subject=self.alice))
        self.assertEqual([item["draft_id"]], [row["draft_id"] for row in listed.body["items"]])
        bob = Actor(ActorType.USER, self.bob)
        hidden = facade.handle(ProductApiRequest("GET", f"/production-drafts/{item['draft_id']}", {}, {}, bob, verified_identity_subject=self.bob))
        self.assertEqual("NOT_AVAILABLE", hidden.body["availability"])
        self.assertIsNone(hidden.body["item"])

    def test_product_api_requires_verified_identity_and_no_global_draft_read(self):
        facade = ProductApiFacade(EmptyReadModel(), RejectingGateway(), entry_draft_api=self.store)
        actor = Actor(ActorType.USER, self.alice)
        with self.assertRaisesRegex(Exception, "ENTRY_DRAFT_IDENTITY_REQUIRED"):
            facade.handle(ProductApiRequest("GET", "/production-drafts", {}, {}, actor))
        with self.assertRaisesRegex(Exception, "ENTRY_DRAFT_IDENTITY_REQUIRED"):
            facade.handle(ProductApiRequest("GET", "/factory-home/drafts", {}, {}, actor))


if __name__ == "__main__":
    unittest.main()
