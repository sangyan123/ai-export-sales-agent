import os
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
from app.models.email import EmailDraft
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.quote import Quote, QuoteItem
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)

PRODUCT_SNAPSHOT = {
    "product_code": "BOLT-EXT",
    "product_name": "Hex bolt SS316 M8x50",
    "category": "BOLT",
    "standard_code": "DIN 933",
    "material": "SS316",
    "grade": "8.8",
    "diameter": "M8",
    "length": "50mm",
    "thread_pitch": None,
    "head_type": "HEX",
    "drive_type": None,
    "surface_finish": "PLAIN",
    "sales_unit": "PCS",
    "moq": "1000",
    "packaging": None,
    "attributes": {},
}


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
class EmailSeed:
    tenant: Tenant
    other_tenant: Tenant
    customer: Customer
    inquiry: Inquiry
    requirement: InquiryRequirement
    approved_quote: Quote
    latest_quote: Quote
    draft_quote: Quote
    inquiry_without_quote: Inquiry
    other_inquiry: Inquiry
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


def _quote(
    tenant_id: uuid.UUID,
    inquiry_id: uuid.UUID,
    *,
    quote_no: str,
    version_no: int,
    status: str,
    grand_total: str,
) -> Quote:
    total = Decimal(grand_total)
    return Quote(
        tenant_id=tenant_id,
        inquiry_id=inquiry_id,
        quote_no=quote_no,
        version_no=version_no,
        status=status,
        currency="USD",
        subtotal=total,
        subtotal_display=total,
        discount_total=Decimal("0"),
        discount_total_display=Decimal("0"),
        freight_total=Decimal("0"),
        freight_total_display=Decimal("0"),
        other_charges=Decimal("0"),
        other_charges_display=Decimal("0"),
        grand_total=total,
        grand_total_display=total,
        valid_until=date(2026, 12, 31),
        terms_json={
            "incoterm": None,
            "payment_terms": "T/T 30% deposit",
            "lead_time": None,
        },
        source_snapshot_json={},
    )


def _quote_item(tenant_id: uuid.UUID, quote_id: uuid.UUID, line_total: str) -> QuoteItem:
    total = Decimal(line_total)
    return QuoteItem(
        tenant_id=tenant_id,
        quote_id=quote_id,
        line_no=1,
        product_id=None,
        product_snapshot_json=PRODUCT_SNAPSHOT,
        quantity=Decimal("5000"),
        unit="PCS",
        priced_quantity=Decimal("5000"),
        price_unit="PCS",
        price_basis="PER_PIECE",
        unit_price=Decimal("0.1234"),
        unit_price_display=Decimal("0.1234"),
        line_total=total,
        line_total_display=total,
        price_source_ref={},
    )


