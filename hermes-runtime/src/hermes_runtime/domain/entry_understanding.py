class EntryUnderstandingRejected(Exception):
    pass

class EntryUnderstandingValidationError(EntryUnderstandingRejected):
    pass

READY = "READY"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
