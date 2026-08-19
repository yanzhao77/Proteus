import json
import os
import unittest
from unittest.mock import patch
from hermes_runtime.domain.understanding_producer import UNDERSTANDING_PROMPT_VERSION, UNDERSTANDING_SCHEMA_VERSION, UnderstandingProducerRequest, ProducerError
from hermes_runtime.infrastructure.openai_compatible_understanding_provider import UnderstandingProviderConfig, OpenAICompatibleUnderstandingProvider
from hermes_runtime.infrastructure.understanding_provider_registry import UnavailableUnderstandingProducer, build_understanding_producer_from_env

class ScriptedTransport:
    def __init__(self, responses): self.responses=list(responses); self.calls=[]
    def post(self, url, headers, payload, timeout_seconds):
        self.calls.append((url,headers,payload,timeout_seconds))
        item=self.responses.pop(0)
        if isinstance(item,Exception): raise item
        return item

def request(): return UnderstandingProducerRequest('edr-1','edrv-1',1,'Build a chat app with chat messages',['fast'],[],None,'corr-1')
def success(request_id='req-1', usage=True):
    body={'id':request_id,'choices':[{'message':{'content':json.dumps({'goal':'Build a chat app','objectives':['Support real-time chat'],'requirements':['chat messages'],'unknowns':['deployment target'],'assumptions':['Web first'],'risks':['scope growth'],'clarification_questions':['Which platform?']})}}]}
    if usage: body['usage']={'prompt_tokens':11,'completion_tokens':7,'total_tokens':18}
    return 200,{},json.dumps(body)
def config(): return UnderstandingProviderConfig('openai-compatible','https://provider.example/v1','model-1','super-secret-key',3,2)

