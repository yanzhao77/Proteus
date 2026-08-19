import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
from hermes_runtime.domain.entry_understanding import EntryUnderstandingRejected, EntryUnderstandingValidationError, READY, NEEDS_CLARIFICATION
from hermes_runtime.domain.understanding_producer import UNDERSTANDING_PROMPT_VERSION, UNDERSTANDING_SCHEMA_VERSION, UnderstandingProducer, UnderstandingProducerRequest, ProducedUnderstanding, ProducerError

class EntryUnderstandingStoreUnavailable(Exception): pass
def _hash(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
def _array(value, name):
    if value is None: return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    return value
def _validate(raw):
    if not isinstance(raw, Mapping): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    allowed={"interpreted_intent","objective","user_constraints","explicit_requirements","ambiguities","open_questions","assumptions","clarifications","confidence","provider_metadata"}
    if set(raw)-allowed: raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    intent=raw.get("interpreted_intent")
    if not isinstance(intent,str) or not intent.strip(): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    objective=raw.get("objective")
    if objective is not None and (not isinstance(objective,str) or not objective.strip()): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    assumptions=raw.get("assumptions") or []; clarifications=raw.get("clarifications") or []
    if not isinstance(assumptions,list) or not isinstance(clarifications,list): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    for row in assumptions:
        if not isinstance(row,Mapping) or set(row)-{"statement","basis"} or not isinstance(row.get("statement"),str) or not row["statement"].strip() or row.get("basis") is not None and not isinstance(row.get("basis"),str): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    for row in clarifications:
        if not isinstance(row,Mapping) or set(row)-{"question","rationale"} or not isinstance(row.get("question"),str) or not row["question"].strip() or row.get("rationale") is not None and not isinstance(row.get("rationale"),str): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    confidence=raw.get("confidence")
    if confidence is not None and (not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or confidence<0 or confidence>1): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    meta=raw.get("provider_metadata")
    if meta is not None and not isinstance(meta,Mapping): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    return {"interpreted_intent":intent.strip(),"objective":objective.strip() if isinstance(objective,str) else None,"user_constraints":_array(raw.get("user_constraints"),"user_constraints"),"explicit_requirements":_array(raw.get("explicit_requirements"),"explicit_requirements"),"ambiguities":_array(raw.get("ambiguities"),"ambiguities"),"open_questions":_array(raw.get("open_questions"),"open_questions"),"assumptions":[{"statement":r["statement"].strip(),"basis":r.get("basis")} for r in assumptions],"clarifications":[{"question":r["question"].strip(),"rationale":r.get("rationale")} for r in clarifications],"confidence":confidence,"provider_metadata":dict(meta) if meta is not None else None}

def _candidate_output(produced, source):
    if not isinstance(produced, ProducedUnderstanding): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_SCHEMA_INVALID")
    candidate=produced.candidate
    raw=source["raw_input"].casefold()
    requirements=list(candidate.requirements)
    if any(item.casefold() not in raw for item in requirements): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_DOMAIN_INVALID")
    mapped={"interpreted_intent":candidate.goal,"objective":"; ".join(candidate.objectives) if candidate.objectives else None,"user_constraints":[],"explicit_requirements":requirements,"ambiguities":list(candidate.risks),"open_questions":list(candidate.unknowns),"assumptions":[{"statement":item,"basis":None} for item in candidate.assumptions],"clarifications":[{"question":item,"rationale":None} for item in candidate.clarification_questions],"confidence":None,"provider_metadata":None}
    return _validate(mapped)

class PostgresEntryUnderstandingStore:
    def __init__(self,database_url: str,producer: UnderstandingProducer): self.database_url,self.producer=database_url,producer
    def _connect(self):
        if psycopg is None: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE")
        return psycopg.connect(self.database_url,row_factory=dict_row)
    def _source(self,creator,draft_id):
        try:
            with self._connect() as c:
                draft=c.execute("SELECT * FROM public.entry_drafts WHERE draft_id=%s AND creator_subject=%s",(draft_id,creator)).fetchone()
                if not draft: raise EntryUnderstandingRejected("ENTRY_DRAFT_NOT_AVAILABLE")
                if draft["state"]!="SUBMITTED": raise EntryUnderstandingRejected("E2_UNDERSTANDING_DRAFT_NOT_SUBMITTED")
                rev=c.execute("SELECT revision_id,revision_number,raw_input,title FROM public.entry_draft_revisions WHERE draft_id=%s AND revision_number=%s",(draft_id,draft["latest_revision_number"])).fetchone()
                if not rev: raise EntryUnderstandingRejected("E2_UNDERSTANDING_SOURCE_UNAVAILABLE")
                return dict(draft),dict(rev)
        except EntryUnderstandingRejected: raise
        except Exception as exc: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE") from exc
    def _reserve(self,creator,draft_id,kind,key,payload):
        if not isinstance(key,str) or not key.strip(): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_VALIDATION_FAILED")
        request_hash=_hash(payload)
        try:
            with self._connect() as c:
                with c.transaction():
                    rec=c.execute("SELECT * FROM public.entry_understanding_command_receipts WHERE creator_subject=%s AND command_type=%s AND idempotency_key=%s FOR UPDATE",(creator,kind,key)).fetchone()
                    if rec:
                        if rec["request_hash"]!=request_hash: raise EntryUnderstandingRejected("E2_UNDERSTANDING_IDEMPOTENCY_CONFLICT")
                        if rec["status"]=="APPLIED": return None,dict(rec["result"])
                        if rec["status"]=="REJECTED": raise EntryUnderstandingRejected((rec["result"] or {}).get("error_code","E2_UNDERSTANDING_COMMAND_REJECTED"))
                        raise EntryUnderstandingRejected("E2_UNDERSTANDING_COMMAND_IN_PROGRESS")
                    cmd="euc-"+uuid.uuid4().hex
                    c.execute("INSERT INTO public.entry_understanding_command_receipts(command_id,creator_subject,understanding_id,command_type,idempotency_key,request_hash,status,result) VALUES(%s,%s,NULL,%s,%s,%s,'PROCESSING','{}'::jsonb)",(cmd,creator,kind,key,request_hash))
                    return cmd,None
        except (EntryUnderstandingRejected,EntryUnderstandingValidationError): raise
        except Exception as exc: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE") from exc
    def _reject_receipt(self,cmd,code):
        try:
            with self._connect() as c:
                with c.transaction(): c.execute("UPDATE public.entry_understanding_command_receipts SET status='REJECTED',result=%s::jsonb,completed_at=now() WHERE command_id=%s AND status='PROCESSING'",(json.dumps({"error_code":code}),cmd))
        except Exception: pass
    def _producer_request(self,c,creator,draft,source,correlation,pending=None):
        current=c.execute("SELECT understanding_id FROM public.entry_understandings WHERE draft_id=%s AND creator_subject=%s",(draft["draft_id"],creator)).fetchone()
        answers=[]; previous=None
        if current:
            rows=c.execute("SELECT cl.question,a.answer FROM public.entry_clarifications cl JOIN public.entry_clarification_answers a ON a.clarification_id=cl.clarification_id WHERE cl.understanding_id=%s ORDER BY a.created_at",(current["understanding_id"],)).fetchall()
            answers=[{"question":r["question"],"answer":r["answer"]} for r in rows]
            latest=c.execute("SELECT interpreted_intent,objective,explicit_requirements FROM public.entry_understanding_revisions WHERE understanding_id=%s ORDER BY revision_number DESC LIMIT 1",(current["understanding_id"],)).fetchone()
            previous=dict(latest) if latest else None
        if pending: answers.append(pending)
        return UnderstandingProducerRequest(draft["draft_id"],source["revision_id"],int(source["revision_number"]),source["raw_input"],(),answers,previous,correlation,UNDERSTANDING_PROMPT_VERSION,UNDERSTANDING_SCHEMA_VERSION)
    def generate(self,creator,draft_id,expected_version,idempotency_key,reason):
        draft,source=self._source(creator,draft_id)
        payload={"draft_id":draft_id,"source_revision_id":source["revision_id"],"expected_version":expected_version,"reason":reason}
        cmd,replay=self._reserve(creator,draft_id,"understanding.generate",idempotency_key,payload)
        if replay: return replay
        try:
            with self._connect() as c: request=self._producer_request(c,creator,draft,source,cmd)
            produced=self.producer.generate(request); output=_candidate_output(produced,source)
            return self._complete_generate(cmd,creator,draft_id,source,expected_version,reason,output,produced)
        except ProducerError as exc:
            self._reject_receipt(cmd,exc.code)
            raise EntryUnderstandingRejected(exc.code) from exc
        except EntryUnderstandingRejected as exc: self._reject_receipt(cmd,str(exc)); raise
        except Exception as exc:
            self._reject_receipt(cmd,"ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED")
            raise EntryUnderstandingRejected("ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED") from exc
    def answer_clarification(self,creator,draft_id,clarification_id,answer,expected_version,idempotency_key,reason):
        if not isinstance(answer,str) or not answer.strip(): raise EntryUnderstandingValidationError("ENTRY_UNDERSTANDING_VALIDATION_FAILED")
        draft,source=self._source(creator,draft_id)
        payload={"draft_id":draft_id,"source_revision_id":source["revision_id"],"clarification_id":clarification_id,"answer":answer.strip(),"expected_version":expected_version,"reason":reason}
        cmd,replay=self._reserve(creator,draft_id,"understanding.answer_clarification",idempotency_key,payload)
        if replay: return replay
        try:
            with self._connect() as c:
                current=self._current(c,creator,draft_id)
                if not current: raise EntryUnderstandingRejected("E2_UNDERSTANDING_NOT_AVAILABLE")
                cl=c.execute("SELECT state FROM public.entry_clarifications WHERE clarification_id=%s AND understanding_id=%s",(clarification_id,current["understanding_id"])).fetchone()
                if not cl: raise EntryUnderstandingRejected("E2_CLARIFICATION_NOT_AVAILABLE")
                if cl["state"]!="OPEN": raise EntryUnderstandingRejected("E2_CLARIFICATION_NOT_OPEN")
                request=self._producer_request(c,creator,draft,source,cmd,{"clarification_id":clarification_id,"answer":answer.strip()})
            produced=self.producer.generate(request); output=_candidate_output(produced,source)
            return self._complete_answer(cmd,creator,draft_id,source,clarification_id,answer.strip(),expected_version,reason,output,produced)
        except ProducerError as exc:
            self._reject_receipt(cmd,exc.code)
            raise EntryUnderstandingRejected(exc.code) from exc
        except EntryUnderstandingRejected as exc: self._reject_receipt(cmd,str(exc)); raise
        except Exception as exc:
            self._reject_receipt(cmd,"ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED")
            raise EntryUnderstandingRejected("ENTRY_UNDERSTANDING_PROVIDER_REQUEST_FAILED") from exc
    def _current(self,c,creator,draft_id): return c.execute("SELECT * FROM public.entry_understandings WHERE draft_id=%s AND creator_subject=%s FOR UPDATE",(draft_id,creator)).fetchone()
    def _assert_source_current(self,c,creator,draft_id,source):
        row=c.execute("SELECT d.state,r.revision_id FROM public.entry_drafts d JOIN public.entry_draft_revisions r ON r.draft_id=d.draft_id AND r.revision_number=d.latest_revision_number WHERE d.draft_id=%s AND d.creator_subject=%s FOR UPDATE",(draft_id,creator)).fetchone()
        if not row or row["state"]!="SUBMITTED" or row["revision_id"]!=source["revision_id"]: raise EntryUnderstandingRejected("ENTRY_UNDERSTANDING_STALE_SOURCE_REVISION")
    def _complete_generate(self,cmd,creator,draft_id,source,expected,reason,output,produced):
        try:
            with self._connect() as c:
                with c.transaction():
                    self._assert_source_current(c,creator,draft_id,source); draft={"draft_id":draft_id}; current=self._current(c,creator,draft_id)
                    if current is None:
                        if expected not in (0,None): raise EntryUnderstandingRejected("E2_UNDERSTANDING_VERSION_CONFLICT")
                        uid="eun-"+uuid.uuid4().hex; version=1; revno=1; prev=None
                        c.execute("INSERT INTO public.entry_understandings(understanding_id,draft_id,creator_subject,state,version,latest_revision_number) VALUES(%s,%s,%s,%s,%s,%s)",(uid,draft_id,creator,NEEDS_CLARIFICATION if output["clarifications"] else READY,version,revno))
                    else:
                        if int(current["version"])!=int(expected): raise EntryUnderstandingRejected("E2_UNDERSTANDING_VERSION_CONFLICT")
                        uid=current["understanding_id"]; version=int(current["version"])+1; revno=int(current["latest_revision_number"])+1; prev=current["state"]
                    result=self._insert_revision(c,uid,creator,draft,source,output,version,revno,prev,cmd,reason,produced)
                    c.execute("UPDATE public.entry_understanding_command_receipts SET understanding_id=%s,status='APPLIED',result=%s::jsonb,completed_at=now() WHERE command_id=%s",(uid,json.dumps(result),cmd))
                    return result
        except EntryUnderstandingRejected: raise
        except Exception as exc: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE") from exc
    def _complete_answer(self,cmd,creator,draft_id,source,cid,answer,expected,reason,output,produced):
        try:
            with self._connect() as c:
                with c.transaction():
                    self._assert_source_current(c,creator,draft_id,source); current=self._current(c,creator,draft_id)
                    if not current: raise EntryUnderstandingRejected("E2_UNDERSTANDING_NOT_AVAILABLE")
                    if int(current["version"])!=int(expected): raise EntryUnderstandingRejected("E2_UNDERSTANDING_VERSION_CONFLICT")
                    cl=c.execute("SELECT state FROM public.entry_clarifications WHERE clarification_id=%s AND understanding_id=%s FOR UPDATE",(cid,current["understanding_id"])).fetchone()
                    if not cl: raise EntryUnderstandingRejected("E2_CLARIFICATION_NOT_AVAILABLE")
                    if cl["state"]!="OPEN": raise EntryUnderstandingRejected("E2_CLARIFICATION_NOT_OPEN")
                    c.execute("INSERT INTO public.entry_clarification_answers(answer_id,clarification_id,answer,answered_by_subject) VALUES(%s,%s,%s,%s)",("eca-"+uuid.uuid4().hex,cid,answer,creator)); c.execute("UPDATE public.entry_clarifications SET state='ANSWERED',answered_at=now() WHERE clarification_id=%s",(cid,))
                    result=self._insert_revision(c,current["understanding_id"],creator,{"draft_id":draft_id},source,output,int(current["version"])+1,int(current["latest_revision_number"])+1,current["state"],cmd,reason,produced)
                    c.execute("UPDATE public.entry_understanding_command_receipts SET understanding_id=%s,status='APPLIED',result=%s::jsonb,completed_at=now() WHERE command_id=%s",(current["understanding_id"],json.dumps(result),cmd)); return result
        except EntryUnderstandingRejected: raise
        except Exception as exc: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE") from exc
    def _insert_revision(self,c,uid,creator,draft,source,out,version,revno,prev,cmd,reason,produced):
        rid="eur-"+uuid.uuid4().hex; state=NEEDS_CLARIFICATION if out["clarifications"] else READY
        c.execute("INSERT INTO public.entry_understanding_revisions(understanding_revision_id,understanding_id,revision_number,source_draft_id,source_draft_revision_number,source_raw_input,interpreted_intent,objective,user_constraints,explicit_requirements,ambiguities,open_questions,confidence,provider_metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb)",(rid,uid,revno,draft["draft_id"],source["revision_number"],source["raw_input"],out["interpreted_intent"],out["objective"],json.dumps(out["user_constraints"]),json.dumps(out["explicit_requirements"]),json.dumps(out["ambiguities"]),json.dumps(out["open_questions"]),out["confidence"],json.dumps(out["provider_metadata"]) if out["provider_metadata"] is not None else None))
        p=produced.provenance; u=p.usage
        c.execute("INSERT INTO public.entry_understanding_provenance(understanding_revision_id,source_draft_revision_id,producer,provider,model,model_version,provider_request_id,correlation_id,prompt_version,schema_version,request_started_at,completed_at,latency_ms,retry_count,input_tokens,output_tokens,total_tokens) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(rid,source["revision_id"],p.producer,p.provider,p.model,p.model_version,p.provider_request_id,p.correlation_id,p.prompt_version,p.schema_version,p.request_started_at,p.completed_at,p.latency_ms,p.retry_count,u.input_tokens,u.output_tokens,u.total_tokens))
        for row in out["assumptions"]: c.execute("INSERT INTO public.entry_understanding_assumptions(assumption_id,understanding_id,understanding_revision_id,statement,basis) VALUES(%s,%s,%s,%s,%s)",("eas-"+uuid.uuid4().hex,uid,rid,row["statement"],row["basis"]))
        for row in out["clarifications"]: c.execute("INSERT INTO public.entry_clarifications(clarification_id,understanding_id,understanding_revision_id,question,rationale,state) VALUES(%s,%s,%s,%s,%s,'OPEN')",("ecl-"+uuid.uuid4().hex,uid,rid,row["question"],row["rationale"]))
        c.execute("UPDATE public.entry_understandings SET state=%s,version=%s,latest_revision_number=%s,updated_at=now() WHERE understanding_id=%s",(state,version,revno,uid)); c.execute("INSERT INTO public.entry_understanding_transition_records(transition_id,understanding_id,command_id,previous_state,new_state,understanding_version,actor_subject,reason,idempotency_key) SELECT %s,%s,%s,%s,%s,%s,%s,%s,idempotency_key FROM public.entry_understanding_command_receipts WHERE command_id=%s",("eut-"+uuid.uuid4().hex,uid,cmd,prev,state,version,creator,reason,cmd))
        return self._detail(c,creator,draft["draft_id"],uid)
    def get(self,creator,draft_id):
        try:
            with self._connect() as c:
                row=c.execute("SELECT understanding_id FROM public.entry_understandings WHERE draft_id=%s AND creator_subject=%s",(draft_id,creator)).fetchone(); return {"availability":"NOT_AVAILABLE","reason":"E2_UNDERSTANDING_NOT_AVAILABLE","item":None} if not row else {"availability":"CURRENT","item":self._detail(c,creator,draft_id,row["understanding_id"])}
        except Exception as exc: raise EntryUnderstandingStoreUnavailable("ENTRY_UNDERSTANDING_AUTHORITY_UNAVAILABLE") from exc
    def list_revisions(self,creator,draft_id):
        r=self.get(creator,draft_id); return {"availability":r["availability"],"reason":r.get("reason"),"items":[]} if not r.get("item") else {"availability":"CURRENT","items":r["item"]["revisions"]}
    def list_clarifications(self,creator,draft_id):
        r=self.get(creator,draft_id); return {"availability":r["availability"],"reason":r.get("reason"),"items":[]} if not r.get("item") else {"availability":"CURRENT","items":r["item"]["clarifications"]}
    def _detail(self,c,creator,draft_id,uid):
        u=c.execute("SELECT * FROM public.entry_understandings WHERE understanding_id=%s AND creator_subject=%s",(uid,creator)).fetchone(); revs=c.execute("SELECT * FROM public.entry_understanding_revisions WHERE understanding_id=%s ORDER BY revision_number",(uid,)).fetchall(); cls=c.execute("SELECT c.*,a.answer,a.answered_by_subject,a.created_at AS answer_created_at FROM public.entry_clarifications c LEFT JOIN public.entry_clarification_answers a ON a.clarification_id=c.clarification_id WHERE c.understanding_id=%s ORDER BY c.created_at",(uid,)).fetchall(); assumptions=c.execute("SELECT assumption_id,understanding_revision_id,statement,basis,created_at FROM public.entry_understanding_assumptions WHERE understanding_id=%s ORDER BY created_at",(uid,)).fetchall()
        def rev(r):
            provenance=c.execute("SELECT source_draft_revision_id,producer,provider,model,model_version,provider_request_id,prompt_version,schema_version,latency_ms,retry_count,input_tokens,output_tokens,total_tokens FROM public.entry_understanding_provenance WHERE understanding_revision_id=%s",(r["understanding_revision_id"],)).fetchone()
            return {"understanding_revision_id":r["understanding_revision_id"],"revision_number":int(r["revision_number"]),"source_draft_id":r["source_draft_id"],"source_draft_revision_number":int(r["source_draft_revision_number"]),"source_raw_input":r["source_raw_input"],"interpreted_intent":r["interpreted_intent"],"objective":r["objective"],"user_constraints":r["user_constraints"],"explicit_requirements":r["explicit_requirements"],"ambiguities":r["ambiguities"],"open_questions":r["open_questions"],"confidence":float(r["confidence"]) if r["confidence"] is not None else None,"provider_metadata":dict(provenance) if provenance else None,"generated_at":r["generated_at"].isoformat()}
        latest=rev(revs[-1]); return {"understanding_id":uid,"draft_id":draft_id,"state":u["state"],"version":int(u["version"]),"latest_revision_number":int(u["latest_revision_number"]),"created_at":u["created_at"].isoformat(),"updated_at":u["updated_at"].isoformat(),"current":latest,"revisions":[rev(r) for r in revs],"clarifications":[{"clarification_id":r["clarification_id"],"understanding_revision_id":r["understanding_revision_id"],"question":r["question"],"rationale":r["rationale"],"state":r["state"],"answer":r["answer"],"answered_at":r["answer_created_at"].isoformat() if r["answer_created_at"] else None} for r in cls],"assumptions":[{"assumption_id":r["assumption_id"],"understanding_revision_id":r["understanding_revision_id"],"statement":r["statement"],"basis":r["basis"],"created_at":r["created_at"].isoformat()} for r in assumptions],"as_of":u["updated_at"].isoformat(),"freshness":"NOT_AVAILABLE","source":"entry_understandings","source_version":int(u["version"])}
