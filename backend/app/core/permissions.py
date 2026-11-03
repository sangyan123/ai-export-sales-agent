from enum import StrEnum


class Permission(StrEnum):
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE_ROLE = "member:update_role"
    PRODUCT_READ = "product:read"
    PRODUCT_CREATE = "product:create"
    PRODUCT_UPDATE = "product:update"
    PRODUCT_IMPORT = "product:import"
    PRICING_READ = "pricing:read"
    PRICING_UPDATE = "pricing:update"
    INQUIRY_READ = "inquiry:read"
    INQUIRY_CREATE = "inquiry:create"
    INQUIRY_UPDATE = "inquiry:update"
    AI_RUN = "ai:run"
    QUOTE_CREATE = "quote:create"
    QUOTE_READ = "quote:read"
    QUOTE_CALCULATE = "quote:calculate"
    QUOTE_SUBMIT = "quote:submit"
    QUOTE_APPROVE = "quote:approve"
    QUOTE_CANCEL = "quote:cancel"
    EMAIL_DRAFT = "email:draft"
    EMAIL_APPROVE = "email:approve"
    EMAIL_SEND = "email:send"
    CUSTOMER_READ = "customer:read"
    CUSTOMER_CREATE = "customer:create"
    CUSTOMER_UPDATE = "customer:update"
    FOLLOWUP_MANAGE = "followup:manage"
    AUDIT_READ = "audit:read"
    USAGE_READ = "usage:read"
    DATA_EXPORT = "data:export"


_READ_ONLY = frozenset(
    {
        Permission.PRODUCT_READ,
        Permission.PRICING_READ,
        Permission.INQUIRY_READ,
        Permission.QUOTE_READ,
        Permission.CUSTOMER_READ,
    }
)

_SALES_REP = _READ_ONLY | frozenset(
    {
        Permission.INQUIRY_CREATE,
        Permission.INQUIRY_UPDATE,
        Permission.AI_RUN,
        Permission.QUOTE_CREATE,
        Permission.QUOTE_CALCULATE,
        Permission.QUOTE_SUBMIT,
        Permission.QUOTE_CANCEL,
        Permission.EMAIL_DRAFT,
        Permission.CUSTOMER_CREATE,
        Permission.CUSTOMER_UPDATE,
        Permission.FOLLOWUP_MANAGE,
    }
)

_SALES_MANAGER = _SALES_REP | frozenset(
    {
        Permission.PRODUCT_CREATE,
        Permission.PRODUCT_UPDATE,
        Permission.PRODUCT_IMPORT,
        Permission.PRICING_UPDATE,
        Permission.QUOTE_APPROVE,
        Permission.EMAIL_APPROVE,
        Permission.USAGE_READ,
        Permission.AUDIT_READ,
    }
)

_APPROVER = _READ_ONLY | frozenset(
    {
        Permission.QUOTE_APPROVE,
        Permission.EMAIL_APPROVE,
    }
)

_ADMIN = frozenset(Permission)

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "OWNER": _ADMIN,
    "TENANT_ADMIN": _ADMIN,
    "SALES_MANAGER": _SALES_MANAGER,
    "SALES_REP": _SALES_REP,
    "APPROVER": _APPROVER,
    "VIEWER": _READ_ONLY,
}


def permissions_for_role(role_code: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role_code, frozenset())
