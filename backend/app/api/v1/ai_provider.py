import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import SessionDep, require_permission
from app.api.errors import ApiError
from app.core.config import settings
from app.core.encryption import EncryptionError, decrypt_api_key, encrypt_api_key, mask_api_key
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.ai_provider import TenantAIProviderConfig

router = APIRouter(prefix="/settings/ai-provider", tags=["ai-provider"])

TenantReadDep = Depends(require_permission(Permission.TENANT_READ))
TenantUpdateDep = Depends(require_permission(Permission.TENANT_UPDATE))

ALLOWED_PROVIDERS = frozenset({"openai", "openai-compatible"})


class AIProviderUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=255)
    model_id: str | None = Field(default=None, max_length=120)
    enabled: bool = False

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(ALLOWED_PROVIDERS)}")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if stripped and not stripped.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return stripped.rstrip("/") or None

    @field_validator("model_id", "api_key")
    @classmethod
    def strip_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def _config_detail(config: TenantAIProviderConfig) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "api_key_hint": config.api_key_hint,
        "api_key_set": config.encrypted_api_key is not None,
        "base_url": config.base_url,
        "model_id": config.model_id,
        "enabled": config.enabled,
        "last_test_at": iso_datetime(config.last_test_at) if config.last_test_at else None,
        "last_test_status": config.last_test_status,
        "last_test_message": config.last_test_message,
        "updated_at": iso_datetime(config.updated_at),
    }


async def _get_config(
    session: AsyncSession, tenant_id: uuid.UUID
) -> TenantAIProviderConfig | None:
    return await session.scalar(
        select(TenantAIProviderConfig).where(
            TenantAIProviderConfig.tenant_id == tenant_id
        )
    )


@router.get("")
async def get_ai_provider(
    context: Annotated[Any, TenantReadDep],
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    config = await _get_config(session, context.tenant_id)
    if config is None:
        return envelope(
            {
                "provider": None,
                "api_key_hint": None,
                "api_key_set": False,
                "base_url": None,
                "model_id": None,
                "enabled": False,
                "last_test_at": None,
                "last_test_status": None,
                "last_test_message": None,
                "updated_at": None,
                "env_fallback": {
                    "provider": settings.llm_provider,
                    "model_id": settings.llm_model,
                },
            },
            context,
        )
    data = _config_detail(config)
    data["env_fallback"] = {
        "provider": settings.llm_provider,
        "model_id": settings.llm_model,
    }
    return envelope(data, context)


@router.put("")
async def update_ai_provider(
    payload: AIProviderUpdate,
    context: Annotated[Any, TenantUpdateDep],
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    config = await _get_config(session, context.tenant_id)
    if config is None:
        config = TenantAIProviderConfig(
            tenant_id=context.tenant_id,
            updated_by_id=context.user_id,
        )
        session.add(config)

    config.provider = payload.provider
    config.base_url = payload.base_url
    config.model_id = payload.model_id
    config.enabled = payload.enabled
    config.updated_by_id = context.user_id

    if payload.api_key is not None:
        try:
            config.encrypted_api_key = encrypt_api_key(payload.api_key)
            config.api_key_hint = mask_api_key(payload.api_key)
        except EncryptionError as exc:
            raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc

    if payload.enabled and config.encrypted_api_key is None:
        raise ApiError(
            422,
            "API_KEY_REQUIRED",
            "api_key must be set before enabling tenant provider",
        )

    await session.flush()
    await session.refresh(config)
    await commit_or_rollback(session)
    return envelope(_config_detail(config), context)


@router.post("/test")
async def test_ai_provider(
    context: Annotated[Any, TenantReadDep],
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    config = await _get_config(session, context.tenant_id)
    if config is None or config.encrypted_api_key is None:
        raise ApiError(404, "AI_PROVIDER_NOT_CONFIGURED", "no tenant AI provider configured")

    try:
        api_key = decrypt_api_key(config.encrypted_api_key)
    except EncryptionError as exc:
        raise ApiError(409, "DECRYPTION_FAILED", str(exc)) from exc

    base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
    started = datetime.now(UTC)
    ok = False
    message = ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": config.model_id or settings.llm_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
        latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        if response.status_code < 400:
            ok = True
            message = f"OK ({latency_ms} ms)"
        elif response.status_code in (401, 403):
            message = "authentication failed: check API key"
        elif response.status_code == 404:
            message = "model or endpoint not found: check model_id and base_url"
        else:
            message = f"provider returned HTTP {response.status_code}"
    except httpx.HTTPError:
        message = "provider unreachable: check base_url and network"

    config.last_test_at = datetime.now(UTC)
    config.last_test_status = "SUCCESS" if ok else "FAILED"
    config.last_test_message = message[:500]
    await session.flush()
    await commit_or_rollback(session)

    return envelope(
        {
            "status": config.last_test_status,
            "message": config.last_test_message,
            "tested_at": iso_datetime(config.last_test_at),
        },
        context,
    )
