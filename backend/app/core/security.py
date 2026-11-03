import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

ALGORITHM = "HS256"

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class AccessTokenError(Exception):
    pass


class AccessTokenExpired(AccessTokenError):
    pass


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    jti: str


def _signing_key() -> str:
    return settings.jwt_secret_key or settings.app_secret_key


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy_password(password: str) -> None:
    """Burn the same hashing cost for unknown accounts to limit timing leaks."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        pass


def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    ttl_seconds: int | None = None,
) -> str:
    now = datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "mid": str(membership_id),
        "typ": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "tid", "mid", "jti", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AccessTokenExpired from exc
    except jwt.InvalidTokenError as exc:
        raise AccessTokenError from exc

    if payload.get("typ") != "access":
        raise AccessTokenError
    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            membership_id=uuid.UUID(payload["mid"]),
            jti=str(payload["jti"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AccessTokenError from exc


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    return raw_token, hash_refresh_token(raw_token)
