from dataclasses import dataclass
from enum import Enum


class EntryDraftState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ARCHIVED = "ARCHIVED"


class EntryDraftRejected(ValueError):
    pass


@dataclass(frozen=True)
class EntryDraftCommand:
    creator_subject: str
    command_type: str
    idempotency_key: str
    expected_version: int
    reason: str


def require_transition(previous: EntryDraftState, target: EntryDraftState) -> None:
    allowed = {
        EntryDraftState.DRAFT: {EntryDraftState.SUBMITTED, EntryDraftState.ARCHIVED},
        EntryDraftState.SUBMITTED: {EntryDraftState.ARCHIVED},
        EntryDraftState.ARCHIVED: set(),
    }
    if target not in allowed[previous]:
        raise EntryDraftRejected("ENTRY_DRAFT_TRANSITION_FORBIDDEN")
