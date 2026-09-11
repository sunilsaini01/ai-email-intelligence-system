"""Unit tests for app/core/token_encryption.py (Phase 18)."""

import pytest

from app.core.config import get_settings
from app.core.token_encryption import TokenDecryptionError, decrypt_token, encrypt_token


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_encrypt_then_decrypt_round_trips_to_the_original_value():
    ciphertext = encrypt_token("a-real-refresh-token")
    assert ciphertext != "a-real-refresh-token"
    assert decrypt_token(ciphertext) == "a-real-refresh-token"


def test_ciphertext_is_not_valid_utf8_plaintext_of_the_secret():
    ciphertext = encrypt_token("super-secret-value")
    assert "super-secret-value" not in ciphertext


def test_decrypting_garbage_raises_token_decryption_error():
    with pytest.raises(TokenDecryptionError):
        decrypt_token("not-a-real-fernet-token")


def test_decrypting_with_a_different_key_fails(monkeypatch):
    monkeypatch.setenv("MAILBOX_TOKEN_ENCRYPTION_KEY", "key-one")
    get_settings.cache_clear()
    ciphertext = encrypt_token("a-secret")

    monkeypatch.setenv("MAILBOX_TOKEN_ENCRYPTION_KEY", "key-two")
    get_settings.cache_clear()
    # _fernet() is itself lru_cache'd -- clear that cache too, or this test
    # would silently reuse the first key's Fernet instance.
    from app.core.token_encryption import _fernet

    _fernet.cache_clear()

    with pytest.raises(TokenDecryptionError):
        decrypt_token(ciphertext)
