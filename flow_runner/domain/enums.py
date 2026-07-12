from enum import StrEnum


class ConditionOutcome(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    ERROR = "error"


class StepOutcome(StrEnum):
    SUCCESS = "success"
    NOT_MATCHED = "not_matched"
    TIMEOUT = "timeout"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class ConditionMode(StrEnum):
    ONCE = "once"
    UNTIL = "until"

