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


class FollowupStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class FollowupSource(StrEnum):
    MANUAL = "MANUAL"
    RULE = "RULE"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    TENANT_ADMIN = "TENANT_ADMIN"
    SALES_MANAGER = "SALES_MANAGER"
    SALES_REP = "SALES_REP"
    APPROVER = "APPROVER"
    VIEWER = "VIEWER"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class MemberStatusUpdate(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
