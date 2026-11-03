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
