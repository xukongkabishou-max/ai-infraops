from pydantic import BaseModel, Field


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


class K8sClusterCreateRequest(BaseModel):
    environment_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    api_server_url: str = Field(default="", max_length=512)
    credential_name: str = Field(min_length=1, max_length=255)
    credential_content: str = Field(min_length=1, max_length=1_000_000)
    context_name: str = Field(default="", max_length=128)
    verify_ssl: bool = True
