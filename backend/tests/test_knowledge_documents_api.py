import os
import uuid
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.main import app
from app.models.product import KnowledgeDocument
from app.models.tenant import Tenant, TenantMembership, User
from app.storage import get_storage

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
class KnowledgeSeed:
    tenant: Tenant
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


async def seed_knowledge(session: AsyncSession, slug: str) -> KnowledgeSeed:
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

    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="SALES_MANAGER")
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_MANAGER"
    )
    session.add_all([rep_membership, viewer_membership, other_membership])
    await session.flush()

    return KnowledgeSeed(
        tenant=tenant,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def test_upload_and_list_documents(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-upload")

    upload = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("catalog.pdf", b"fake pdf content", "application/pdf")},
        data={"source": "CATALOG", "description": "Product catalog 2026"},
        headers=seed.rep_headers,
    )
    assert upload.status_code == 201, upload.text
    doc = upload.json()["data"]
    assert doc["filename"] == "catalog.pdf"
    assert doc["source"] == "CATALOG"
    assert doc["parse_status"] == "UPLOADED"
    assert doc["size_bytes"] == len(b"fake pdf content")
    assert doc["checksum"] is not None

    listing = await client.get(
        "/api/v1/knowledge-documents",
        headers=seed.rep_headers,
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == doc["id"]


async def test_upload_rejects_unsupported_extension(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_knowledge(session, "knowledge-ext")

    response = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("malware.exe", b"binary", "application/octet-stream")},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_upload_rejects_empty_file(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-empty")

    response = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_viewer_cannot_upload(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-viewer-deny")

    response = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("catalog.pdf", b"content", "application/pdf")},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403


async def test_delete_document(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-delete")

    upload = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("catalog.pdf", b"content", "application/pdf")},
        headers=seed.rep_headers,
    )
    doc_id = upload.json()["data"]["id"]

    delete = await client.delete(
        f"/api/v1/knowledge-documents/{doc_id}",
        headers=seed.rep_headers,
    )
    assert delete.status_code == 204

    listing = await client.get("/api/v1/knowledge-documents", headers=seed.rep_headers)
    assert listing.json()["meta"]["total"] == 0


async def test_tenant_isolation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-isolation")

    upload = await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("secret.pdf", b"secret content", "application/pdf")},
        headers=seed.rep_headers,
    )
    doc_id = upload.json()["data"]["id"]

    listing = await client.get(
        "/api/v1/knowledge-documents",
        headers=seed.other_headers,
    )
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 0

    delete = await client.delete(
        f"/api/v1/knowledge-documents/{doc_id}",
        headers=seed.other_headers,
    )
    assert delete.status_code == 404


async def test_filter_by_source_and_search(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_knowledge(session, "knowledge-filter")

    await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("catalog.pdf", b"a", "application/pdf")},
        data={"source": "CATALOG"},
        headers=seed.rep_headers,
    )
    await client.post(
        "/api/v1/knowledge-documents/upload",
        files={"file": ("price-list.xlsx", b"b", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"source": "PRICE_LIST"},
        headers=seed.rep_headers,
    )

    filtered = await client.get(
        "/api/v1/knowledge-documents",
        params={"source": "PRICE_LIST"},
        headers=seed.rep_headers,
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["source"] == "PRICE_LIST"

    searched = await client.get(
        "/api/v1/knowledge-documents",
        params={"q": "catalog"},
        headers=seed.rep_headers,
    )
    assert searched.status_code == 200
    assert searched.json()["meta"]["total"] == 1
    assert searched.json()["data"][0]["filename"] == "catalog.pdf"
