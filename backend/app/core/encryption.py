"""API key encryption for tenant AI provider configuration.

Keys are encrypted at rest with Fernet, derived from APP_SECRET_KEY via SHA-256.
The plaintext key is never returned through the API - only a masked hint.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class EncryptionError(Exception):
    pass


def _fernet() -> Fernet:
    secret = settings.app_secret_key.encode("utf-8")
    derived = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_api_key(plaintext: str) -> str:
    if not plaintext:
        raise EncryptionError("cannot encrypt empty API key")
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        plaintext = _fernet().decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "API key cannot be decrypted; APP_SECRET_KEY may have changed"
        ) from exc


def mask_api_key(plaintext: str) -> str:
    if len(plaintext) <= 8:
        return "*" * len(plaintext)
    return f"{plaintext[:4]}...{plaintext[-4:]}"
