import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings
from .credential_crypto import CredentialConfigurationError


AAD = b"ai-infraops:middleware-password:v1"
DERIVATION_INFO = b"ai-infraops:middleware-password-key:v1"


def encrypt_middleware_password(password: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(
        nonce, password.encode("utf-8"), AAD
    )
    return ciphertext, nonce


def decrypt_middleware_password(ciphertext: bytes, nonce: bytes) -> str:
    keys = [_encryption_key()]
    if (
        settings.middleware_credential_encryption_key.strip()
        and settings.k8s_credential_encryption_key.strip()
    ):
        legacy_key = _derived_k8s_key(settings.k8s_credential_encryption_key.strip())
        if legacy_key != keys[0]:
            keys.append(legacy_key)
    for key in keys:
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, AAD)
            return plaintext.decode("utf-8")
        except InvalidTag:
            continue
    raise ValueError("中间件密码解密失败，请检查凭证加密密钥")


def _encryption_key() -> bytes:
    middleware_key = settings.middleware_credential_encryption_key.strip()
    encoded_key = middleware_key or settings.k8s_credential_encryption_key.strip()
    if not encoded_key:
        raise CredentialConfigurationError(
            "缺少 MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY"
        )
    try:
        key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))
    except (ValueError, TypeError) as exc:
        raise CredentialConfigurationError(
            "MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY 不是有效 Base64"
        ) from exc
    if len(key) != 32:
        raise CredentialConfigurationError(
            "MIDDLEWARE_CREDENTIAL_ENCRYPTION_KEY 解码后必须为 32 字节"
        )
    if middleware_key:
        return key
    return _derive_key(key)


def _derived_k8s_key(encoded_key: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))
    except (ValueError, TypeError) as exc:
        raise CredentialConfigurationError(
            "K8S_CREDENTIAL_ENCRYPTION_KEY 不是有效 Base64"
        ) from exc
    if len(key) != 32:
        raise CredentialConfigurationError(
            "K8S_CREDENTIAL_ENCRYPTION_KEY 解码后必须为 32 字节"
        )
    return _derive_key(key)


def _derive_key(key: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=DERIVATION_INFO,
    ).derive(key)
