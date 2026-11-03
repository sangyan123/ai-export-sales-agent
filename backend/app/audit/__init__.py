import hashlib
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit import AuditLog


def client_ip_hash(request: Request) -> str:
    host = request.client.host if request.client else ""
    return hashlib.sha256(f"{settings.app_secret_key}:{host}".encode()).hexdigest()


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        request_id: str | None = None,
        ip_hash: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            ip_hash=ip_hash,
            metadata_json=dict(metadata or {}),
        )
        self._session.add(entry)
        return entry


__all__ = ["AuditService", "client_ip_hash"]
