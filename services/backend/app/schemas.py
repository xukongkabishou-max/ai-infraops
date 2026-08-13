import re
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    client_type: Literal["user_web", "backend_admin_web"] = "user_web"


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
    client_type: Literal["user_web", "backend_admin_web"]


class HostCreateRequest(BaseModel):
    node_exporter_url: str = Field(min_length=1, max_length=512)
    linux_agent_url: str = Field(default="", max_length=512)
    hostname: str = Field(min_length=1, max_length=128)
    public_ip: str = Field(default="", max_length=64)
    private_ip: str = Field(default="", max_length=64)
    environment_code: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    environment_name: str = Field(min_length=1, max_length=128)
    k8s_credential_name: str = Field(default="", max_length=255)
    k8s_credential_content: str = Field(default="", max_length=1_000_000)
    namespace_keys: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("linux_agent_url")
    @classmethod
    def normalize_linux_agent_url(cls, value: str) -> str:
        return _normalize_linux_agent_url(value)

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


class MiddlewareInstanceBaseRequest(BaseModel):
    middleware_type: Literal["nacos", "doris", "mysql"] = "nacos"
    environment_name: str = Field(min_length=1, max_length=128)
    instance_name: str = Field(default="", max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    dashboard_url: str = Field(default="", max_length=2048)
    username: str = Field(min_length=1, max_length=255)

    @field_validator(
        "environment_name", "instance_name", "dashboard_url", "username"
    )
    @classmethod
    def strip_text(cls, value: str, info) -> str:
        stripped = value.strip()
        if info.field_name not in {"instance_name", "dashboard_url"} and not stripped:
            raise ValueError("字段不能为空")
        return stripped

    @model_validator(mode="after")
    def normalize_connection_address(self):
        if self.middleware_type == "nacos":
            self.base_url = _normalize_nacos_url(self.base_url)
            self.dashboard_url = ""
        elif self.middleware_type == "doris":
            self.base_url = _normalize_doris_address(self.base_url)
            self.dashboard_url = ""
        else:
            self.base_url = _normalize_mysql_address(self.base_url)
            if not self.dashboard_url:
                raise ValueError("MySQL 实例必须填写 Grafana 仪表盘地址")
            self.dashboard_url = _normalize_dashboard_url(self.dashboard_url)
        return self


class MiddlewareInstanceCreateRequest(MiddlewareInstanceBaseRequest):
    password: str = Field(min_length=1, max_length=2048)

    @field_validator("password")
    @classmethod
    def strip_password(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空")
        return stripped


class MiddlewareInstanceUpdateRequest(MiddlewareInstanceBaseRequest):
    password: str = Field(default="", max_length=2048)

    @field_validator("password")
    @classmethod
    def strip_optional_password(cls, value: str) -> str:
        return value.strip()


class NacosConfigStructureRequest(BaseModel):
    namespace_id: str = Field(default="public", max_length=255)
    group: str = Field(min_length=1, max_length=255)
    data_id: str = Field(min_length=1, max_length=255)
    config_type: Literal["yaml", "yml", "json"]

    @field_validator("namespace_id", "group", "data_id", "config_type")
    @classmethod
    def strip_config_identifier(cls, value: str, info) -> str:
        stripped = value.strip()
        if info.field_name == "namespace_id":
            return stripped or "public"
        if not stripped:
            raise ValueError("字段不能为空")
        return stripped


class DorisPasswordVerifyRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)


class DorisPasswordResetRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)


class DorisManagedPasswordRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=512)
    purpose: Literal["view", "copy"]


class DorisManagedPasswordSaveRequest(BaseModel):
    user_identity: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=2048)


def _normalize_nacos_url(value: str) -> str:
    parts = urlsplit(value.strip())
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


def _normalize_doris_address(value: str) -> str:
    raw_value = value.strip()
    parts = urlsplit(raw_value if "://" in raw_value else f"mysql://{raw_value}")
    if parts.scheme != "mysql" or not parts.hostname:
        raise ValueError("Doris FE 地址必须使用 host:port 格式")
    if parts.username or parts.password:
        raise ValueError("Doris FE 地址不允许包含用户名或密码")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("Doris FE 地址不允许包含路径、查询参数或锚点")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Doris FE 查询端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Doris FE 地址必须包含有效查询端口")
    host = parts.hostname
    normalized_host = f"[{host}]" if ":" in host else host
    return f"mysql://{normalized_host}:{port}"


def _normalize_mysql_address(value: str) -> str:
    raw_value = value.strip()
    parts = urlsplit(raw_value if "://" in raw_value else f"mysql://{raw_value}")
    if parts.scheme != "mysql" or not parts.hostname:
        raise ValueError("MySQL 地址必须使用 host:port 格式")
    if parts.username or parts.password:
        raise ValueError("MySQL 地址不允许包含用户名或密码")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("MySQL 地址不允许包含路径、查询参数或锚点")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("MySQL 连接端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("MySQL 地址必须包含有效连接端口")
    host = parts.hostname
    normalized_host = f"[{host}]" if ":" in host else host
    return f"mysql://{normalized_host}:{port}"


def _normalize_dashboard_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Grafana 仪表盘地址必须是完整的 HTTP 或 HTTPS 地址")
    if parts.username or parts.password:
        raise ValueError("Grafana 仪表盘地址不允许包含用户名或密码")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("Grafana 仪表盘地址端口无效") from exc
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc, parts.path, parts.query, parts.fragment)
    )


def _normalize_linux_agent_url(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        return ""
    parts = urlsplit(raw_value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("主机用户管理地址必须是完整的 HTTP 或 HTTPS 地址")
    if parts.username or parts.password:
        raise ValueError("主机用户管理地址不允许包含用户名或密码")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("主机用户管理地址只允许填写服务根地址")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("主机用户管理地址端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("主机用户管理地址必须包含有效端口")
    return urlunsplit((parts.scheme.lower(), parts.netloc, "", "", ""))
