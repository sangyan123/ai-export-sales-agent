import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant, TenantMembership, User

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
class FollowupSeed:
    tenant: Tenant
    other_tenant: Tenant
    rep: User
    manager: User
    other_user: User
    customer: Customer
    other_customer: Customer
    inquiry: Inquiry
    inquiry_other_customer: Inquiry
    other_customer_other_tenant: Customer
    rep_headers: dict[str, str]
    manager_headers: dict[str, str]
    viewer_headers: dict[str, str]
    other_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_followups(session: AsyncSession, slug: str) -> FollowupSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Rep")
    manager = User(
        email=f"manager@{slug}.example", password_hash=PASSWORD_HASH, display_name="Manager"
    )
    viewer = User(
        email=f"viewer@{slug}.example", password_hash=PASSWORD_HASH, display_name="Viewer"
    )
    other_user = User(
        email=f"other@{slug}.example", password_hash=PASSWORD_HASH, display_name="Other"
    )
    session.add_all([rep, manager, viewer, other_user])
    await session.flush()

    await set_tenant_context(session, tenant.id)
    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="SALES_REP")
    manager_membership = TenantMembership(
        tenant_id=tenant.id, user_id=manager.id, role_code="SALES_MANAGER"
    )
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    customer = Customer(tenant_id=tenant.id, company_name="Fastener Buyer GmbH")
    other_customer = Customer(tenant_id=tenant.id, company_name="Second Buyer")
    session.add_all(
        [rep_membership, manager_membership, viewer_membership, customer, other_customer]
    )
    await session.flush()

    inquiry = Inquiry(
        tenant_id=tenant.id,
        customer_id=customer.id,
        subject="RFQ - hex bolts",
        source_type="MANUAL",
        status="QUOTE_APPROVED",
    )
    inquiry_other_customer = Inquiry(
        tenant_id=tenant.id,
        customer_id=other_customer.id,
        subject="RFQ - washers",
        source_type="MANUAL",
        status="RECEIVED",
    )
    session.add_all([inquiry, inquiry_other_customer])
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_customer_other_tenant = Customer(
        tenant_id=other_tenant.id, company_name="Other Tenant Buyer"
    )
    session.add(other_customer_other_tenant)
    await session.flush()
    other_inquiry = Inquiry(
        tenant_id=other_tenant.id,
        customer_id=other_customer_other_tenant.id,
        subject="Other tenant RFQ",
        source_type="MANUAL",
        status="RECEIVED",
    )
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_REP"
    )
    session.add_all([other_inquiry, other_membership])
    await session.flush()

    await set_tenant_context(session, tenant.id)
    return FollowupSeed(
        tenant=tenant,
        other_tenant=other_tenant,
        rep=rep,
        manager=manager,
        other_user=other_user,
        customer=customer,
        other_customer=other_customer,
        inquiry=inquiry,
        inquiry_other_customer=inquiry_other_customer,
        other_customer_other_tenant=other_customer_other_tenant,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        manager_headers=_bearer(tenant, manager, manager_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def create_followup(
    client: AsyncClient,
    seed: FollowupSeed,
    *,
    customer_id: uuid.UUID | None = None,
    inquiry_id: uuid.UUID | None = None,
    title: str = "Follow up with buyer",
    due_at: datetime | None = None,
    assigned_to: uuid.UUID | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "customer_id": str(customer_id or seed.customer.id),
        "title": title,
        "due_at": (due_at or datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    if inquiry_id is not None:
        payload["inquiry_id"] = str(inquiry_id)
    if assigned_to is not None:
        payload["assigned_to"] = str(assigned_to)
    response = await client.post(
        "/api/v1/followups",
        json=payload,
        headers=headers or seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_followup_defaults(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_followups(session, "followup-create")

    data = await create_followup(client, seed)

    assert data["customer_id"] == str(seed.customer.id)
    assert data["inquiry_id"] is None
    assert data["status"] == "PENDING"
    assert data["source"] == "MANUAL"
    assert data["assigned_to"] == str(seed.rep.id)
    assert data["completed_at"] is None

    response = await client.get("/api/v1/followups", headers=seed.viewer_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == data["id"]


async def test_create_followup_with_inquiry_and_assignee(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_followups(session, "followup-linked")

    data = await create_followup(
        client,
        seed,
        inquiry_id=seed.inquiry.id,
        assigned_to=seed.manager.id,
    )

    assert data["inquiry_id"] == str(seed.inquiry.id)
    assert data["assigned_to"] == str(seed.manager.id)


async def test_create_followup_validation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_followups(session, "followup-validation")

    response = await client.post(
        "/api/v1/followups",
        json={
            "customer_id": str(seed.customer.id),
            "inquiry_id": str(seed.inquiry_other_customer.id),
            "title": "Wrong customer",
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FOLLOWUP_CUSTOMER_MISMATCH"

    response = await client.post(
        "/api/v1/followups",
        json={
            "customer_id": str(seed.customer.id),
            "title": "Non member",
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "assigned_to": str(seed.other_user.id),
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_MEMBER"

    response = await client.post(
        "/api/v1/followups",
        json={
            "customer_id": str(seed.customer.id),
            "title": "Naive due date",
            "due_at": "2026-12-01T10:00:00",
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_list_followups_filters(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_followups(session, "followup-filters")
    now = datetime.now(UTC)

    overdue = await create_followup(
        client,
        seed,
        inquiry_id=seed.inquiry.id,
        title="Overdue task",
        due_at=now - timedelta(days=1),
    )
    future = await create_followup(
        client,
        seed,
        title="Future task",
        due_at=now + timedelta(days=1),
        assigned_to=seed.manager.id,
    )
    done = await create_followup(
        client,
        seed,
        customer_id=seed.other_customer.id,
        title="Done task",
        due_at=now + timedelta(days=2),
    )
    response = await client.patch(
        f"/api/v1/followups/{done['id']}",
        json={"status": "DONE"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200, response.text

    cases = [
        ({}, 3),
        ({"status": "PENDING"}, 2),
        ({"assigned_to": str(seed.rep.id)}, 2),
        ({"customer_id": str(seed.other_customer.id)}, 1),
        ({"inquiry_id": str(seed.inquiry.id)}, 1),
        ({"overdue": "true"}, 1),
    ]
    for params, expected in cases:
        response = await client.get(
            "/api/v1/followups",
            params=params,
            headers=seed.viewer_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["meta"]["total"] == expected, (params, body)
        assert body["meta"]["page"] == 1

    response = await client.get(
        "/api/v1/followups",
        params={"overdue": "true"},
        headers=seed.viewer_headers,
    )
    assert response.json()["data"][0]["id"] == overdue["id"]
    assert future["id"] != overdue["id"]


async def test_update_followup_status_transitions(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_followups(session, "followup-transitions")
    task = await create_followup(client, seed)
    tomorrow = datetime.now(UTC) + timedelta(days=2)

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"title": "Call buyer", "due_at": tomorrow.isoformat()},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["title"] == "Call buyer"

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": "DONE"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    done = response.json()["data"]
    assert done["status"] == "DONE"
    assert done["completed_at"] is not None

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": "PENDING"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    reopened = response.json()["data"]
    assert reopened["status"] == "PENDING"
    assert reopened["completed_at"] is None

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": "CANCELLED"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": "DONE"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": None},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_update_followup_assignee(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_followups(session, "followup-assignee")
    task = await create_followup(client, seed)

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"assigned_to": str(seed.manager.id)},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["assigned_to"] == str(seed.manager.id)

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"assigned_to": None},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["assigned_to"] is None

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"assigned_to": str(seed.other_user.id)},
        headers=seed.rep_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_MEMBER"


async def test_followup_rbac_and_tenant_isolation(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_followups(session, "followup-rbac")
    task = await create_followup(client, seed)

    response = await client.get("/api/v1/followups", headers=seed.viewer_headers)
    assert response.status_code == 200

    response = await client.post(
        "/api/v1/followups",
        json={
            "customer_id": str(seed.customer.id),
            "title": "Viewer created",
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403

    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"title": "Viewer edit"},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403

    other_task = await create_followup(
        client,
        seed,
        customer_id=seed.other_customer_other_tenant.id,
        title="Other tenant task",
        headers=seed.other_headers,
    )
    response = await client.patch(
        f"/api/v1/followups/{other_task['id']}",
        json={"title": "Hijacked"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FOLLOWUP_NOT_FOUND"


async def test_followup_audit_events(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_followups(session, "followup-audit")
    task = await create_followup(client, seed)
    response = await client.patch(
        f"/api/v1/followups/{task['id']}",
        json={"status": "DONE"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200

    await set_tenant_context(session, seed.tenant.id)
    actions = set(
        await session.scalars(
            select(AuditLog.action).where(
                AuditLog.tenant_id == seed.tenant.id,
                AuditLog.resource_type == "FOLLOWUP",
                AuditLog.resource_id == uuid.UUID(task["id"]),
            )
        )
    )
    assert actions == {"followup.create", "followup.update"}
