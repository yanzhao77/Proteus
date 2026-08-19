from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Sequence

UNDERSTANDING_PROMPT_VERSION = "v2"
UNDERSTANDING_SCHEMA_VERSION = "v1"

UNDERSTANDING_PROMPT_V2 = """Return only one JSON object. Its top-level fields must exactly match the UnderstandingCandidate schema: goal, objectives, requirements, unknowns, assumptions, risks, clarification_questions. Do not add, omit, rename, nest, or explain fields. goal must be a non-empty string. Every other field must be an array of strings.

Requirements have a strict source rule: each requirements item must be a non-empty, verbatim traceable fragment from idea_text. Do not infer, paraphrase, recommend, normalize, or add general knowledge to requirements. If idea_text contains no explicit requirement, return requirements as an empty array. Put inferences, suggestions, uncertainties, and missing information only in assumptions, risks, unknowns, or clarification_questions.

Never return credentials, tokens, secrets, internal authority metadata, Project data, P6 data, plans, tasks, executions, or any field outside the schema."""

class ProducerError(Exception):
    def __init__(self, code: str): super().__init__(code); self.code = code

@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

@dataclass(frozen=True)
class ProducerProvenance:
    producer: str
    provider: Optional[str]
    model: Optional[str]
    model_version: Optional[str]
    provider_request_id: Optional[str]
    correlation_id: str
    prompt_version: str
    schema_version: str
    request_started_at: str
    completed_at: str
    latency_ms: Optional[int]
    retry_count: int
    usage: ProviderUsage

@dataclass(frozen=True)
class UnderstandingProducerRequest:
    draft_id: str
    source_revision_id: str
    source_revision_number: int
    idea_text: str
    relevant_constraints: Sequence[str]
    answered_clarifications: Sequence[Mapping[str, str]]
    previous_understanding: Optional[Mapping[str, object]]
    correlation_id: str
    prompt_version: str = UNDERSTANDING_PROMPT_VERSION
    schema_version: str = UNDERSTANDING_SCHEMA_VERSION

@dataclass(frozen=True)
class UnderstandingCandidate:
    goal: str
    objectives: Sequence[str]
    requirements: Sequence[str]
    unknowns: Sequence[str]
    assumptions: Sequence[str]
    risks: Sequence[str]
    clarification_questions: Sequence[str]

@dataclass(frozen=True)
class ProducedUnderstanding:
    candidate: UnderstandingCandidate
    provenance: ProducerProvenance

class UnderstandingProducer(Protocol):
    def generate(self, request: UnderstandingProducerRequest) -> ProducedUnderstanding: ...
