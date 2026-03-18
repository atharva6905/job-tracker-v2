import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError("TOKEN_ENCRYPTION_KEY environment variable is not set")
    return Fernet(key.encode())


def encrypt_token(token: str) -> str:
    """Encrypt a plaintext token and return as a base64 string."""
    try:
        return _get_fernet().encrypt(token.encode()).decode()
    except Exception as exc:
        raise ValueError(f"Failed to encrypt token: {exc}") from exc


def decrypt_token(encrypted: str) -> str:
    """Decrypt an encrypted token and return the plaintext string."""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt token: invalid or corrupted data") from exc
    except Exception as exc:
        raise ValueError(f"Failed to decrypt token: {exc}") from exc
