import os
import unittest
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

from hermes_runtime.application.human_gate_product import HumanGateProductFacade
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.human_gates import HumanGateAuthority
from hermes_runtime.application.user_human_gate_transport import UserHumanGateRejected, UserHumanGateTransport
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.infrastructure.postgres_factory_home_read_model import PostgresCreatorActorProjectScope
from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider
from tests import test_human_gate_postgres as human_gate_fixture

DATABASE_URL = os.environ.get('HERMES_TEST_DATABASE_URL')


@unittest.skipUnless(DATABASE_URL and psycopg, 'requires explicit PostgreSQL')
class E12HumanGateTransportPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresHumanGateStore(DATABASE_URL)
        cls.store.check_server_version(140000)
        for migration in sorted((Path(__file__).parents[1] / 'migrations').glob('*.sql')):
            cls.store.apply_migration(migration)

    def setUp(self):
        self.store.reset_for_test()
        self.approver = Actor(ActorType.USER, 'e12-approver')
        self.fixture = human_gate_fixture.HumanGatePostgresTests()
        self.fixture.store = self.store
        self.fixture.authority = HumanGateAuthority(self.store)
        self.fixture.main = Actor(ActorType.MAIN_HERMES, 'main-hermes')
        self.fixture.user = self.approver
        self.fixture._seed_project()
        with psycopg.connect(DATABASE_URL) as connection:
            command_id = connection.execute("SELECT last_command_id FROM public.projects WHERE project_id='project-1'").fetchone()[0]
            connection.execute("""INSERT INTO public.project_transition_records(
                transition_id, project_id, command_id, previous_state, new_state, project_version,
                actor_type, actor_id, requested_by_type, requested_by_id, reason
            ) VALUES (%s,'project-1',%s,NULL,'IMPLEMENTING',7,'control_plane','fixture','user',%s,'creator scope fixture')""", (f'e12-scope-{uuid.uuid4().hex}', command_id, self.approver.actor_id))
        self.fixture._seed_policy_require_human('project-1', 7)
        self.fixture._request()
        self.store.seed_human_authorization('assert-e12', self.approver.actor_id, 'project-1', 'gate-1', 'project:resume')
        self.transport = UserHumanGateTransport(
            self.store, PostgresCreatorActorProjectScope(DATABASE_URL),
            HumanGateProductFacade(self.store, HumanGateAuthority(self.store), self.store),
        )

    def _counts(self):
        with psycopg.connect(DATABASE_URL) as connection:
            return tuple(connection.execute(f"SELECT count(*) FROM public.{table}").fetchone()[0] for table in ('command_receipts', 'human_gate_decisions', 'event_log', 'outbox_messages'))

    def _submit(self, command_id='e12-command-1', decision_id='e12-decision-1', key='e12-idem-1', reason='approved after human review'):
        return self.transport.submit(gate_request_id='gate-1', verified_identity_subject=self.approver.actor_id, actor=self.approver, command_id=command_id, gate_decision_id=decision_id, idempotency_key=key, expected_gate_version=1, decision='APPROVE', reason=reason)

    def test_creator_scoped_list_submit_receipt_event_and_outbox(self):
        listed = self.transport.list(verified_identity_subject=self.approver.actor_id, actor=self.approver)
        self.assertEqual(('gate-1',), tuple(item['gate_id'] for item in listed))
        result = self._submit()
        self.assertEqual('APPLIED', result['receipt_status'])
        self.assertEqual('HUMAN_GATE_APPROVED', result['result_code'])
        self.assertEqual('GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME', result['completion_claim'])
        with psycopg.connect(DATABASE_URL) as connection:
            decision = connection.execute("SELECT approver_type, approver_id, authorization_ref, assertion_id, event_id FROM public.human_gate_decisions WHERE gate_decision_id='e12-decision-1'").fetchone()
            receipt = connection.execute("SELECT status, result->>'result_code', (result->>'target_version')::bigint FROM public.command_receipts WHERE command_id='e12-command-1'").fetchone()
            event_count = connection.execute("SELECT count(*) FROM public.event_log WHERE command_id='e12-command-1' AND event_type='human_gate.approved'").fetchone()[0]
            outbox_count = connection.execute("SELECT count(*) FROM public.outbox_messages WHERE event_id=%s", (decision[4],)).fetchone()[0]
        self.assertEqual(('user', 'e12-approver', 'oidc-session:test-only:assert-e12', 'assert-e12'), tuple(decision[:4]))
        self.assertEqual(('APPLIED', 'HUMAN_GATE_APPROVED', 2), tuple(receipt))
        self.assertEqual(1, event_count); self.assertEqual(1, outbox_count)
        self.assertEqual((), self.transport.list(verified_identity_subject=self.approver.actor_id, actor=self.approver))

    def test_stale_gate_version_fails_closed_without_new_event(self):
        before = self.store.count('event_log')
        with self.assertRaisesRegex(UserHumanGateRejected, 'GATE_VERSION_CONFLICT'):
            self.transport.submit(gate_request_id='gate-1', verified_identity_subject=self.approver.actor_id, actor=self.approver, command_id='e12-stale-command', gate_decision_id='e12-stale-decision', idempotency_key='e12-stale-idem', expected_gate_version=99, decision='APPROVE', reason='stale version')
        self.assertEqual(before, self.store.count('event_log'))

    def test_same_key_replays_and_different_payload_conflicts_without_new_event(self):
        before = self.store.count('event_log')
        first = self._submit()
        after = self.store.count('event_log')
        replay = self._submit()
        self.assertEqual(first['gate_decision_id'], replay['gate_decision_id'])
        self.assertEqual(after, self.store.count('event_log'))
        with self.assertRaisesRegex(UserHumanGateRejected, 'IDEMPOTENCY_PAYLOAD_CONFLICT'):
            self._submit(reason='different reason')
        self.assertEqual(after, self.store.count('event_log'))
        self.assertEqual(before + 1, after)

    def test_verified_http_session_uses_real_postgres_gate_transport(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private.public_key()))
        jwk.update({'kid': 'e12-pg', 'alg': 'RS256'})
        verifier = OidcTokenVerifier(
            OidcConfig(issuer='https://e12-pg.proteus.invalid', audience='proteus-test', production_profile=False, allow_local_test_issuer=True),
            StaticJwksProvider({'keys': [jwk]}),
        )
        now = int(time.time())
        token = jwt.encode({'iss': 'https://e12-pg.proteus.invalid', 'aud': 'proteus-test', 'sub': self.approver.actor_id, 'exp': now + 300, 'nbf': now - 1}, private, algorithm='RS256', headers={'kid': 'e12-pg'})
        client = TestClient(create_app(ProductApiFacade(type('Read', (), {})(), type('Gateway', (), {})(), user_human_gate_transport=self.transport), oidc_verifier=verifier, session_cookie_secure=False))
        self.assertEqual(201, client.post('/session', headers={'Authorization': f'Bearer {token}'}).status_code)
        listed = client.get('/factory-home/gates')
        self.assertEqual(200, listed.status_code)
        self.assertEqual('gate-1', listed.json()['data']['items'][0]['gate_id'])
        body = {'command_id': 'e12-http-command', 'gate_decision_id': 'e12-http-decision', 'idempotency_key': 'e12-http-idem', 'expected_gate_version': 1, 'decision': 'APPROVE', 'reason': 'approved through verified session'}
        response = client.post('/factory-home/gates/gate-1/decisions', json=body)
        self.assertEqual(202, response.status_code)
        self.assertEqual('HUMAN_GATE_APPROVED', response.json()['data']['result_code'])
        forged = client.post('/factory-home/gates/gate-1/decisions', json=body | {'actor': {'type': 'user', 'id': 'forged'}})
        self.assertEqual(422, forged.status_code)
        self.assertEqual('E12_GATE_CLIENT_AUTHORITY_FIELD_FORBIDDEN', forged.json()['error']['code'])

    def test_foreign_scope_discloses_nothing_and_writes_nothing(self):
        foreign = Actor(ActorType.USER, 'e12-foreign')
        before = self._counts()
        self.assertEqual((), self.transport.list(verified_identity_subject=foreign.actor_id, actor=foreign))
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_NOT_AVAILABLE'):
            self.transport.submit(gate_request_id='gate-1', verified_identity_subject=foreign.actor_id, actor=foreign, command_id='foreign-cmd', gate_decision_id='foreign-decision', idempotency_key='foreign-idem', expected_gate_version=1, decision='APPROVE', reason='foreign')
        self.assertEqual(before, self._counts())


if __name__ == '__main__':
    unittest.main()
