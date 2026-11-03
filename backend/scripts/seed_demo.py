"""Create idempotent demo accounts for local development.

Creates a demo tenant with an OWNER account and a VIEWER account so the
permission-filtered navigation can be exercised. Passwords are reset on
every run. Never use these credentials outside local development.

Usage:
    uv run python scripts/seed_demo.py
    uv run python scripts/seed_demo.py --password 'Another-Pass1'
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import SessionFactory
from app.db.tenant import set_tenant_context
from app.models.tenant import Tenant, TenantMembership, User

DEMO_SLUG = "demo"
DEMO_TENANT_NAME = "示例紧固件出口有限公司"
DEMO_PASSWORD = "Demo1234!"
DEMO_ACCOUNTS = (
    ("demo@example.com", "演示账号", "OWNER"),
    ("viewer@example.com", "只读成员", "VIEWER"),
)


async def _ensure_account(
    session: AsyncSession,
    *,
    tenant: Tenant,
    email: str,
    display_name: str,
    role_code: str,
    password: str,
) -> None:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = hash_password(password)
        user.status = "ACTIVE"

    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant.id,
            TenantMembership.user_id == user.id,
        )
    )
    if membership is None:
        session.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role_code=role_code,
                status="ACTIVE",
            )
        )
    else:
        membership.role_code = role_code
        membership.status = "ACTIVE"


async def seed(password: str) -> None:
    async with SessionFactory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        if tenant is None:
            tenant = Tenant(name=DEMO_TENANT_NAME, slug=DEMO_SLUG, plan_code="starter")
            session.add(tenant)
            await session.flush()
        await set_tenant_context(session, tenant.id)

        for email, display_name, role_code in DEMO_ACCOUNTS:
            await _ensure_account(
                session,
                tenant=tenant,
                email=email,
                display_name=display_name,
                role_code=role_code,
                password=password,
            )

        await session.commit()

    print(f"tenant_slug={DEMO_SLUG}")
    print(f"password={password}")
    for email, _, role_code in DEMO_ACCOUNTS:
        print(f"account={email} role={role_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", default=DEMO_PASSWORD, help="demo account password")
    args = parser.parse_args()
    asyncio.run(seed(args.password))


if __name__ == "__main__":
    main()
