from enum import StrEnum


class MatchStatus(StrEnum):
    EXACT = "EXACT"
    POSSIBLE = "POSSIBLE"
    CONFLICT = "CONFLICT"
    NO_MATCH = "NO_MATCH"


class MatchingErrorCode(StrEnum):
    INQUIRY_NOT_FOUND = "INQUIRY_NOT_FOUND"
    INQUIRY_STATUS_NOT_MATCHABLE = "INQUIRY_STATUS_NOT_MATCHABLE"
    REQUIREMENTS_NOT_READY = "REQUIREMENTS_NOT_READY"
    REQUIREMENTS_INCOMPLETE = "REQUIREMENTS_INCOMPLETE"


class MatchingError(Exception):
    def __init__(self, code: MatchingErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = ["MatchStatus", "MatchingError", "MatchingErrorCode"]
