import secrets
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

from .config import settings
from .db import execute_query, get_connection
from .node_exporter import scrape_node_exporter
from .schemas import HostCreateRequest, LoginRequest, LoginResponse, SessionRequest
from .session_store import delete_session, load_session, save_session

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="AI InfraOps RBAC API",
    version="0.1.0",
    description="登录、用户、角色、权限、菜单、机器资源信息 API。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rbac-api"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    users = execute_query(
        """
        SELECT id, username, display_name, email, password_hash, is_active, is_superuser
        FROM rbac_users
        WHERE username = %s
        LIMIT 1
        """,
        (payload.username,),
    )
    if not users:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user = users[0]
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="用户已被禁用")

    if not password_context.verify(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    roles = execute_query(
        """
        SELECT r.code
        FROM rbac_roles r
        JOIN rbac_user_roles ur ON ur.role_id = r.id
        WHERE ur.user_id = %s AND r.is_active = 1
        ORDER BY r.code
        """,
        (user["id"],),
    )
    permissions = execute_query(
        """
        SELECT DISTINCT p.code
        FROM rbac_permissions p
        JOIN rbac_role_permissions rp ON rp.permission_id = p.id
        JOIN rbac_user_roles ur ON ur.role_id = rp.role_id
        WHERE ur.user_id = %s AND p.is_active = 1
        ORDER BY p.code
        """,
        (user["id"],),
    )
    menus = execute_query(
        """
        SELECT DISTINCT m.id, m.title, m.code, m.path, m.icon, m.parent_id, m.sort_order
        FROM rbac_menus m
        LEFT JOIN rbac_menu_permissions mp ON mp.menu_id = m.id
        LEFT JOIN rbac_role_permissions rp ON rp.permission_id = mp.permission_id
        LEFT JOIN rbac_user_roles ur ON ur.role_id = rp.role_id
        WHERE m.is_active = 1
          AND m.is_visible = 1
          AND (m.permission_id IS NULL OR ur.user_id = %s OR %s = 1)
        ORDER BY m.sort_order, m.id
        """,
        (user["id"], user["is_superuser"]),
    )

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE rbac_users SET last_login_at = %s WHERE id = %s",
                (datetime.now(timezone.utc).replace(tzinfo=None), user["id"]),
            )
        connection.commit()
    finally:
        connection.close()

    access_token = secrets.token_urlsafe(32)
    response = LoginResponse(
        access_token=access_token,
        client_type=payload.client_type,
        expires_in=settings.session_ttl_seconds,
        user={
            "id": user["id"],
            "username": user["username"],
            "displayName": user["display_name"],
            "email": user["email"],
            "isSuperuser": bool(user["is_superuser"]),
        },
        roles=[item["code"] for item in roles],
        permissions=[item["code"] for item in permissions],
        menus=menus,
    )
    save_session(payload.client_type, access_token, response.model_dump())
    return response


@app.post("/api/auth/session", response_model=LoginResponse)
def get_session(payload: SessionRequest) -> LoginResponse:
    session = load_session(payload.client_type, payload.access_token)
    if not session:
        raise HTTPException(status_code=401, detail="会话已失效，请重新登录")
    return LoginResponse(**session)


@app.post("/api/auth/logout")
def logout(payload: SessionRequest) -> dict:
    delete_session(payload.client_type, payload.access_token)
    return {"logged_out": True}


@app.get("/api/rbac/users")
def list_users() -> list[dict]:
    return execute_query(
        """
        SELECT id, username, display_name, email, is_active, is_superuser, last_login_at
        FROM rbac_users
        ORDER BY id
        """
    )


@app.get("/api/rbac/roles")
def list_roles() -> list[dict]:
    return execute_query(
        "SELECT id, code, name, description, is_active FROM rbac_roles ORDER BY code"
    )


@app.get("/api/rbac/permissions")
def list_permissions() -> list[dict]:
    return execute_query(
        """
        SELECT id, code, name, permission_type, description, is_active
        FROM rbac_permissions
        ORDER BY code
        """
    )


@app.get("/api/rbac/menus")
def list_menus() -> list[dict]:
    return execute_query(
        """
        SELECT id, title, code, path, icon, parent_id, sort_order, is_visible, is_active
        FROM rbac_menus
        ORDER BY sort_order, id
        """
    )


