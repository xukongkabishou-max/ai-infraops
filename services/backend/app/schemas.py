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
    hostname: str = Field(default="", max_length=128)
    public_ip: str = Field(default="", max_length=64)
    private_ip: str = Field(default="", max_length=64)
