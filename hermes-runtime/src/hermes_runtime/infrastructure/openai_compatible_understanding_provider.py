import json
import math
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Protocol
from hermes_runtime.domain.understanding_producer import UNDERSTANDING_PROMPT_V2, UnderstandingProducerRequest, UnderstandingCandidate, ProducedUnderstanding, ProducerProvenance, ProviderUsage, ProducerError

@dataclass(frozen=True)
class UnderstandingProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    def __post_init__(self):
        if self.provider != "openai-compatible" or not isinstance(self.base_url,str) or not self.base_url.strip() or not isinstance(self.model,str) or not self.model.strip() or not isinstance(self.api_key,str) or not self.api_key:
            raise ProducerError("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")
        if isinstance(self.timeout_seconds,bool) or not isinstance(self.timeout_seconds,(int,float)) or not math.isfinite(float(self.timeout_seconds)) or float(self.timeout_seconds)<=0:
            raise ProducerError("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")
        if isinstance(self.max_retries,bool) or not isinstance(self.max_retries,int) or self.max_retries<0 or self.max_retries>2:
            raise ProducerError("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")

class HttpTransport(Protocol):
    def post(self, url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout_seconds: float) -> tuple[int, Mapping[str, str], str]: ...

class UrllibJsonTransport:
    def post(self, url, headers, payload, timeout_seconds):
        req = urllib.request.Request(url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                return int(response.status), dict(response.headers.items()), response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return int(exc.code), dict(exc.headers.items()) if exc.headers else {}, exc.read().decode("utf-8", errors="replace")
        except socket.timeout as exc:
            raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT") from exc
        except urllib.error.URLError as exc:
            raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_CONNECTION_ERROR") from exc

def _now(): return datetime.now(timezone.utc).isoformat()
def _strings(value, field):
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value): raise ProducerError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    return tuple(item.strip() for item in value)
def _candidate(value):
    if not isinstance(value, Mapping): raise ProducerError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    allowed={"goal","objectives","requirements","unknowns","assumptions","risks","clarification_questions"}
    if set(value) != allowed or not isinstance(value.get("goal"),str) or not value["goal"].strip(): raise ProducerError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    return UnderstandingCandidate(value["goal"].strip(), _strings(value["objectives"],"objectives"), _strings(value["requirements"],"requirements"), _strings(value["unknowns"],"unknowns"), _strings(value["assumptions"],"assumptions"), _strings(value["risks"],"risks"), _strings(value["clarification_questions"],"clarification_questions"))

class OpenAICompatibleUnderstandingProvider:
    def __init__(self, config: UnderstandingProviderConfig, transport: HttpTransport = None, sleeper=time.sleep):
        if config.provider != "openai-compatible" or not config.base_url or not config.model or not config.api_key or isinstance(config.timeout_seconds,bool) or not isinstance(config.timeout_seconds,(int,float)) or not math.isfinite(float(config.timeout_seconds)) or config.timeout_seconds <= 0 or isinstance(config.max_retries,bool) or not isinstance(config.max_retries,int) or config.max_retries < 0 or config.max_retries > 2:
            raise ProducerError("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")
        self._config, self._transport, self._sleeper = config, transport or UrllibJsonTransport(), sleeper
    def generate(self, request: UnderstandingProducerRequest) -> ProducedUnderstanding:
        started=time.monotonic(); started_at=_now(); attempts=0; last=None
        url=self._config.base_url.rstrip("/")+"/chat/completions"
        payload={"model":self._config.model,"temperature":0,"response_format":{"type":"json_object"},"messages":[{"role":"system","content":UNDERSTANDING_PROMPT_V2},{"role":"user","content":json.dumps({"draft_id":request.draft_id,"source_revision_id":request.source_revision_id,"idea_text":request.idea_text,"relevant_constraints":list(request.relevant_constraints),"answered_clarifications":list(request.answered_clarifications),"previous_understanding":request.previous_understanding,"prompt_version":request.prompt_version,"schema_version":request.schema_version},separators=(",",":"))}]}
        for attempt in range(self._config.max_retries+1):
            attempts=attempt
            try:
                status, _headers, body=self._transport.post(url,{"Authorization":"Bearer "+self._config.api_key,"Content-Type":"application/json","Accept":"application/json"},payload,self._config.timeout_seconds)
            except ProducerError as exc:
                last=exc
                if exc.code not in {"ENTRY_UNDERSTANDING_PROVIDER_TIMEOUT","ENTRY_UNDERSTANDING_PROVIDER_CONNECTION_ERROR"} or attempt >= self._config.max_retries: raise
                self._sleeper(min(0.1*(2**attempt),1.0)); continue
            if status == 429 or 500 <= status <= 599:
                last=ProducerError("ENTRY_UNDERSTANDING_PROVIDER_RATE_LIMITED" if status==429 else "ENTRY_UNDERSTANDING_PROVIDER_SERVER_ERROR")
                if attempt >= self._config.max_retries: raise last
                self._sleeper(min(0.1*(2**attempt),1.0)); continue
            if status in {401,403}: raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_AUTH_FAILED")
            if 400 <= status < 500: raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_BAD_REQUEST")
            if status < 200 or status >= 300: raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED")
            try:
                response=json.loads(body)
                content=response["choices"][0]["message"]["content"]
                raw=json.loads(content) if isinstance(content,str) else content
                candidate=_candidate(raw)
            except (ValueError,KeyError,IndexError,TypeError):
                raise ProducerError("ENTRY_UNDERSTANDING_PROVIDER_INVALID_RESPONSE")
            usage=response.get("usage") if isinstance(response,Mapping) else None
            def nonnegative(name):
                value=usage.get(name) if isinstance(usage,Mapping) else None
                return value if isinstance(value,int) and value >= 0 else None
            completed_at=_now(); latency=int((time.monotonic()-started)*1000)
            provenance=ProducerProvenance("understanding-producer", "openai-compatible", self._config.model, None, response.get("id") if isinstance(response.get("id"),str) else None, request.correlation_id, request.prompt_version, request.schema_version, started_at, completed_at, latency, attempts, ProviderUsage(nonnegative("prompt_tokens"),nonnegative("completion_tokens"),nonnegative("total_tokens")))
            return ProducedUnderstanding(candidate,provenance)
        raise last or ProducerError("ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED")
