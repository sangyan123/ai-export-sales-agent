import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.tenant import Tenant, TenantMembership, User
from app.products import importer

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = [
    "产品编码",
    "产品名称",
    "产品类别",
    "标准号",
    "材质",
    "等级",
    "直径",
    "长度",
    "螺距",
    "头型",
    "驱动类型",
    "表面处理",
    "计价单位",
    "MOQ",
]
FIELDS = [
    "product_code",
    "product_name",
    "category",
    "standard_code",
    "material",
    "grade",
    "diameter",
    "length",
    "thread_pitch",
    "head_type",
    "drive_type",
    "surface_finish",
    "sales_unit",
    "moq",
]


@dataclass(frozen=True)
class Account:
    tenant: Tenant
    user: User
    headers: dict[str, str]


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


async def seed_account(
    session: AsyncSession, slug: str, role_code: str = "SALES_MANAGER"
) -> Account:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    user = User(email=f"user@{slug}.example", password_hash=PASSWORD_HASH, display_name="Sales Rep")
    session.add(user)
    await session.flush()
    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role_code=role_code)
    session.add(membership)
    await session.flush()
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
    )
    return Account(
        tenant=tenant,
        user=user,
        headers={"Authorization": f"Bearer {token}"},
    )


def workbook_bytes(rows: list[tuple], headers: list[str] = HEADERS) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def product_row(**overrides) -> tuple:
    values = {
        "product_code": "BOLT-IMPORT-M8",
        "product_name": "Hex bolt M8x30 SS304",
        "category": "BOLT",
        "standard_code": "DIN 933",
        "material": "SS304",
        "grade": None,
        "diameter": "M8",
        "length": "30mm",
        "thread_pitch": None,
        "head_type": "HEX",
        "drive_type": None,
        "surface_finish": "Plain",
        "sales_unit": "PCS",
        "moq": 1000,
    }
    values.update(overrides)
    return tuple(values[field] for field in FIELDS)


async def upload(
    client: AsyncClient, account: Account, data: bytes, filename: str = "products.xlsx"
):
    return await client.post(
        "/api/v1/products/imports",
        files={"file": (filename, data, XLSX_MEDIA_TYPE)},
        headers=account.headers,
    )


