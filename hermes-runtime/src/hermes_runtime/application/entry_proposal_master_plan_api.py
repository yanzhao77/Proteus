from typing import Mapping, Protocol


class EntryProposalMasterPlanApi(Protocol):
    def generate_proposal(self, creator: str, draft_id: str, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, object]: ...
    def get_proposal(self, creator: str, draft_id: str) -> Mapping[str, object]: ...
    def list_proposal_revisions(self, creator: str, draft_id: str) -> Mapping[str, object]: ...
    def generate_master_plan(self, creator: str, draft_id: str, expected_version: int, idempotency_key: str, reason: str) -> Mapping[str, object]: ...
    def get_master_plan(self, creator: str, draft_id: str) -> Mapping[str, object]: ...
    def list_master_plan_revisions(self, creator: str, draft_id: str) -> Mapping[str, object]: ...


class UnavailableEntryProposalMasterPlanApi:
    def _unavailable_proposal(self, *_args: object, **_kwargs: object) -> Mapping[str, object]:
        return {"availability": "NOT_AVAILABLE", "reason": "ENTRY_PROPOSAL_AUTHORITY_UNAVAILABLE", "item": None, "items": []}

    def _unavailable_plan(self, *_args: object, **_kwargs: object) -> Mapping[str, object]:
        return {"availability": "NOT_AVAILABLE", "reason": "ENTRY_PLAN_AUTHORITY_UNAVAILABLE", "item": None, "items": []}

    generate_proposal = get_proposal = list_proposal_revisions = _unavailable_proposal
    generate_master_plan = get_master_plan = list_master_plan_revisions = _unavailable_plan
