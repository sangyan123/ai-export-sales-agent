import os
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.customer import Customer, CustomerNote
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
class NoteSeed:
    tenant: Tenant
    customer: Customer
    rep_headers: dict[str, str]
    viewer_headers: dict[str, str]
    other_headers: dict[str, str]
    other_customer: Customer


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_notes(session: AsyncSession, slug: str) -> NoteSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Rep")
    viewer = User(
        email=f"viewer@{slug}.example", password_hash=PASSWORD_HASH, display_name="Viewer"
    )
    other_user = User(
        email=f"other@{slug}.example", password_hash=PASSWORD_HASH, display_name="Other"
    )
    session.add_all([rep, viewer, other_user])
    await session.flush()

    await set_tenant_context(session, tenant.id)
    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="SALES_REP")
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    customer = Customer(tenant_id=tenant.id, company_name="Note Buyer GmbH")
    session.add_all([rep_membership, viewer_membership, customer])
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_REP"
    )
    other_customer = Customer(tenant_id=other_tenant.id, company_name="Other Buyer")
    session.add_all([other_membership, other_customer])
    await session.flush()

    return NoteSeed(
        tenant=tenant,
        customer=customer,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
        other_customer=other_customer,
    )


async def create_note(
    client: AsyncClient,
    seed: NoteSeed,
    *,
    content: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/customers/{seed.customer.id}/notes",
        json={"content": content},
        headers=headers or seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_and_list_notes_chronological(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-list")

    first = await create_note(client, seed, content="First contact via email")
    second = await create_note(client, seed, content="  Quoted M8 bolts, waiting for reply  ")

    assert first["content"] == "First contact via email"
    assert second["content"] == "Quoted M8 bolts, waiting for reply"
    assert first["author_id"] is not None

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/notes",
        headers=seed.viewer_headers,
    )
    assert response.status_code == 200
    body = response.json()
    items = body["data"]
    assert body["total"] == 2
    assert len(items) == 2
    assert items[0]["content"] == "Quoted M8 bolts, waiting for reply"
    assert items[1]["content"] == "First contact via email"


async def test_viewer_cannot_create_note(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-viewer-deny")

    response = await client.post(
        f"/api/v1/customers/{seed.customer.id}/notes",
        json={"content": "should fail"},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403


async def test_update_note(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-update")

    note = await create_note(client, seed, content="Original content")
    note_id = note["id"]

    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/notes/{note_id}",
        json={"content": "Updated content"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    updated = response.json()["data"]
    assert updated["content"] == "Updated content"
    assert updated["id"] == note_id


async def test_delete_note(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-delete")

    note = await create_note(client, seed, content="To be deleted")
    note_id = note["id"]

    response = await client.delete(
        f"/api/v1/customers/{seed.customer.id}/notes/{note_id}",
        headers=seed.rep_headers,
    )
    assert response.status_code == 204

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/notes",
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_cross_tenant_note_not_visible(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-tenant-isolation")

    note = await create_note(client, seed, content="Private note")

    response = await client.get(
        f"/api/v1/customers/{seed.other_customer.id}/notes/{note['id']}",
        headers=seed.other_headers,
    )
    assert response.status_code in (403, 404)

    patch_response = await client.patch(
        f"/api/v1/customers/{seed.other_customer.id}/notes/{note['id']}",
        json={"content": "hijack"},
        headers=seed.other_headers,
    )
    assert patch_response.status_code in (403, 404)


async def test_note_content_validation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_notes(session, "notes-validation")

    for bad_content in ("", "   ", "x" * 5001):
        response = await client.post(
            f"/api/v1/customers/{seed.customer.id}/notes",
            json={"content": bad_content},
            headers=seed.rep_headers,
        )
        assert response.status_code == 422, f"expected 422 for content={bad_content!r}"
