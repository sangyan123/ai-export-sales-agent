import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.tenant import Tenant, TenantMembership, User
from app.models.workflow import WorkflowRun

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(bind=connection, expire_on_commit=False)
            async with factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncClient:
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@dataclass(frozen=True)
class WorkflowSeed:
    tenant: Tenant
    manager: User
    viewer: User
    manager_headers: dict[str, str]
    viewer_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_tenant(session: AsyncSession, slug: str) -> WorkflowSeed:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    manager = User(
        email=f"manager@{slug}.example", password_hash=PASSWORD_HASH, display_name="Manager"
    )
    viewer = User(
        email=f"viewer@{slug}.example", password_hash=PASSWORD_HASH, display_name="Viewer"
    )
    session.add_all([manager, viewer])
    await session.flush()
    manager_membership = TenantMembership(
        tenant_id=tenant.id, user_id=manager.id, role_code="SALES_MANAGER"
    )
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    session.add_all([manager_membership, viewer_membership])
    await session.flush()

    return WorkflowSeed(
        tenant=tenant,
        manager=manager,
        viewer=viewer,
        manager_headers=_bearer(tenant, manager, manager_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
    )


def build_run(
    seed: WorkflowSeed,
    *,
    status: str = "QUEUED",
    business_object_id: uuid.UUID | None = None,
    **overrides: Any,
) -> WorkflowRun:
    run = WorkflowRun(
        tenant_id=seed.tenant.id,
        workflow_type="INQUIRY_ANALYSIS",
        business_object_type="INQUIRY",
        business_object_id=business_object_id or uuid.uuid4(),
        status=status,
        input_ref={"inquiry_id": str(uuid.uuid4())},
        requested_by=seed.manager.id,
    )
    for key, value in overrides.items():
        setattr(run, key, value)
    return run


async def test_get_workflow_run(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_tenant(session, "wf-get")
    inquiry_id = uuid.uuid4()
    run = build_run(seed, business_object_id=inquiry_id)
    session.add(run)
    await session.flush()

    response = await client.get(
        f"/api/v1/workflow-runs/{run.id}",
        headers=seed.manager_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == str(run.id)
    assert data["workflow_type"] == "INQUIRY_ANALYSIS"
    assert data["business_object_type"] == "INQUIRY"
    assert data["business_object_id"] == str(inquiry_id)
    assert data["status"] == "QUEUED"
    assert data["error_code"] is None
    assert data["started_at"] is None
    assert data["finished_at"] is None
    assert "input_ref" not in data
    assert "output_ref" not in data


async def test_workflow_run_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/workflow-runs/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_workflow_run_is_not_visible_to_another_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed_a = await seed_tenant(session, "wf-tenant-a")
    seed_b = await seed_tenant(session, "wf-tenant-b")
    await set_tenant_context(session, seed_a.tenant.id)
    run = build_run(seed_a)
    session.add(run)
    await session.flush()

    response = await client.get(
        f"/api/v1/workflow-runs/{run.id}",
        headers=seed_b.manager_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_RUN_NOT_FOUND"


async def test_cancel_queued_workflow_run_writes_audit(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_tenant(session, "wf-cancel")
    run = build_run(seed)
    session.add(run)
    await session.flush()

    response = await client.post(
        f"/api/v1/workflow-runs/{run.id}/cancel",
        json={"note": "wrong attachment"},
        headers=seed.manager_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["finished_at"] is not None

    await session.refresh(run)
    assert run.status == "CANCELLED"
    assert run.finished_at is not None

    audit = await client.get(
        "/api/v1/audit-logs",
        params={"resource_type": "WORKFLOW_RUN", "resource_id": str(run.id)},
        headers=seed.manager_headers,
    )
    assert audit.status_code == 200, audit.text
    entries = audit.json()["data"]
    assert len(entries) == 1
    assert entries[0]["action"] == "workflow.cancel"
    assert entries[0]["metadata"]["previous_status"] == "QUEUED"
    assert entries[0]["metadata"]["note"] == "wrong attachment"


async def test_cancel_running_workflow_run(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_tenant(session, "wf-cancel-running")
    run = build_run(seed, status="RUNNING", started_at=datetime.now(UTC))
    session.add(run)
    await session.flush()

    response = await client.post(
        f"/api/v1/workflow-runs/{run.id}/cancel",
        headers=seed.manager_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "CANCELLED"


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED", "CANCELLED"])
async def test_cancel_finished_workflow_run_returns_conflict(
    client: AsyncClient, session: AsyncSession, status: str
) -> None:
    seed = await seed_tenant(session, f"wf-cancel-{status.lower()}")
    run = build_run(seed, status=status, finished_at=datetime.now(UTC))
    session.add(run)
    await session.flush()

    response = await client.post(
        f"/api/v1/workflow-runs/{run.id}/cancel",
        headers=seed.manager_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_WORKFLOW_STATUS"


async def test_cancel_requires_cancel_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_tenant(session, "wf-permission")
    run = build_run(seed)
    session.add(run)
    await session.flush()

    readable = await client.get(
        f"/api/v1/workflow-runs/{run.id}",
        headers=seed.viewer_headers,
    )
    assert readable.status_code == 200

    response = await client.post(
        f"/api/v1/workflow-runs/{run.id}/cancel",
        headers=seed.viewer_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_cancel_workflow_run_is_scoped_to_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed_a = await seed_tenant(session, "wf-cancel-tenant-a")
    seed_b = await seed_tenant(session, "wf-cancel-tenant-b")
    await set_tenant_context(session, seed_a.tenant.id)
    run = build_run(seed_a)
    session.add(run)
    await session.flush()

    response = await client.post(
        f"/api/v1/workflow-runs/{run.id}/cancel",
        headers=seed_b.manager_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_RUN_NOT_FOUND"
    await set_tenant_context(session, seed_a.tenant.id)
    refreshed = await session.scalar(select(WorkflowRun.status).where(WorkflowRun.id == run.id))
    assert refreshed == "QUEUED"