async def list_products(client: AsyncClient, account: Account) -> list[dict]:
    response = await client.get(
        "/api/v1/products", params={"page": 1, "page_size": 100}, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_download_import_template(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-template", role_code="VIEWER")

    response = await client.get("/api/v1/products/import-template", headers=account.headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(XLSX_MEDIA_TYPE)
    workbook = load_workbook(BytesIO(response.content))
    headers = [cell.value for cell in workbook.active[1]]
    assert headers == HEADERS
    assert "填写说明" in workbook.sheetnames


async def test_import_products_success(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-success")
    data = workbook_bytes(
        [
            product_row(),
            product_row(
                product_code="NUT-IMPORT-M8",
                product_name="Hex nut M8",
                category="螺母",
                sales_unit="PCS",
                moq="500",
            ),
        ]
    )

    response = await upload(client, account, data)

    assert response.status_code == 201, response.text
    job = response.json()["data"]
    assert job["status"] == "SUCCEEDED"
    assert job["filename"] == "products.xlsx"
    assert job["total_rows"] == 2
    assert job["imported"] == 2
    assert job["failed"] == 0
    assert job["errors"] == []

    detail = await client.get(f"/api/v1/products/imports/{job['id']}", headers=account.headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "SUCCEEDED"
    assert detail.json()["data"]["imported"] == 2

    products = await list_products(client, account)
    by_code = {product["product_code"]: product for product in products}
    assert set(by_code) == {"BOLT-IMPORT-M8", "NUT-IMPORT-M8"}
    assert by_code["NUT-IMPORT-M8"]["category"] == "NUT"
    assert Decimal(by_code["NUT-IMPORT-M8"]["moq"]) == Decimal("500")
    assert by_code["BOLT-IMPORT-M8"]["moq"] == "1000.0000"


async def test_import_accepts_english_headers(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-english")
    headers = ["product_code", "product_name", "category", "sales_unit"]
    data = workbook_bytes([("SCREW-1", "Self tapping screw", "SCREW", "PCS")], headers=headers)

    response = await upload(client, account, data)

    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "SUCCEEDED"
    products = await list_products(client, account)
    assert [product["product_code"] for product in products] == ["SCREW-1"]


async def test_import_rolls_back_on_invalid_row(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-invalid")
    data = workbook_bytes(
        [
            product_row(),
            product_row(product_code="BOLT-BAD", category="BOLT!", moq=-5),
        ]
    )

    response = await upload(client, account, data)

    assert response.status_code == 201, response.text
    job = response.json()["data"]
    assert job["status"] == "FAILED"
    assert job["error_code"] == "IMPORT_VALIDATION_FAILED"
    assert job["imported"] == 0
    assert job["failed"] == 1
    codes = {(error["row"], error["code"]) for error in job["errors"]}
    assert (3, "INVALID_CATEGORY") in codes
    assert (3, "INVALID_MOQ") in codes
    assert await list_products(client, account) == []


async def test_import_rejects_existing_product_code(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "import-existing")
    created = await client.post(
        "/api/v1/products",
        json={
            "product_code": "BOLT-IMPORT-M8",
            "product_name": "Existing bolt",
            "category": "BOLT",
            "sales_unit": "PCS",
        },
        headers=account.headers,
    )
    assert created.status_code == 201, created.text

    response = await upload(client, account, workbook_bytes([product_row()]))

    assert response.status_code == 201, response.text
    job = response.json()["data"]
    assert job["status"] == "FAILED"
    assert job["imported"] == 0
    assert job["errors"][0]["code"] == "PRODUCT_CODE_EXISTS"
    assert job["errors"][0]["row"] == 2
    assert len(await list_products(client, account)) == 1


async def test_import_rejects_duplicate_codes_in_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "import-duplicate")
    data = workbook_bytes([product_row(), product_row(product_name="Second bolt with same code")])

    response = await upload(client, account, data)

    assert response.status_code == 201, response.text
    job = response.json()["data"]
    assert job["status"] == "FAILED"
    assert job["failed"] == 2
    assert {error["code"] for error in job["errors"]} == {"DUPLICATE_PRODUCT_CODE"}
    assert {error["row"] for error in job["errors"]} == {2, 3}
    assert await list_products(client, account) == []


async def test_import_rejects_unsupported_file(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-suffix")

    response = await upload(client, account, b"product_code,product_name", filename="products.csv")

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "IMPORT_FILE_UNSUPPORTED"


async def test_import_rejects_missing_required_columns(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "import-columns")
    data = workbook_bytes([("BOLT-1", "Hex bolt")], headers=["产品编码", "产品名称"])

    response = await upload(client, account, data)

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "IMPORT_TEMPLATE_INVALID"
    assert "产品类别" in error["message"]
    assert "计价单位" in error["message"]


async def test_import_rejects_empty_workbook(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-empty")

    response = await upload(client, account, workbook_bytes([]))

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "IMPORT_EMPTY"


async def test_import_rejects_too_many_rows(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = await seed_account(session, "import-too-many")
    monkeypatch.setattr(importer, "MAX_ROWS", 1)
    data = workbook_bytes([product_row(), product_row(product_code="BOLT-IMPORT-M10")])

    response = await upload(client, account, data)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "IMPORT_TOO_MANY_ROWS"


async def test_import_requires_import_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "import-forbidden", role_code="SALES_REP")

    response = await upload(client, account, workbook_bytes([product_row()]))
    template = await client.get("/api/v1/products/import-template", headers=account.headers)

    assert response.status_code == 403, response.text
    assert template.status_code == 200, template.text


async def test_import_job_not_found(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "import-missing")

    response = await client.get(f"/api/v1/products/imports/{uuid.uuid4()}", headers=account.headers)

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "PRODUCT_IMPORT_NOT_FOUND"
