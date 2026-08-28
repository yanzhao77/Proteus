import unittest

from hermes_runtime.application.user_human_gate_transport import UserHumanGateRejected, UserHumanGateTransport
from hermes_runtime.domain.human_gate import AuthorizationAssertion
from hermes_runtime.domain.models import Actor, ActorType


class Scope:
    def project_ids_for(self, actor_scope):
        return ('project-1',) if actor_scope.get('identity_subject') in {'alice', 'bob'} else ()


class Reader:
    def __init__(self):
        self.rows = []
        self.gate = {
            'gate_request_id': 'gate-1', 'project_id': 'project-1', 'production_name': 'Safe Project',
            'task_id': None, 'action_scope': 'project:resume', 'request_type': 'approval',
            'requester_type': 'main_hermes', 'requester_id': 'main', 'risk_assessment_id': 'risk-1',
            'supporting_evidence_refs': ('evidence-1',), 'evidence_count': 1, 'reason': 'Authorized decision required',
            'expires_at': '2099-01-01T00:00:00+00:00', 'request_state': 'REQUESTED', 'version': 3,
            'updated_at': '2026-08-27T00:00:00+00:00', 'decisions': (),
        }
        self.assertion = AuthorizationAssertion('assert-1', 'test-issuer', 'alice', 'approver', 'project-1', None, 'gate-1', 'project:resume', '2026-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00', 'sha256:assertion')
    def list_gate_requests(self, project_ids):
        self.rows.append(tuple(project_ids)); return (self.gate,)
    def get_gate_request(self, gate_request_id, project_ids):
        self.rows.append(tuple(project_ids)); return self.gate if gate_request_id == 'gate-1' and 'project-1' in project_ids else None
    def get_active_approver_assertion(self, gate_request_id, project_ids, subject):
        return self.assertion if gate_request_id == 'gate-1' and subject == 'alice' and 'project-1' in project_ids else None
    def current_time(self):
        return '2026-08-27T00:00:00+00:00'


class Facade:
    def __init__(self): self.requests = []
    def submit_decision(self, request):
        self.requests.append(request)
        return {'command_id': request.command_id, 'gate_request_id': request.gate_request_id, 'gate_decision_id': request.gate_decision_id, 'result_code': 'HUMAN_GATE_APPROVED', 'request_state': 'APPROVED', 'request_version': 4, 'decision': request.decision.value, 'event_ids': ['event-1']}


class UserHumanGateTransportTests(unittest.TestCase):
    def setUp(self):
        self.reader = Reader(); self.facade = Facade(); self.transport = UserHumanGateTransport(self.reader, Scope(), self.facade)
        self.actor = Actor(ActorType.USER, 'alice')

    def test_creator_scoped_list_and_safe_detail(self):
        rows = self.transport.list(verified_identity_subject='alice', actor=self.actor)
        detail = self.transport.detail(gate_request_id='gate-1', verified_identity_subject='alice', actor=self.actor)
        self.assertEqual(('project-1',), self.reader.rows[0])
        self.assertEqual('gate-1', rows[0]['gate_id'])
        self.assertEqual(('evidence-1',), tuple(detail['evidence_refs']))
        self.assertNotIn('assertion_hash', detail)
        self.assertNotIn('authorization_ref', detail)

    def test_submit_derives_approver_assertion_and_authorization_ref(self):
        receipt = self.transport.submit(gate_request_id='gate-1', verified_identity_subject='alice', actor=self.actor, command_id='command-1', gate_decision_id='decision-1', idempotency_key='idem-1', expected_gate_version=3, decision='APPROVE', reason='reviewed evidence')
        request = self.facade.requests[0]
        self.assertEqual(Actor(ActorType.USER, 'alice'), request.approver)
        self.assertEqual(Actor(ActorType.MAIN_HERMES, 'main'), request.requester)
        self.assertEqual('oidc-session:test-issuer:assert-1', request.authorization_ref)
        self.assertEqual('assert-1', request.assertion.assertion_id)
        self.assertEqual('HUMAN_GATE_APPROVED', receipt['result_code'])
        self.assertEqual('GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME', receipt['completion_claim'])

    def test_identity_scope_action_and_metadata_fail_closed(self):
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_IDENTITY_REQUIRED'):
            self.transport.list(verified_identity_subject='alice', actor=Actor(ActorType.USER, 'mallory'))
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_NOT_AVAILABLE'):
            self.transport.detail(gate_request_id='foreign', verified_identity_subject='alice', actor=self.actor)
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_DECISION_FORBIDDEN'):
            self.transport.submit(gate_request_id='gate-1', verified_identity_subject='alice', actor=self.actor, command_id='c', gate_decision_id='d', idempotency_key='i', expected_gate_version=3, decision='CANCEL', reason='x')
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_DECISION_REASON_REQUIRED'):
            self.transport.submit(gate_request_id='gate-1', verified_identity_subject='alice', actor=self.actor, command_id='c', gate_decision_id='d', idempotency_key='i', expected_gate_version=3, decision='APPROVE', reason=' ')

    def test_scope_unavailable_fails_closed(self):
        class UnavailableScope:
            def project_ids_for(self, _scope): return None
        transport = UserHumanGateTransport(self.reader, UnavailableScope(), self.facade)
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_SCOPE_UNAVAILABLE'):
            transport.list(verified_identity_subject='alice', actor=self.actor)

    def test_approver_assertion_is_required(self):
        with self.assertRaisesRegex(UserHumanGateRejected, 'E12_GATE_APPROVER_NOT_AUTHORIZED'):
            self.transport.submit(gate_request_id='gate-1', verified_identity_subject='bob', actor=Actor(ActorType.USER, 'bob'), command_id='c', gate_decision_id='d', idempotency_key='i', expected_gate_version=3, decision='APPROVE', reason='x')


if __name__ == '__main__':
    unittest.main()
