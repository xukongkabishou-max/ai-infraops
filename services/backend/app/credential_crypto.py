import base64
import binascii
import hashlib
import os

from cryptography import x509
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
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
    document = _load_kubeconfig(content)
    if not isinstance(document, dict) or document.get("apiVersion") != "v1":
        raise ValueError("K8S 凭证文件缺少 apiVersion: v1")
    if not document.get("clusters") or not document.get("contexts") or not document.get("users"):
        raise ValueError("K8S 凭证文件缺少 clusters、contexts 或 users")
    _validate_inline_client_credentials(document)


def normalize_kubeconfig_tls(content: str, skip_tls_verify: bool) -> str:
    document = _load_kubeconfig(content)
    clusters = document.get("clusters") if isinstance(document, dict) else None
    if not isinstance(clusters, list) or not clusters:
        raise ValueError("K8S 凭证文件缺少 clusters")
    for item in clusters:
        cluster = item.get("cluster") if isinstance(item, dict) else None
        if not isinstance(cluster, dict):
            raise ValueError("K8S 凭证文件的 cluster 配置无效")
        if skip_tls_verify:
            cluster["insecure-skip-tls-verify"] = True
        else:
            cluster.pop("insecure-skip-tls-verify", None)
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def _load_kubeconfig(content: str) -> dict:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("K8S 凭证文件不是有效 YAML") from exc
    if not isinstance(document, dict):
        raise ValueError("K8S 凭证文件必须是 YAML 对象")
    return document


def _validate_inline_client_credentials(document: dict) -> None:
    for item in document.get("users", []):
        if not isinstance(item, dict):
            continue
        user = item.get("user")
        if not isinstance(user, dict):
            continue
        certificate = _decode_inline_data(user, "client-certificate-data")
        private_key = _decode_inline_data(user, "client-key-data")
        parsed_certificate = None
        parsed_private_key = None
        if certificate is not None:
            try:
                parsed_certificate = x509.load_pem_x509_certificate(certificate)
            except ValueError as exc:
                raise ValueError("K8S 客户端证书不是有效 PEM") from exc
        if private_key is not None:
            try:
                parsed_private_key = serialization.load_pem_private_key(
                    private_key,
                    password=None,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("K8S 客户端私钥不是有效 PEM 或需要密码") from exc
        if parsed_certificate is not None and parsed_private_key is not None:
            certificate_key = parsed_certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            private_public_key = parsed_private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            if certificate_key != private_public_key:
                raise ValueError("K8S 客户端证书与私钥不匹配")


def _decode_inline_data(user: dict, field: str) -> bytes | None:
    encoded = user.get(field)
    if not encoded:
        return None
    try:
        return base64.b64decode(str(encoded), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"K8S 凭证字段 {field} 不是有效 Base64") from exc


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
