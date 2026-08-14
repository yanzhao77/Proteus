from typing import Any, Mapping, Tuple


class LocalObservabilityExporter:
    def __init__(self) -> None:
        self._envelopes = []

    def export(self, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
        stored = dict(envelope)
        self._envelopes.append(stored)
        return {"status": "EXPORTED", "trace_id": stored["trace_id"], "span_id": stored["span_id"]}

    @property
    def envelopes(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(self._envelopes)