@app.get("/api/hosts")
def list_hosts() -> list[dict]:
    hosts = execute_query(
        """
        SELECT id, hostname, public_ip, private_ip, node_exporter_url, status,
               last_error, last_seen_at, created_at, updated_at
        FROM machine_hosts
        ORDER BY id DESC
        """
    )
    for host in hosts:
        refresh_host_status(host)
    return execute_query(
        """
        SELECT id, hostname, public_ip, private_ip, node_exporter_url, status,
               last_error, last_seen_at, created_at, updated_at
        FROM machine_hosts
        ORDER BY id DESC
        """
    )


@app.post("/api/hosts")
def create_host(payload: HostCreateRequest) -> dict:
    scrape = scrape_node_exporter(payload.node_exporter_url)
    hostname = payload.hostname.strip() or scrape.hostname or scrape.public_ip
    public_ip = payload.public_ip.strip() or scrape.public_ip
    private_ip = payload.private_ip.strip()

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO machine_hosts (
                    hostname, public_ip, private_ip, node_exporter_url, status,
                    last_error, last_seen_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, IF(%s = 'active', NOW(), NULL))
                ON DUPLICATE KEY UPDATE
                    hostname = VALUES(hostname),
                    public_ip = VALUES(public_ip),
                    private_ip = VALUES(private_ip),
                    status = VALUES(status),
                    last_error = VALUES(last_error),
                    last_seen_at = VALUES(last_seen_at)
                """,
                (
                    hostname,
                    public_ip,
                    private_ip,
                    scrape.normalized_url,
                    scrape.status,
                    scrape.error,
                    scrape.status,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    return get_host_by_url(scrape.normalized_url)


@app.delete("/api/hosts/{host_id}")
def delete_host(host_id: int) -> dict:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM machine_hosts WHERE id = %s", (host_id,))
            affected = cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="主机不存在")
    return {"deleted": True, "id": host_id}


@app.get("/api/hosts/{host_id}/metrics")
def get_host_metrics(host_id: int) -> dict:
    host = get_host_by_id(host_id)
    scrape = scrape_node_exporter(host["node_exporter_url"], include_cpu_usage=True)
    update_host_scrape(host_id, scrape)

    if scrape.status != "active" or scrape.metrics is None:
        raise HTTPException(status_code=503, detail=scrape.error or "node-exporter 无法连接")

    if scrape.hostname and scrape.hostname != host["hostname"]:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE machine_hosts SET hostname = %s WHERE id = %s",
                    (scrape.hostname, host_id),
                )
            connection.commit()
        finally:
            connection.close()

    return {
        "host": get_host_by_id(host_id),
        "metrics": scrape.metrics,
    }


def get_host_by_id(host_id: int) -> dict:
    rows = execute_query(
        """
        SELECT id, hostname, public_ip, private_ip, node_exporter_url, status,
               last_error, last_seen_at, created_at, updated_at
        FROM machine_hosts
        WHERE id = %s
        LIMIT 1
        """,
        (host_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="主机不存在")
    return rows[0]


def get_host_by_url(node_exporter_url: str) -> dict:
    rows = execute_query(
        """
        SELECT id, hostname, public_ip, private_ip, node_exporter_url, status,
               last_error, last_seen_at, created_at, updated_at
        FROM machine_hosts
        WHERE node_exporter_url = %s
        LIMIT 1
        """,
        (node_exporter_url,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="主机不存在")
    return rows[0]


def refresh_host_status(host: dict) -> None:
    scrape = scrape_node_exporter(host["node_exporter_url"])
    update_host_scrape(host["id"], scrape)


def update_host_scrape(host_id: int, scrape) -> None:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE machine_hosts
                SET status = %s,
                    last_error = %s,
                    last_seen_at = IF(%s = 'active', NOW(), last_seen_at),
                    public_ip = IF(public_ip = '', %s, public_ip),
                    hostname = IF(
                        %s <> '' AND (hostname = '' OR hostname = public_ip),
                        %s,
                        hostname
                    )
                WHERE id = %s
                """,
                (
                    scrape.status,
                    scrape.error,
                    scrape.status,
                    scrape.public_ip,
                    scrape.hostname,
                    scrape.hostname,
                    host_id,
                ),
            )
        connection.commit()
    finally:
        connection.close()
