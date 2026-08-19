import os
from hermes_runtime.config import env_or_file
from hermes_runtime.domain.understanding_producer import ProducerError, UnderstandingProducerRequest
from hermes_runtime.infrastructure.openai_compatible_understanding_provider import UnderstandingProviderConfig, OpenAICompatibleUnderstandingProvider

class UnavailableUnderstandingProducer:
    def __init__(self, code="ENTRY_UNDERSTANDING_PROVIDER_UNAVAILABLE"): self._code=code
    def generate(self, request: UnderstandingProducerRequest): raise ProducerError(self._code)

def build_understanding_producer_from_env():
    provider=os.getenv("HERMES_UNDERSTANDING_PROVIDER", "").strip()
    if not provider: return UnavailableUnderstandingProducer()
    if provider != "openai-compatible": return UnavailableUnderstandingProducer("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")
    try:
        config=UnderstandingProviderConfig(provider=provider, base_url=os.getenv("HERMES_UNDERSTANDING_BASE_URL", "").strip(), model=os.getenv("HERMES_UNDERSTANDING_MODEL", "").strip(), api_key=env_or_file("PROTEUS_LLM_API_KEY"), timeout_seconds=float(os.getenv("HERMES_UNDERSTANDING_TIMEOUT_SECONDS", "15")), max_retries=int(os.getenv("HERMES_UNDERSTANDING_MAX_RETRIES", "2")))
        return OpenAICompatibleUnderstandingProvider(config)
    except (ValueError, ProducerError):
        return UnavailableUnderstandingProducer("ENTRY_UNDERSTANDING_CONFIGURATION_ERROR")
