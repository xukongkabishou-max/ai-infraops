import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import yaml

from .config import settings


AAD = b"ai-infraops:k8s-kubeconfig:v1"


class CredentialConfigurationError(RuntimeError):
    pass


def encrypt_credential(content: str) -> tuple[bytes, bytes, str]:
    plaintext = content.encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, plaintext, AAD)
    fingerprint = hashlib.sha256(plaintext).hexdigest()
    return ciphertext, nonce, fingerprint


def decrypt_credential(ciphertext: bytes, nonce: bytes) -> str:
    plaintext = AESGCM(_encryption_key()).decrypt(nonce, ciphertext, AAD)
    return plaintext.decode("utf-8")


def validate_kubeconfig(content: str) -> None:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("K8S 凭证文件不是有效 YAML") from exc
    if not isinstance(document, dict) or document.get("apiVersion") != "v1":
        raise ValueError("K8S 凭证文件缺少 apiVersion: v1")
    if not document.get("clusters") or not document.get("contexts") or not document.get("users"):
        raise ValueError("K8S 凭证文件缺少 clusters、contexts 或 users")


def _encryption_key() -> bytes:
    encoded_key = settings.k8s_credential_encryption_key.strip()
    if not encoded_key:
        raise CredentialConfigurationError("缺少 K8S_CREDENTIAL_ENCRYPTION_KEY")
    try:
        key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))
    except ValueError as exc:
        raise CredentialConfigurationError("K8S_CREDENTIAL_ENCRYPTION_KEY 不是有效 Base64") from exc
    if len(key) != 32:
        raise CredentialConfigurationError("K8S_CREDENTIAL_ENCRYPTION_KEY 解码后必须为 32 字节")
    return key