class ProviderAdapterTests(unittest.TestCase):
    def test_configured_provider_parses_candidate_usage_and_explicit_timeout(self):
        tx=ScriptedTransport([success()]); provider=OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None)
        output=provider.generate(request())
        self.assertEqual('Build a chat app',output.candidate.goal); self.assertEqual(('chat messages',),output.candidate.requirements)
        self.assertEqual('openai-compatible',output.provenance.provider); self.assertEqual('model-1',output.provenance.model); self.assertEqual('req-1',output.provenance.provider_request_id)
        self.assertEqual(11,output.provenance.usage.input_tokens); self.assertEqual(3,tx.calls[0][3]); self.assertNotIn('super-secret-key',str(output.provenance))
    def test_prompt_v2_and_code_owned_schema_version_are_in_payload_and_provenance(self):
        tx=ScriptedTransport([success()])
        output=OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None).generate(request())
        self.assertEqual("v2", UNDERSTANDING_PROMPT_VERSION)
        self.assertEqual("v1", UNDERSTANDING_SCHEMA_VERSION)
        self.assertEqual("v2", output.provenance.prompt_version)
        self.assertEqual("v1", output.provenance.schema_version)
        system_prompt=tx.calls[0][2]["messages"][0]["content"]
        self.assertIn("verbatim traceable fragment from idea_text", system_prompt)
        self.assertIn("If idea_text contains no explicit requirement", system_prompt)
        self.assertEqual("v2", json.loads(tx.calls[0][2]["messages"][1]["content"])["prompt_version"])
        self.assertEqual("v1", json.loads(tx.calls[0][2]["messages"][1]["content"])["schema_version"])

    def test_schema_environment_override_cannot_forge_provenance(self):
        env={"HERMES_UNDERSTANDING_PROVIDER":"openai-compatible","HERMES_UNDERSTANDING_BASE_URL":"https://x","HERMES_UNDERSTANDING_MODEL":"m","PROTEUS_LLM_API_KEY":"k","HERMES_UNDERSTANDING_SCHEMA_VERSION":"v999"}
        with patch.dict(os.environ,env,clear=True):
            provider=build_understanding_producer_from_env()
        self.assertIsInstance(provider,OpenAICompatibleUnderstandingProvider)
        self.assertFalse(hasattr(provider._config,"schema_version"))

    def test_usage_is_nullable_when_provider_omits_it(self):
        out=OpenAICompatibleUnderstandingProvider(config(),ScriptedTransport([success(usage=False)]),sleeper=lambda _: None).generate(request())
        self.assertIsNone(out.provenance.usage.input_tokens); self.assertIsNone(out.provenance.usage.total_tokens)
    def test_timeout_connection_429_and_every_5xx_retry_bounded(self):
        for response in [ProducerError('ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT'),ProducerError('ENTRY_UNDERSTANDING_PROVIDER_CONNECTION_ERROR'),(429,{},'{}'),(500,{},'{}'),(501,{},'{}'),(503,{},'{}'),(599,{},'{}')]:
            tx=ScriptedTransport([response,success()]); out=OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None).generate(request())
            self.assertEqual(2,len(tx.calls)); self.assertEqual(1,out.provenance.retry_count)
        tx=ScriptedTransport([(599,{},'{}'),(599,{},'{}'),(599,{},'{}')])
        with self.assertRaisesRegex(ProducerError,'ENTRY_UNDERSTANDING_PROVIDER_SERVER_ERROR'): OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None).generate(request())
        self.assertEqual(3,len(tx.calls))
    def test_401_403_400_do_not_retry_or_leak_key(self):
        for status,code in [(401,'ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED'),(403,'ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED'),(400,'ENTRY_UNDERSTANDING_PROVIDER_BAD_REQUEST')]:
            tx=ScriptedTransport([(status,{},'bad body with super-secret-key')])
            with self.assertRaisesRegex(ProducerError,code) as raised: OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None).generate(request())
            self.assertEqual(1,len(tx.calls)); self.assertNotIn('super-secret-key',str(raised.exception))
    def test_malformed_or_schema_invalid_response_rejected_without_defaults(self):
        for body in ['not-json',json.dumps({'id':'req','choices':[{'message':{'content':'{"goal":"only"}'}}]})]:
            tx=ScriptedTransport([(200,{},body)])
            with self.assertRaisesRegex(ProducerError,'ENTRY_UNDERSTANDING_PROVIDER_INVALID_RESPONSE|ENTRY_UNDERSTANDING_SCHEMA_INVALID'): OpenAICompatibleUnderstandingProvider(config(),tx,sleeper=lambda _: None).generate(request())

    def test_timeout_and_retry_configuration_fail_closed_without_transport(self):
        invalid=[dict(timeout_seconds=0),dict(timeout_seconds=-1),dict(timeout_seconds=float("nan")),dict(timeout_seconds=float("inf")),dict(max_retries=-1),dict(max_retries=3),dict(max_retries=1.5)]
        for changes in invalid:
            values={"provider":"openai-compatible","base_url":"https://provider.example/v1","model":"model-1","api_key":"super-secret-key","timeout_seconds":3,"max_retries":2}; values.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ProducerError,"ENTRY_UNDERSTANDING_CONFIGURATION_ERROR"): UnderstandingProviderConfig(**values)
    def test_inline_key_precedes_file_key(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w",delete=False) as f: f.write("file-key"); name=f.name
        try:
            with patch.dict(os.environ,{"HERMES_UNDERSTANDING_PROVIDER":"openai-compatible","HERMES_UNDERSTANDING_BASE_URL":"https://x","HERMES_UNDERSTANDING_MODEL":"m","PROTEUS_LLM_API_KEY":"inline-key","PROTEUS_LLM_API_KEY_FILE":name},clear=True):
                provider=build_understanding_producer_from_env(); self.assertEqual("inline-key",provider._config.api_key)
        finally: os.unlink(name)

    def test_registry_is_configured_or_unavailable_only(self):
        with patch.dict(os.environ,{},clear=True): self.assertIsInstance(build_understanding_producer_from_env(),UnavailableUnderstandingProducer)
        with patch.dict(os.environ,{'HERMES_UNDERSTANDING_PROVIDER':'other'},clear=True):
            with self.assertRaisesRegex(ProducerError,'ENTRY_UNDERSTANDING_CONFIGURATION_ERROR'): build_understanding_producer_from_env().generate(request())
        with patch.dict(os.environ,{'HERMES_UNDERSTANDING_PROVIDER':'openai-compatible','HERMES_UNDERSTANDING_BASE_URL':'https://x','HERMES_UNDERSTANDING_MODEL':'m','PROTEUS_LLM_API_KEY':'k'},clear=True):
            self.assertIsInstance(build_understanding_producer_from_env(),OpenAICompatibleUnderstandingProvider)
