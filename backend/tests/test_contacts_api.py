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
from app.models.customer import Contact, Customer
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
class ContactSeed:
    tenant: Tenant
    other_tenant: Tenant
    customer: Customer
    other_customer: Customer
    other_contact: Contact
    rep_headers: dict[str, str]
    viewer_headers: dict[str, str]
    other_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_contacts(session: AsyncSession, slug: str) -> ContactSeed:
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
    customer = Customer(tenant_id=tenant.id, company_name="Fastener Buyer GmbH")
    session.add_all([rep_membership, viewer_membership, customer])
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_customer = Customer(tenant_id=other_tenant.id, company_name="Other Buyer")
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_REP"
    )
    session.add_all([other_customer, other_membership])
    await session.flush()
    other_contact = Contact(
        tenant_id=other_tenant.id,
        customer_id=other_customer.id,
        name="Other Contact",
        email="other.contact@example.com",
    )
    session.add(other_contact)
    await session.flush()

    await set_tenant_context(session, tenant.id)
    return ContactSeed(
        tenant=tenant,
        other_tenant=other_tenant,
        customer=customer,
        other_customer=other_customer,
        other_contact=other_contact,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def create_contact(
    client: AsyncClient,
    seed: ContactSeed,
    *,
    name: str,
    is_primary: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        json={"name": name, "is_primary": is_primary, **fields},
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_and_list_contacts(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_contacts(session, "contacts-list")

    primary = await create_contact(
        client,
        seed,
        name="  Alice Chen  ",
        is_primary=True,
        email="Alice@Example.COM",
        phone="+86 138 0000 0000",
        language="EN-US",
        job_title="Purchasing Manager",
    )
    secondary = await create_contact(client, seed, name="Bob Li", email="bob@example.com")

    assert primary["name"] == "Alice Chen"
    assert primary["email"] == "alice@example.com"
    assert primary["language"] == "en-us"
    assert primary["is_primary"] is True

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        headers=seed.viewer_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2
    assert [item["id"] for item in body["data"]] == [primary["id"], secondary["id"]]


async def test_new_primary_unsets_previous_contact(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_contacts(session, "contacts-primary")

    first = await create_contact(client, seed, name="First", is_primary=True)
    second = await create_contact(client, seed, name="Second", is_primary=True)

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        headers=seed.rep_headers,
    )
    primary_ids = [item["id"] for item in response.json()["data"] if item["is_primary"]]
    assert primary_ids == [second["id"]]

    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/contacts/{first['id']}",
        json={"is_primary": True},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["is_primary"] is True

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        headers=seed.rep_headers,
    )
    primary_ids = [item["id"] for item in response.json()["data"] if item["is_primary"]]
    assert primary_ids == [first["id"]]


async def test_update_contact_allows_clearing_optional_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_contacts(session, "contacts-update")
    contact = await create_contact(
        client,
        seed,
        name="Alice",
        email="alice@example.com",
        phone="12345",
        language="en",
    )

    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/contacts/{contact['id']}",
        json={"email": None, "phone": "", "language": "DE", "job_title": "Buyer"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["email"] is None
    assert data["phone"] is None
    assert data["language"] == "de"
    assert data["job_title"] == "Buyer"

    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/contacts/{contact['id']}",
        json={"name": None},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_contact_validation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_contacts(session, "contacts-validation")

    for payload in (
        {"name": "   "},
        {"name": "Alice", "email": "not-an-email"},
        {"name": "Alice", "language": "english"},
    ):
        response = await client.post(
            f"/api/v1/customers/{seed.customer.id}/contacts",
            json=payload,
            headers=seed.rep_headers,
        )
        assert response.status_code == 422, response.text

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/contacts",
    )
    assert response.status_code == 401


async def test_contact_tenant_isolation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_contacts(session, "contacts-isolation")

    response = await client.get(
        f"/api/v1/customers/{seed.other_customer.id}/contacts",
        headers=seed.rep_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"

    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/contacts/{seed.other_contact.id}",
        json={"name": "Hijacked"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONTACT_NOT_FOUND"


async def test_contact_rbac(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_contacts(session, "contacts-rbac")

    response = await client.post(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        json={"name": "Viewer Created"},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    contact = await create_contact(client, seed, name="Rep Created")
    response = await client.patch(
        f"/api/v1/customers/{seed.customer.id}/contacts/{contact['id']}",
        json={"job_title": "Director"},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403

    response = await client.get(
        f"/api/v1/customers/{seed.customer.id}/contacts",
        headers=seed.other_headers,
    )
    assert response.status_code == 404
