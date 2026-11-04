import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.common import envelope, envelope_meta, iso_datetime
from app.api.deps import ContextDep, SessionDep
from app.api.errors import ApiError, get_request_id
from app.audit import client_ip_hash
from app.auth.invitations import accept_invitation
from app.auth.service import IssuedTokens, login, logout, refresh
from app.models.tenant import Tenant, User

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    tenant_id: uuid.UUID | None = None
    tenant_slug: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def require_single_tenant_selector(self) -> "LoginRequest":
        if (self.tenant_id is None) == (self.tenant_slug is None):
            raise ValueError("exactly one of tenant_id or tenant_slug is required")
        return self


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("password")
    @classmethod
    def require_letters_and_digits(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("password must contain both letters and digits")
        return value


def _token_payload(tokens: IssuedTokens) -> dict[str, Any]:
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "Bearer",
        "expires_in": tokens.expires_in,
        "refresh_expires_in": tokens.refresh_expires_in,
    }


@router.post("/auth/login")
async def login_endpoint(
    payload: LoginRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    tokens = await login(
        session,
        email=payload.email,
        password=payload.password,
        tenant_id=payload.tenant_id,
        tenant_slug=payload.tenant_slug,
    )
    return {"data": _token_payload(tokens), "meta": envelope_meta(get_request_id(request))}


@router.post("/auth/refresh")
async def refresh_endpoint(
    payload: RefreshRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    tokens = await refresh(session, payload.refresh_token)
    return {"data": _token_payload(tokens), "meta": envelope_meta(get_request_id(request))}


@router.post("/auth/logout")
async def logout_endpoint(
    payload: LogoutRequest,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    await logout(session, user_id=context.user_id, raw_token=payload.refresh_token)
    return envelope({"revoked": True}, context)


@router.post("/auth/invitations/accept")
async def accept_invitation_endpoint(
    payload: AcceptInvitationRequest,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    accepted = await accept_invitation(
        session,
        token=payload.token,
        display_name=payload.display_name,
        password=payload.password,
        request_id=get_request_id(request),
        ip_hash=client_ip_hash(request),
    )
    return {
        "data": {
            "tokens": _token_payload(accepted.tokens),
            "tenant_slug": accepted.tenant.slug,
            "email": accepted.user.email,
        },
        "meta": envelope_meta(get_request_id(request)),
    }


@router.get("/users/me")
async def current_user(context: ContextDep, session: SessionDep) -> dict[str, Any]:
    user = await session.get(User, context.user_id)
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "user not found")
    tenant = await session.get(Tenant, context.tenant_id)
    return envelope(
        {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "last_login_at": iso_datetime(user.last_login_at) if user.last_login_at else None,
            "tenant": {
                "id": str(context.tenant_id),
                "name": tenant.name if tenant else None,
                "slug": tenant.slug if tenant else None,
            },
            "role": context.role_code,
            "permissions": sorted(permission.value for permission in context.permissions),
        },
        context,
    )
