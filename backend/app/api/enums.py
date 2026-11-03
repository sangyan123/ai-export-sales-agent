from enum import StrEnum


class ProductCategory(StrEnum):
    BOLT = "BOLT"
    NUT = "NUT"
    SCREW = "SCREW"
    WASHER = "WASHER"
    OTHER = "OTHER"


class CatalogStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class PriceBasis(StrEnum):
    PER_PIECE = "PER_PIECE"
    PER_KG = "PER_KG"
    PER_SET = "PER_SET"
    PER_LOT = "PER_LOT"


class OverrideApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InquiryStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    NEEDS_INFO = "NEEDS_INFO"
    READY_FOR_MATCH = "READY_FOR_MATCH"
    MATCHED = "MATCHED"
    QUOTE_DRAFTED = "QUOTE_DRAFTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    QUOTE_APPROVED = "QUOTE_APPROVED"
    REPLIED = "REPLIED"
    WON = "WON"
    LOST = "LOST"
    ARCHIVED = "ARCHIVED"


class InquirySourceType(StrEnum):
    MANUAL = "MANUAL"
    EMAIL = "EMAIL"
    UPLOAD = "UPLOAD"
    OTHER = "OTHER"


INQUIRY_STATUS_TRANSITIONS: dict[InquiryStatus, frozenset[InquiryStatus]] = {
    InquiryStatus.RECEIVED: frozenset(
        {
            InquiryStatus.PARSING,
            InquiryStatus.NEEDS_INFO,
            InquiryStatus.READY_FOR_MATCH,
            InquiryStatus.ARCHIVED,
        }
    ),
    InquiryStatus.PARSING: frozenset({InquiryStatus.NEEDS_INFO, InquiryStatus.READY_FOR_MATCH}),
    InquiryStatus.NEEDS_INFO: frozenset(
        {
            InquiryStatus.RECEIVED,
            InquiryStatus.PARSING,
            InquiryStatus.READY_FOR_MATCH,
            InquiryStatus.ARCHIVED,
        }
    ),
    InquiryStatus.READY_FOR_MATCH: frozenset({InquiryStatus.MATCHED, InquiryStatus.NEEDS_INFO}),
    InquiryStatus.MATCHED: frozenset({InquiryStatus.QUOTE_DRAFTED, InquiryStatus.NEEDS_INFO}),
    InquiryStatus.QUOTE_DRAFTED: frozenset({InquiryStatus.PENDING_APPROVAL, InquiryStatus.MATCHED}),
    InquiryStatus.PENDING_APPROVAL: frozenset(
        {InquiryStatus.QUOTE_APPROVED, InquiryStatus.QUOTE_DRAFTED}
    ),
    InquiryStatus.QUOTE_APPROVED: frozenset({InquiryStatus.REPLIED, InquiryStatus.LOST}),
    InquiryStatus.REPLIED: frozenset(
        {InquiryStatus.WON, InquiryStatus.LOST, InquiryStatus.QUOTE_DRAFTED}
    ),
    InquiryStatus.WON: frozenset({InquiryStatus.ARCHIVED}),
    InquiryStatus.LOST: frozenset({InquiryStatus.ARCHIVED}),
    InquiryStatus.ARCHIVED: frozenset(),
}