async def seed_email(session: AsyncSession, slug: str) -> EmailSeed:
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
    session.add_all([rep_membership, manager_membership, viewer_membership])

    customer = Customer(tenant_id=tenant.id, company_name="Fastener Buyer GmbH")
    session.add(customer)
    await session.flush()

    inquiry = Inquiry(
        tenant_id=tenant.id,
        customer_id=customer.id,
        subject="RFQ - hex bolts",
        source_type="MANUAL",
        raw_body="We need 5000 pcs of M8 x 50mm hex bolts in SS316.",
        language="en",
        status="QUOTE_APPROVED",
    )
    inquiry_without_quote = Inquiry(
        tenant_id=tenant.id,
        customer_id=customer.id,
        subject="RFQ - washers",
        source_type="MANUAL",
        status="QUOTE_APPROVED",
    )
    session.add_all([inquiry, inquiry_without_quote])
    await session.flush()

    requirement = InquiryRequirement(
        tenant_id=tenant.id,
        inquiry_id=inquiry.id,
        schema_version=1,
        parsed_json={
            "product_category": {"normalized_value": "BOLT", "confidence": 0.99},
            "material": {"normalized_value": "SS304", "confidence": 0.9},
            "diameter": {"normalized_value": "M8", "confidence": 0.99},
            "quantity": {"normalized_value": "5000", "confidence": 0.99},
            "missing_fields": ["packaging"],
        },
        confirmed_json={"material": "SS316"},
    )
    session.add(requirement)

    approved_quote = _quote(
        tenant.id,
        inquiry.id,
        quote_no="Q-1001",
        version_no=1,
        status="APPROVED",
        grand_total="617.00",
    )
    latest_quote = _quote(
        tenant.id,
        inquiry.id,
        quote_no="Q-1001",
        version_no=2,
        status="APPROVED",
        grand_total="700.00",
    )
    draft_quote = _quote(
        tenant.id,
        inquiry.id,
        quote_no="Q-1001",
        version_no=3,
        status="DRAFT",
        grand_total="650.00",
    )
    session.add_all([approved_quote, latest_quote, draft_quote])
    await session.flush()
    session.add_all(
        [
            _quote_item(tenant.id, approved_quote.id, "617.00"),
            _quote_item(tenant.id, latest_quote.id, "700.00"),
            _quote_item(tenant.id, draft_quote.id, "650.00"),
        ]
    )
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_customer = Customer(tenant_id=other_tenant.id, company_name="Other Buyer")
    session.add(other_customer)
    await session.flush()
    other_inquiry = Inquiry(
        tenant_id=other_tenant.id,
        customer_id=other_customer.id,
        subject="Other tenant RFQ",
        source_type="MANUAL",
        status="QUOTE_APPROVED",
    )
    session.add(other_inquiry)
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_REP"
    )
    session.add(other_membership)
    await session.flush()

    await set_tenant_context(session, tenant.id)
    return EmailSeed(
        tenant=tenant,
        other_tenant=other_tenant,
        customer=customer,
        inquiry=inquiry,
        requirement=requirement,
        approved_quote=approved_quote,
        latest_quote=latest_quote,
        draft_quote=draft_quote,
        inquiry_without_quote=inquiry_without_quote,
        other_inquiry=other_inquiry,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        manager_headers=_bearer(tenant, manager, manager_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def create_draft(
    client: AsyncClient,
    seed: EmailSeed,
    *,
    inquiry_id: uuid.UUID | str | None = None,
    quote_id: uuid.UUID | None = None,
    language: str = "en",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"language": language}
    if quote_id is not None:
        payload["quote_id"] = str(quote_id)
    response = await client.post(
        f"/api/v1/inquiries/{inquiry_id or seed.inquiry.id}/email-drafts",
        json=payload,
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_generate_email_draft_from_latest_approved_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-generate")

    data = await create_draft(client, seed)

    assert data["inquiry_id"] == str(seed.inquiry.id)
    assert data["quote_id"] == str(seed.latest_quote.id)
    assert data["status"] == "DRAFT"
    assert data["language"] == "en"
    assert data["model_id"] == "deterministic-email-generator.v1"
    assert data["subject"] == "Re: RFQ - hex bolts"
    assert "Fastener Buyer GmbH" in data["body"]
    assert "Q-1001 (version 2)" in data["body"]
    assert "Total: USD 700.00" in data["body"]
    assert "- Material: SS316" in data["body"]
    assert "Specifications: Standard DIN 933; Material SS316" in data["body"]
    assert "Incoterm: To be confirmed" in data["body"]
    assert "Incoterm" in data["missing_information"]
    assert "Requirement: Packaging" in data["missing_information"]
    assert "MISSING_INFORMATION" in data["review_flags"]
    assert "quote:Q-1001:v2" in data["claims_used"]
    assert "requirement:material" in data["claims_used"]
    assert data["approved_by"] is None
    assert data["approved_at"] is None

    await set_tenant_context(session, seed.tenant.id)
    stored = await session.scalar(select(EmailDraft).where(EmailDraft.id == uuid.UUID(data["id"])))
    assert stored is not None
    assert stored.claims_json == data["claims_used"]


async def test_generate_email_draft_with_explicit_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-explicit")

    data = await create_draft(client, seed, quote_id=seed.approved_quote.id)

    assert data["quote_id"] == str(seed.approved_quote.id)
    assert "Q-1001 (version 1)" in data["body"]
    assert "Total: USD 617.00" in data["body"]


async def test_generate_rejects_unapproved_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-unapproved")

    response = await client.post(
        f"/api/v1/inquiries/{seed.inquiry.id}/email-drafts",
        json={"quote_id": str(seed.draft_quote.id)},
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_QUOTE_NOT_APPROVED"


async def test_generate_requires_approved_quote(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_email(session, "email-noquote")

    response = await client.post(
        f"/api/v1/inquiries/{seed.inquiry_without_quote.id}/email-drafts",
        json={},
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_QUOTE_NOT_APPROVED"


async def test_generate_rejects_unsupported_language(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-language")

    response = await client.post(
        f"/api/v1/inquiries/{seed.inquiry.id}/email-drafts",
        json={"language": "zh"},
        headers=seed.rep_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMAIL_UNSUPPORTED_LANGUAGE"


async def test_get_draft_and_tenant_isolation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_email(session, "email-get")
    data = await create_draft(client, seed)

    own = await client.get(f"/api/v1/email-drafts/{data['id']}", headers=seed.viewer_headers)
    other = await client.get(f"/api/v1/email-drafts/{data['id']}", headers=seed.other_headers)

    assert own.status_code == 200, own.text
    assert own.json()["data"]["subject"] == data["subject"]
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "EMAIL_DRAFT_NOT_FOUND"


async def test_update_draft_and_validation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_email(session, "email-update")
    data = await create_draft(client, seed)

    updated = await client.patch(
        f"/api/v1/email-drafts/{data['id']}",
        json={"subject": "Updated quotation", "body": "Please find the updated quotation."},
        headers=seed.rep_headers,
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["subject"] == "Updated quotation"
    assert updated.json()["data"]["body"] == "Please find the updated quotation."

    blank = await client.patch(
        f"/api/v1/email-drafts/{data['id']}",
        json={"subject": "   "},
        headers=seed.rep_headers,
    )
    empty = await client.patch(
        f"/api/v1/email-drafts/{data['id']}",
        json={},
        headers=seed.rep_headers,
    )

    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"
    assert empty.status_code == 422


async def test_approved_draft_is_not_editable(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_email(session, "email-approved-edit")
    data = await create_draft(client, seed)
    approved = await client.post(
        f"/api/v1/email-drafts/{data['id']}/approve",
        headers=seed.manager_headers,
    )
    assert approved.status_code == 200, approved.text

    response = await client.patch(
        f"/api/v1/email-drafts/{data['id']}",
        json={"subject": "Changed after approval"},
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_DRAFT_NOT_EDITABLE"


async def test_approve_email_draft_requires_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-approve-rbac")
    data = await create_draft(client, seed)

    denied = await client.post(
        f"/api/v1/email-drafts/{data['id']}/approve",
        headers=seed.rep_headers,
    )
    approved = await client.post(
        f"/api/v1/email-drafts/{data['id']}/approve",
        headers=seed.manager_headers,
    )

    assert denied.status_code == 403
    assert denied.json()["error"]["details"][0]["permission"] == "email:approve"
    assert approved.status_code == 200, approved.text
    body = approved.json()["data"]
    assert body["status"] == "APPROVED"
    assert body["approved_by"] is not None
    assert body["approved_at"] is not None

    await set_tenant_context(session, seed.tenant.id)
    actions = list(
        await session.scalars(
            select(AuditLog.action)
            .where(
                AuditLog.tenant_id == seed.tenant.id,
                AuditLog.resource_type == "EMAIL_DRAFT",
                AuditLog.resource_id == uuid.UUID(data["id"]),
            )
            .order_by(AuditLog.created_at)
        )
    )
    assert actions == ["email.draft.create", "email.draft.approve"]


async def test_approve_rejected_when_quote_not_approved(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_email(session, "email-quote-changed")
    data = await create_draft(client, seed)

    await set_tenant_context(session, seed.tenant.id)
    quote = await session.scalar(select(Quote).where(Quote.id == seed.latest_quote.id))
    assert quote is not None
    quote.status = "SENT"
    await session.flush()

    response = await client.post(
        f"/api/v1/email-drafts/{data['id']}/approve",
        headers=seed.manager_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_QUOTE_NOT_APPROVED"


async def test_viewer_can_read_but_not_generate(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_email(session, "email-viewer")
    data = await create_draft(client, seed)

    read = await client.get(f"/api/v1/email-drafts/{data['id']}", headers=seed.viewer_headers)
    generate = await client.post(
        f"/api/v1/inquiries/{seed.inquiry.id}/email-drafts",
        json={},
        headers=seed.viewer_headers,
    )

    assert read.status_code == 200
    assert generate.status_code == 403
    assert generate.json()["error"]["details"][0]["permission"] == "email:draft"
