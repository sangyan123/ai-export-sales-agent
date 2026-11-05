"""Tests for tenant AI provider configuration API and encryption utilities (no DB)."""

import pytest

from app.core.config import settings
from app.core.encryption import decrypt_api_key, encrypt_api_key, mask_api_key
from app.core.encryption import EncryptionError


def test_encrypt_decrypt_roundtrip() -> None:
    plaintext = "sk-proj-abcdef1234567890"
    ciphertext = encrypt_api_key(plaintext)
    assert ciphertext != plaintext
    assert plaintext not in ciphertext
    assert decrypt_api_key(ciphertext) == plaintext


def test_mask_api_key() -> None:
    assert mask_api_key("sk-proj-abcdef1234567890") == "sk-p...7890"
    assert mask_api_key("short") == "*****"
    assert mask_api_key("") == ""


def test_encrypt_empty_key_raises() -> None:
    with pytest.raises(EncryptionError):
        encrypt_api_key("")


def test_wrong_secret_fails_decryption(monkeypatch: pytest.MonkeyPatch) -> None:
    plaintext = "sk-proj-abcdef1234567890"
    ciphertext = encrypt_api_key(plaintext)
    monkeypatch.setattr(settings, "app_secret_key", "different-secret")
    with pytest.raises(EncryptionError):
        decrypt_api_key(ciphertext)
