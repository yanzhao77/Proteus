import json
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import algorithms

from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.application.user_human_gate_transport import UserHumanGateRejected
from hermes_runtime.infrastructure.fastapi_app import create_app
from hermes_runtime.infrastructure.oidc import OidcConfig, OidcTokenVerifier, StaticJwksProvider


class _ReadModel: pass
class _Gateway: pass
class _Transport:
    def __init__(self): self.calls = []
    def list(self, **kwargs):
        self.calls.append(('list', kwargs)); return ({'availability': 'CURRENT', 'gate_id': 'gate-1', 'project_id': 'project-1', 'production_name': 'Project', 'action': 'project:resume', 'request_type': 'approval', 'risk_ref': 'risk-1', 'reason': 'Review required', 'evidence_refs': ['evidence-1'], 'evidence_count': 1, 'expires_at': '2099-01-01T00:00:00Z', 'status': 'REQUESTED', 'version': 3, 'as_of': '2026-08-27T00:00:00Z', 'freshness': 'NOT_AVAILABLE', 'audit': ()},)
    def detail(self, **kwargs):
        self.calls.append(('detail', kwargs)); return self.list(**kwargs)[0]
    def submit(self, **kwargs):
        self.calls.append(('submit', kwargs))
        if kwargs['gate_request_id'] == 'foreign': raise UserHumanGateRejected('E12_GATE_NOT_AVAILABLE')
        return {'availability': 'CURRENT', 'command_id': kwargs['command_id'], 'gate_request_id': kwargs['gate_request_id'], 'gate_decision_id': kwargs['gate_decision_id'], 'receipt_status': 'APPLIED', 'result_code': 'HUMAN_GATE_APPROVED', 'request_state': 'APPROVED', 'request_version': 4, 'decision': kwargs['decision'], 'event_ids': ['event-1'], 'completion_claim': 'GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME'}


def _issuer():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(algorithms.RSAAlgorithm.to_jwk(private.public_key())); jwk.update({'kid': 'e12-test', 'alg': 'RS256'})
    verifier = OidcTokenVerifier(OidcConfig(issuer='https://e12-issuer.proteus.invalid', audience='proteus-test', production_profile=False, allow_local_test_issuer=True), StaticJwksProvider({'keys': [jwk]}))
    now = int(time.time())
    token = jwt.encode({'iss': 'https://e12-issuer.proteus.invalid', 'aud': 'proteus-test', 'sub': 'approver-1', 'exp': now + 300, 'nbf': now - 1}, private, algorithm='RS256', headers={'kid': 'e12-test'})
    return verifier, token


class E12FastApiTransportTests(unittest.TestCase):
    def setUp(self):
        verifier, token = _issuer(); self.transport = _Transport()
        self.client = TestClient(create_app(ProductApiFacade(_ReadModel(), _Gateway(), user_human_gate_transport=self.transport), oidc_verifier=verifier, session_cookie_secure=False))
        self.assertEqual(201, self.client.post('/session', headers={'Authorization': f'Bearer {token}'}).status_code)
    def _body(self):
        return {'command_id': 'cmd-1', 'gate_decision_id': 'decision-1', 'idempotency_key': 'idem-1', 'expected_gate_version': 3, 'decision': 'APPROVE', 'reason': 'approved after evidence review'}
    def test_verified_session_lists_details_and_submits_without_client_authority(self):
        listed = self.client.get('/factory-home/gates'); self.assertEqual(200, listed.status_code); self.assertEqual('gate-1', listed.json()['data']['items'][0]['gate_id'])
        detail = self.client.get('/factory-home/gates/gate-1'); self.assertEqual(200, detail.status_code)
        response = self.client.post('/factory-home/gates/gate-1/decisions', json=self._body()); self.assertEqual(202, response.status_code)
        data = response.json()['data']; self.assertEqual('GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME', data['completion_claim'])
        call = [payload for kind, payload in self.transport.calls if kind == 'submit'][0]
        self.assertEqual('approver-1', call['verified_identity_subject']); self.assertEqual('approver-1', call['actor'].actor_id)
        self.assertNotIn('actor', self._body())
    def test_forged_authority_and_session_actor_mismatch_fail_closed(self):
        forged = self.client.post('/factory-home/gates/gate-1/decisions', json=self._body() | {'actor': {'type': 'user', 'id': 'forged'}})
        self.assertEqual(422, forged.status_code); self.assertEqual('E12_GATE_CLIENT_AUTHORITY_FIELD_FORBIDDEN', forged.json()['error']['code'])
        mismatch = self.client.get('/factory-home/gates', headers={'X-Hermes-Actor-ID': 'forged'})
        self.assertEqual(401, mismatch.status_code); self.assertEqual('FACTORY_HOME_ACTOR_MISMATCH', mismatch.json()['error']['code'])
    def test_foreign_gate_is_not_disclosed(self):
        response = self.client.post('/factory-home/gates/foreign/decisions', json=self._body())
        self.assertEqual(404, response.status_code); self.assertEqual('E12_GATE_NOT_AVAILABLE', response.json()['error']['code'])


if __name__ == '__main__': unittest.main()
