from urllib.parse import urlsplit, urlunsplit
import re

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    client_type: str = Field(default="user_web", min_length=1, max_length=64)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client_type: str
    expires_in: int
    user: dict
    roles: list[str]
    permissions: list[str]
    menus: list[dict]


class SessionRequest(BaseModel):
    access_token: str = Field(min_length=1, max_length=256)
    client_type: str = Field(min_length=1, max_length=64)


class HostCreateRequest(BaseModel):
    node_exporter_url: str = Field(min_length=1, max_length=512)
    hostname: str = Field(min_length=1, max_length=128)
    public_ip: str = Field(default="", max_length=64)
    private_ip: str = Field(default="", max_length=64)
    environment_code: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    environment_name: str = Field(min_length=1, max_length=128)
    k8s_credential_name: str = Field(default="", max_length=255)
    k8s_credential_content: str = Field(default="", max_length=1_000_000)
    namespace_keys: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("namespace_keys")
    @classmethod
    def validate_namespace_keys(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            namespace = value.strip()
            if not namespace:
                continue
            if len(namespace) > 63 or not re.fullmatch(
                r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?",
                namespace,
            ):
                raise ValueError(f"Namespace Key 格式无效：{namespace}")
            if namespace not in normalized:
                normalized.append(namespace)
        return normalized


class K8sClusterCreateRequest(BaseModel):
    environment_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    api_server_url: str = Field(default="", max_length=512)
    credential_name: str = Field(min_length=1, max_length=255)
    credential_content: str = Field(min_length=1, max_length=1_000_000)
    context_name: str = Field(default="", max_length=128)
    verify_ssl: bool = True


class MiddlewareInstanceCreateRequest(BaseModel):
    environment_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=2048)

    @field_validator("environment_name", "username", "password")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空")
        return stripped

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        stripped = value.strip()
        parts = urlsplit(stripped)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Nacos URL 必须是完整的 HTTP 或 HTTPS 地址")
        if parts.username or parts.password:
            raise ValueError("Nacos URL 不允许包含用户名或密码")
        if parts.query or parts.fragment:
            raise ValueError("Nacos URL 不允许包含查询参数或锚点")
        try:
            parts.port
        except ValueError as exc:
            raise ValueError("Nacos URL 端口无效") from exc
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc, parts.path.rstrip("/"), "", "")
        )
