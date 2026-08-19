import json
import os
import unittest
from pathlib import Path
try:
    import psycopg
except ImportError:
    psycopg = None
from hermes_runtime.application.entry_draft_api import UnavailableEntryDraftApi
from hermes_runtime.application.product_api import ProductApiFacade
from hermes_runtime.domain.entry_understanding import EntryUnderstandingRejected
from hermes_runtime.domain.understanding_producer import ProducerError, UnderstandingCandidate, ProducedUnderstanding, ProducerProvenance, ProviderUsage
from hermes_runtime.domain.models import Actor, ActorType
from hermes_runtime.domain.product_api import ProductApiRequest
from hermes_runtime.infrastructure.postgres_project import PostgresProjectStore
from hermes_runtime.infrastructure.postgres_entry_draft import PostgresEntryDraftStore
from hermes_runtime.infrastructure.postgres_entry_understanding import PostgresEntryUnderstandingStore

DATABASE_URL=os.environ.get('HERMES_TEST_DATABASE_URL')
class Producer:
    def __init__(self, outputs=None, error=None): self.outputs=list(outputs or []); self.error=error; self.calls=[]
    def generate(self, request):
        self.calls.append(request)
        if self.error: raise self.error
        raw=self.outputs.pop(0)
        if not isinstance(raw, dict) or 'interpreted_intent' not in raw: return raw
        candidate=UnderstandingCandidate(raw['interpreted_intent'], [raw['objective']] if raw.get('objective') else [], raw.get('explicit_requirements', []), raw.get('open_questions', []), [row['statement'] for row in raw.get('assumptions', [])], raw.get('ambiguities', []), [row['question'] for row in raw.get('clarifications', [])])
        provenance=ProducerProvenance('test-understanding-producer','test-provider','test-model',None,'test-request',request.correlation_id,request.prompt_version,request.schema_version,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00',100,0,ProviderUsage(None,None,None))
        return ProducedUnderstanding(candidate,provenance)
class EmptyReadModel:
    def project_status(self,*a): return {'availability':'NOT_AVAILABLE','item':None}
    def decision_explain(self,*a): return {'availability':'NOT_AVAILABLE','item':None}
    def human_gate_request(self,*a): return {'availability':'NOT_AVAILABLE','item':None}
    def replay_reconcile_findings(self,*a): return {'availability':'NOT_AVAILABLE','items':[]}
    def docker_process_observations(self,*a): return {'availability':'NOT_AVAILABLE','items':[]}
class Gateway:
    def submit_human_gate_decision(self,p): raise AssertionError('not used')
def output(intent='Build a chat application', clarifications=None, assumptions=None, requirements=None):
    return {'interpreted_intent':intent,'objective':'Enable real-time communication','user_constraints':['simple first release'],'explicit_requirements':requirements or ['chat messages'],'ambiguities':['target platform is unspecified'],'open_questions':['Which platform should ship first?'] if clarifications else [],'assumptions':assumptions or [],'clarifications':clarifications or [],'confidence':None,'provider_metadata':None}

@unittest.skipUnless(DATABASE_URL and psycopg,'requires psycopg and HERMES_TEST_DATABASE_URL')
class EntryUnderstandingCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ps=PostgresProjectStore(DATABASE_URL)
        for migration in sorted((Path(__file__).parents[1]/'migrations').glob('*.sql')): ps.apply_migration(migration)
    def setUp(self):
        with psycopg.connect(DATABASE_URL) as c:
            c.execute('TRUNCATE public.entry_understandings, public.entry_understanding_command_receipts, public.entry_drafts, public.entry_draft_command_receipts CASCADE')
        self.alice='oidc-alice'; self.bob='oidc-bob'
        self.drafts=PostgresEntryDraftStore(DATABASE_URL)
        created=self.drafts.create(self.alice, title='Chat product', raw_input='Build a chat app with chat messages', idempotency_key='draft-create', reason='test')
        self.draft_id=created['draft_id']
        self.drafts.submit(self.alice, self.draft_id, expected_version=1, idempotency_key='draft-submit', reason='ready for understanding')
    def store(self, producer): return PostgresEntryUnderstandingStore(DATABASE_URL,producer)
    def test_generation_persists_traceable_revision_assumptions_and_clarification(self):
        p=Producer([output(clarifications=[{'question':'Which platform?','rationale':'platform changes intent'}],assumptions=[{'statement':'Web is the initial target','basis':None}],requirements=['chat messages'])])
        item=self.store(p).generate(self.alice,self.draft_id,0,'gen-1','understand')
        self.assertEqual('NEEDS_CLARIFICATION',item['state']); self.assertEqual(1,item['version']); self.assertEqual(self.draft_id,item['current']['source_draft_id']); self.assertEqual(1,item['current']['source_draft_revision_number'])
        self.assertEqual(['chat messages'],item['current']['explicit_requirements']); self.assertEqual('Web is the initial target',item['assumptions'][0]['statement']); self.assertEqual(None,item['current']['confidence']); self.assertEqual('test-provider',item['current']['provider_metadata']['provider']); self.assertEqual(1,len(item['clarifications']))
    def test_generation_failure_and_schema_failure_persist_no_understanding(self):
        with self.assertRaisesRegex(EntryUnderstandingRejected,'ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED'):
            self.store(Producer(error=RuntimeError('timeout'))).generate(self.alice,self.draft_id,0,'fail-1','understand')
        with self.assertRaisesRegex(EntryUnderstandingRejected,'ENTRY_UNDERSTANDING_SCHEMA_INVALID'):
            self.store(Producer([{'unknown':'forbidden'}])).generate(self.alice,self.draft_id,0,'bad-schema','understand')
        self.assertEqual('NOT_AVAILABLE',self.store(Producer([])).get(self.alice,self.draft_id)['availability'])
    def test_creator_isolation_and_archived_or_unsubmitted_draft_rejection(self):
        store=self.store(Producer([output()]))
        with self.assertRaisesRegex(EntryUnderstandingRejected,'ENTRY_DRAFT_NOT_AVAILABLE'):
            store.generate(self.bob,self.draft_id,0,'foreign','understand')
        created=self.drafts.create(self.alice, title='Unsubmitted', raw_input='raw', idempotency_key='unsubmitted', reason='test')
        with self.assertRaisesRegex(EntryUnderstandingRejected,'E2_UNDERSTANDING_DRAFT_NOT_SUBMITTED'):
            store.generate(self.alice,created['draft_id'],0,'not-submitted','understand')
        self.drafts.archive(self.alice, self.draft_id, expected_version=2, idempotency_key='archive', reason='archive source')
        with self.assertRaisesRegex(EntryUnderstandingRejected,'E2_UNDERSTANDING_DRAFT_NOT_SUBMITTED'):
            store.generate(self.alice,self.draft_id,0,'archived-source','understand')
    def test_answer_creates_new_understanding_revision_and_requires_open_clarification(self):
        p=Producer([output(clarifications=[{'question':'Which platform?','rationale':None}]), output(intent='Build a web chat application',clarifications=[],assumptions=[{'statement':'Web target','basis':'clarification answer'}])])
        store=self.store(p); first=store.generate(self.alice,self.draft_id,0,'gen','understand'); cid=first['clarifications'][0]['clarification_id']
        second=store.answer_clarification(self.alice,self.draft_id,cid,'Web',1,'answer','answer clarification')
        self.assertEqual('READY',second['state']); self.assertEqual(2,second['version']); self.assertEqual(2,len(second['revisions'])); self.assertEqual('ANSWERED',second['clarifications'][0]['state']); self.assertEqual('Web',second['clarifications'][0]['answer'])
        with self.assertRaisesRegex(EntryUnderstandingRejected,'E2_CLARIFICATION_NOT_OPEN'):
            store.answer_clarification(self.alice,self.draft_id,cid,'Again',2,'answer-again','bad')
    def test_idempotency_and_stale_version(self):
        p=Producer([output()]); store=self.store(p); first=store.generate(self.alice,self.draft_id,0,'same','understand'); replay=store.generate(self.alice,self.draft_id,0,'same','understand')
        self.assertEqual(first['understanding_id'],replay['understanding_id']); self.assertEqual(1,len(p.calls))
        with self.assertRaisesRegex(EntryUnderstandingRejected,'E2_UNDERSTANDING_IDEMPOTENCY_CONFLICT'):
            store.generate(self.alice,self.draft_id,1,'same','different')
        with self.assertRaisesRegex(EntryUnderstandingRejected,'E2_UNDERSTANDING_VERSION_CONFLICT'):
            self.store(Producer([output(intent='new')])).generate(self.alice,self.draft_id,0,'stale','understand')


    def test_classified_provider_error_is_durable_and_replayed_without_second_call(self):
        class ClassifiedProducer:
            def __init__(self): self.calls=0
            def generate(self,request): self.calls+=1; raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT")
        producer=ClassifiedProducer(); store=self.store(producer)
        with self.assertRaisesRegex(EntryUnderstandingRejected,"ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT"):
            store.generate(self.alice,self.draft_id,0,'classified-timeout','understand')
        with self.assertRaisesRegex(EntryUnderstandingRejected,"ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT"):
            store.generate(self.alice,self.draft_id,0,'classified-timeout','understand')
        self.assertEqual(1,producer.calls)
        with psycopg.connect(DATABASE_URL) as c:
            receipt=c.execute("SELECT status,result->>'error_code' FROM public.entry_understanding_command_receipts WHERE idempotency_key=%s",('classified-timeout',)).fetchone()
        self.assertEqual(('REJECTED','ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT'),tuple(receipt))

    def test_e2x_provider_candidate_persists_first_class_provenance(self):
        from hermes_runtime.infrastructure.openai_compatible_understanding_provider import UnderstandingProviderConfig, OpenAICompatibleUnderstandingProvider
        class Transport:
            def __init__(self): self.calls=[]
            def post(self,url,headers,payload,timeout_seconds):
                self.calls.append((url,headers,payload,timeout_seconds))
                response={"id":"provider-request-1","choices":[{"message":{"content":json.dumps({"goal":"Build a chat app","objectives":["Support chat"],"requirements":["chat messages"],"unknowns":["deployment"],"assumptions":["Web first"],"risks":["scope"],"clarification_questions":["Which platform?"]})}}],"usage":{"prompt_tokens":9,"completion_tokens":5,"total_tokens":14}}
                return 200,{},json.dumps(response)
        tx=Transport(); provider=OpenAICompatibleUnderstandingProvider(UnderstandingProviderConfig("openai-compatible","https://provider.example/v1","model-test","secret-not-persisted",3,0),tx,sleeper=lambda _: None)
        result=self.store(provider).generate(self.alice,self.draft_id,0,'e2x-provider','understand')
        self.assertEqual('NEEDS_CLARIFICATION',result['state']); self.assertEqual(1,len(tx.calls)); self.assertEqual(3,tx.calls[0][3])
        with psycopg.connect(DATABASE_URL) as c:
            row=c.execute("SELECT source_draft_revision_id,provider,model,provider_request_id,prompt_version,schema_version,input_tokens,output_tokens,total_tokens,retry_count FROM public.entry_understanding_provenance").fetchone()
        source_revision_id=self.store(provider)._source(self.alice,self.draft_id)[1]["revision_id"]
        self.assertEqual(source_revision_id,row[0]); self.assertEqual('openai-compatible',row[1]); self.assertEqual('model-test',row[2]); self.assertEqual('provider-request-1',row[3]); self.assertEqual('v2',row[4]); self.assertEqual('v1',row[5]); self.assertEqual((9,5,14,0),tuple(row[6:])); self.assertNotIn('secret-not-persisted',str(row))
        projected=self.store(provider).get(self.alice,self.draft_id)["item"]["current"]["provider_metadata"]
        self.assertEqual(source_revision_id,projected["source_draft_revision_id"]); self.assertEqual('v2',projected["prompt_version"]); self.assertEqual('v1',projected["schema_version"])
    def test_source_snapshot_mismatch_is_rejected_before_authority_apply(self):
        source=self.store(Producer([]))._source(self.alice,self.draft_id)[1]
        stale=dict(source); stale['revision_id']='edrv-stale'
        with self.store(Producer([]))._connect() as c:
            with self.assertRaisesRegex(EntryUnderstandingRejected,'ENTRY_UNDERSTANDING_STALE_SOURCE_REVISION'):
                self.store(Producer([]))._assert_source_current(c,self.alice,self.draft_id,stale)

    def test_product_api_semantic_routes_and_no_leak(self):
        producer=Producer([output(clarifications=[{'question':'Which platform?','rationale':None}])])
        facade=ProductApiFacade(EmptyReadModel(),Gateway(),entry_draft_api=self.drafts,entry_understanding_api=self.store(producer))
        actor=Actor(ActorType.USER,self.alice)
        response=facade.handle(ProductApiRequest('POST',f'/production-drafts/{self.draft_id}/understanding',{'Idempotency-Key':'api-gen'},{'expected_version':0,'reason':'understand'},actor,verified_identity_subject=self.alice))
        self.assertEqual(202,response.status_code); self.assertEqual('NEEDS_CLARIFICATION',response.body['item']['state'])
        hidden=facade.handle(ProductApiRequest('GET',f'/production-drafts/{self.draft_id}/understanding',{}, {},Actor(ActorType.USER,self.bob),verified_identity_subject=self.bob))
        self.assertEqual('NOT_AVAILABLE',hidden.body['availability']); self.assertIsNone(hidden.body['item'])
        with self.assertRaisesRegex(Exception,'ENTRY_DRAFT_IDENTITY_REQUIRED'):
            facade.handle(ProductApiRequest('GET',f'/production-drafts/{self.draft_id}/understanding',{}, {},actor))
if __name__=='__main__': unittest.main()
