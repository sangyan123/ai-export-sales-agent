from enum import StrEnum


class EmailStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class EmailErrorCode(StrEnum):
    INQUIRY_NOT_FOUND = "INQUIRY_NOT_FOUND"
    EMAIL_DRAFT_NOT_FOUND = "EMAIL_DRAFT_NOT_FOUND"
    EMAIL_QUOTE_NOT_FOUND = "EMAIL_QUOTE_NOT_FOUND"
    EMAIL_QUOTE_NOT_APPROVED = "EMAIL_QUOTE_NOT_APPROVED"
    EMAIL_DRAFT_NOT_EDITABLE = "EMAIL_DRAFT_NOT_EDITABLE"
    EMAIL_DRAFT_NOT_APPROVABLE = "EMAIL_DRAFT_NOT_APPROVABLE"
    EMAIL_UNSUPPORTED_LANGUAGE = "EMAIL_UNSUPPORTED_LANGUAGE"


class EmailError(Exception):
    def __init__(self, code: EmailErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = ["EmailError", "EmailErrorCode", "EmailStatus"]
