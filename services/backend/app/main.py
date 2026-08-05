import logging
import hashlib
import json
import secrets
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pymysql.err import IntegrityError

from .config import settings
from .credential_crypto import encrypt_credential, validate_kubeconfig
from .db import execute_query, get_connection
from .k8s_client import (
    K8sIntegrationError,
    get_workload_environment_keys,
    list_env_workloads,
    list_namespaces,
    list_nodeport_services,
    list_running_controller_images,
)
from .logging_config import RequestLoggingMiddleware, configure_logging
from .middleware_crypto import decrypt_middleware_password, encrypt_middleware_password
from .nacos_client import NacosIntegrationError, fetch_nacos_catalog
from .node_exporter import scrape_node_exporter
from .schemas import (
    HostCreateRequest,
    K8sClusterCreateRequest,
    LoginRequest,
    LoginResponse,
    MiddlewareInstanceCreateRequest,
    SessionRequest,
)
from .session_store import delete_session, load_session, save_session

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
log_file = configure_logging()
logger = logging.getLogger("infraops.api")

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
app.add_middleware(RequestLoggingMiddleware)
logger.info("后端日志系统已初始化：%s", log_file, extra={"event": "logging_initialized"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rbac-api"}


def require_backend_admin_session(
    authorization: str | None = Header(default=None),
) -> dict:
    scheme, _, access_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=401, detail="缺少后台管理会话")
    session = load_session("backend_admin_web", access_token)
    if not session:
        raise HTTPException(status_code=401, detail="后台管理会话已失效")
    return session


def require_user_web_session(
    authorization: str | None = Header(default=None),
) -> dict:
    scheme, _, access_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=401, detail="缺少用户端会话")
    session = load_session("user_web", access_token)
    if not session:
        raise HTTPException(status_code=401, detail="用户端会话已失效")
    return session


def require_permission(session: dict, permission: str) -> None:
    user = session.get("user", {})
    if user.get("isSuperuser") or permission in session.get("permissions", []):
        return
    raise HTTPException(status_code=403, detail="当前账号没有此操作权限")


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


@app.get("/api/environments")
def list_environments() -> list[dict]:
    return execute_query(
        """
        SELECT e.id, e.code, e.name, e.description, e.is_active,
               COUNT(DISTINCT h.id) AS host_count,
               COUNT(DISTINCT c.id) AS cluster_count
        FROM infra_environments e
        LEFT JOIN machine_hosts h ON h.environment_id = e.id
        LEFT JOIN k8s_clusters c ON c.environment_id = e.id AND c.status <> 'disabled'
        WHERE e.is_active = 1
        GROUP BY e.id, e.code, e.name, e.description, e.is_active
        ORDER BY e.name, e.id
        """
    )


@app.get("/api/middleware/instances")
def list_middleware_instances(
    middleware_type: str | None = None,
    admin_session: dict = Depends(require_backend_admin_session),
) -> list[dict]:
    require_permission(admin_session, "middleware:list")
    where_clause = "WHERE m.middleware_type = %s" if middleware_type else ""
    params = (middleware_type,) if middleware_type else None
    return execute_query(
        f"""
        SELECT m.id, m.environment_id, e.code AS environment_code,
               e.name AS environment_name, m.middleware_type, m.instance_name,
               m.base_url, m.username, m.status, m.last_error, m.last_seen_at,
               m.created_at, m.updated_at,
               (m.password_ciphertext IS NOT NULL AND m.password_nonce IS NOT NULL)
                 AS credential_configured
        FROM middleware_instances m
        JOIN infra_environments e ON e.id = m.environment_id
        {where_clause}
        ORDER BY e.name, m.middleware_type, m.instance_name, m.id
        """,
        params,
    )


@app.post("/api/middleware/instances")
def create_middleware_instance(
    payload: MiddlewareInstanceCreateRequest,
    admin_session: dict = Depends(require_backend_admin_session),
) -> dict:
    require_permission(admin_session, "middleware:create")
    try:
        password_ciphertext, password_nonce = encrypt_middleware_password(
            payload.password
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    environment_code = (
        f"env-{hashlib.sha256(payload.environment_name.encode('utf-8')).hexdigest()[:16]}"
    )
    instance_name = f"{payload.environment_name} Nacos"
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, code, is_active
                FROM infra_environments
                WHERE name = %s
                LIMIT 1
                """,
                (payload.environment_name,),
            )
            environment = cursor.fetchone()
            if environment:
                environment_id = environment["id"]
                environment_code = environment["code"]
                if not environment["is_active"]:
                    cursor.execute(
                        "UPDATE infra_environments SET is_active = 1 WHERE id = %s",
                        (environment_id,),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO infra_environments (code, name, is_active)
                    VALUES (%s, %s, 1)
                    """,
                    (environment_code, payload.environment_name),
                )
                environment_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO middleware_instances (
                    environment_id, middleware_type, instance_name, base_url,
                    username, password_ciphertext, password_nonce, status,
                    last_error
                )
                VALUES (%s, 'nacos', %s, %s, %s, %s, %s, 'configured', NULL)
                """,
                (
                    environment_id,
                    instance_name,
                    payload.base_url,
                    payload.username,
                    password_ciphertext,
                    password_nonce,
                ),
            )
            instance_id = cursor.lastrowid
        connection.commit()
    except IntegrityError as exc:
        connection.rollback()
        raise HTTPException(status_code=409, detail="该 Nacos 地址已登记") from exc
    finally:
        connection.close()

    logger.info(
        "Nacos 实例已登记",
        extra={
            "event": "middleware_instance_created",
            "middleware_instance_id": instance_id,
            "middleware_type": "nacos",
        },
    )
    return {
        "id": instance_id,
        "environment_id": environment_id,
        "environment_code": environment_code,
        "environment_name": payload.environment_name,
        "middleware_type": "nacos",
        "instance_name": instance_name,
        "base_url": payload.base_url,
        "username": payload.username,
        "status": "configured",
        "last_error": None,
        "last_seen_at": None,
        "created_at": created_at,
        "updated_at": created_at,
        "credential_configured": True,
    }


@app.delete("/api/middleware/instances/{instance_id}")
def delete_middleware_instance(
    instance_id: int,
    admin_session: dict = Depends(require_backend_admin_session),
) -> dict:
    require_permission(admin_session, "middleware:delete")
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM middleware_instances WHERE id = %s", (instance_id,)
            )
            affected = cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="中间件实例不存在")
    logger.info(
        "中间件实例已删除",
        extra={
            "event": "middleware_instance_deleted",
            "middleware_instance_id": instance_id,
        },
    )
    return {"deleted": True, "id": instance_id}


@app.get("/api/nacos/instances")
def list_user_nacos_instances(
    user_session: dict = Depends(require_user_web_session),
) -> list[dict]:
    require_permission(user_session, "nacos:catalog:list")
    return execute_query(
        """
        SELECT m.id, m.environment_id, e.name AS environment_name,
               m.instance_name, m.status, m.last_seen_at
        FROM middleware_instances m
        JOIN infra_environments e ON e.id = m.environment_id
        WHERE m.middleware_type = 'nacos'
          AND m.status <> 'disabled'
          AND e.is_active = 1
        ORDER BY e.name, m.instance_name, m.id
        """
    )


@app.get("/api/nacos/instances/{instance_id}/catalog")
def get_nacos_catalog(
    instance_id: int,
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "nacos:catalog:list")
    instances = execute_query(
        """
        SELECT m.id, m.environment_id, e.name AS environment_name,
               m.instance_name, m.base_url, m.username,
               m.password_ciphertext, m.password_nonce
        FROM middleware_instances m
        JOIN infra_environments e ON e.id = m.environment_id
        WHERE m.id = %s AND m.middleware_type = 'nacos'
          AND m.status <> 'disabled' AND e.is_active = 1
        LIMIT 1
        """,
        (instance_id,),
    )
    if not instances:
        raise HTTPException(status_code=404, detail="Nacos 实例不存在")

    instance = instances[0]
    try:
        password = decrypt_middleware_password(
            instance["password_ciphertext"], instance["password_nonce"]
        )
        namespaces = fetch_nacos_catalog(
            instance["base_url"], instance["username"], password
        )
    except (ValueError, RuntimeError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, NacosIntegrationError)
            else "Nacos 凭证无法解密"
        )
        _update_middleware_connection_status(instance_id, "unreachable", detail)
        logger.warning(
            "Nacos 配置目录查询失败：%s",
            detail,
            extra={
                "event": "nacos_catalog_failed",
                "middleware_instance_id": instance_id,
            },
        )
        raise HTTPException(status_code=502, detail=detail) from exc

    _update_middleware_connection_status(instance_id, "active", None)
    config_count = sum(item["config_count"] for item in namespaces)
    logger.info(
        "Nacos 配置目录查询成功",
        extra={
            "event": "nacos_catalog_loaded",
            "middleware_instance_id": instance_id,
            "namespace_count": len(namespaces),
            "config_count": config_count,
        },
    )
    return {
        "instance": {
            "id": instance["id"],
            "environment_id": instance["environment_id"],
            "environment_name": instance["environment_name"],
            "instance_name": instance["instance_name"],
            "status": "active",
        },
        "namespace_count": len(namespaces),
        "config_count": config_count,
        "namespaces": namespaces,
    }


def _update_middleware_connection_status(
    instance_id: int, status: str, last_error: str | None
) -> None:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE middleware_instances
                SET status = %s, last_error = %s,
                    last_seen_at = CASE WHEN %s = 'active' THEN %s ELSE last_seen_at END
                WHERE id = %s
                """,
                (
                    status,
                    last_error,
                    status,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    instance_id,
                ),
            )
        connection.commit()
    finally:
        connection.close()


@app.get("/api/k8s/clusters")
def list_k8s_clusters(environment_id: int | None = None) -> list[dict]:
    where_clause = "WHERE c.environment_id = %s" if environment_id else ""
    params = (environment_id,) if environment_id else None
    return execute_query(
        f"""
        SELECT c.id, c.environment_id, e.code AS environment_code,
               e.name AS environment_name, c.name, c.api_server_url,
               c.context_name, c.verify_ssl, c.status, c.last_error,
               c.last_seen_at, c.created_at, c.updated_at
        FROM k8s_clusters c
        JOIN infra_environments e ON e.id = c.environment_id
        {where_clause}
        ORDER BY e.name, c.name
        """,
        params,
    )


@app.post("/api/k8s/clusters")
def create_k8s_cluster(payload: K8sClusterCreateRequest) -> dict:
    try:
        validate_kubeconfig(payload.credential_content)
        ciphertext, nonce, fingerprint = encrypt_credential(payload.credential_content)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not execute_query(
        "SELECT id FROM infra_environments WHERE id = %s AND is_active = 1",
        (payload.environment_id,),
    ):
        raise HTTPException(status_code=404, detail="环境不存在")

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO k8s_clusters (
                    environment_id, name, api_server_url, credential_ref,
                    credential_name, credential_ciphertext, credential_nonce,
                    credential_fingerprint, context_name, verify_ssl, status, last_error
                )
                VALUES (%s, %s, %s, '', %s, %s, %s, %s, %s, %s, 'configured', NULL)
                ON DUPLICATE KEY UPDATE
                    api_server_url = VALUES(api_server_url),
                    credential_ref = '',
                    credential_name = VALUES(credential_name),
                    credential_ciphertext = VALUES(credential_ciphertext),
                    credential_nonce = VALUES(credential_nonce),
                    credential_fingerprint = VALUES(credential_fingerprint),
                    context_name = VALUES(context_name),
                    verify_ssl = VALUES(verify_ssl),
                    status = 'configured',
                    last_error = NULL
                """,
                (
                    payload.environment_id,
                    payload.name.strip(),
                    payload.api_server_url.strip(),
                    payload.credential_name.strip(),
                    ciphertext,
                    nonce,
                    fingerprint,
                    payload.context_name.strip(),
                    payload.verify_ssl,
                ),
            )
            cursor.execute(
                """
                SELECT id FROM k8s_clusters
                WHERE environment_id = %s AND name = %s
                LIMIT 1
                """,
                (payload.environment_id, payload.name.strip()),
            )
            cluster_id = cursor.fetchone()["id"]
        connection.commit()
    finally:
        connection.close()
    return get_k8s_cluster(cluster_id, include_credentials=False)


@app.delete("/api/k8s/clusters/{cluster_id}")
def delete_k8s_cluster(cluster_id: int) -> dict:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM k8s_clusters WHERE id = %s", (cluster_id,))
            affected = cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    if affected == 0:
        raise HTTPException(status_code=404, detail="K8S 集群不存在")
    return {"deleted": True, "id": cluster_id}


@app.get("/api/k8s/hosts")
def list_k8s_hosts() -> list[dict]:
    return execute_query(
        """
        SELECT h.id AS host_id, h.hostname, h.environment_id,
               e.name AS environment_name, c.id AS cluster_id,
               c.status, c.last_error, c.last_seen_at
        FROM machine_hosts h
        JOIN infra_environments e ON e.id = h.environment_id
        JOIN k8s_clusters c ON c.host_id = h.id
        WHERE c.credential_ciphertext IS NOT NULL
          AND c.credential_nonce IS NOT NULL
          AND c.status <> 'disabled'
        ORDER BY e.name, h.hostname, h.id
        """
    )


@app.get("/api/k8s/namespaces")
def get_k8s_namespaces(host_id: int) -> dict:
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    cluster_id = cluster["id"]
    try:
        namespaces = list_namespaces(cluster)
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster_id, "unreachable", str(exc))
        logger.warning(
            "K8S namespace 查询失败",
            extra={"event": "k8s_namespace_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster_id, "active", None)
    return {"cluster": _public_cluster(cluster), "namespaces": namespaces}


@app.get("/api/k8s/images")
def get_k8s_images(
    host_id: int,
    namespace: str = Query(min_length=1, max_length=253),
) -> dict:
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    cluster_id = cluster["id"]
    try:
        images = list_running_controller_images(cluster, namespace)
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster_id, "unreachable", str(exc))
        logger.warning(
            "K8S 镜像查询失败",
            extra={"event": "k8s_image_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster_id, "active", None)
    return {
        "cluster": _public_cluster(cluster),
        "namespace": namespace,
        "images": images,
    }


@app.get("/api/k8s/nodeports/hosts")
def list_k8s_nodeport_hosts(
    user_session: dict = Depends(require_user_web_session),
) -> list[dict]:
    require_permission(user_session, "k8s:nodeport:list")
    return execute_query(
        """
        SELECT h.id AS host_id, h.hostname, h.environment_id,
               e.name AS environment_name, h.public_ip,
               c.id AS cluster_id, c.status, c.last_error, c.last_seen_at
        FROM machine_hosts h
        JOIN infra_environments e ON e.id = h.environment_id
        JOIN k8s_clusters c ON c.host_id = h.id
        WHERE c.credential_ciphertext IS NOT NULL
          AND c.credential_nonce IS NOT NULL
          AND c.status <> 'disabled'
        ORDER BY e.name, h.hostname, h.id
        """
    )


@app.get("/api/k8s/nodeports/namespaces")
def get_k8s_nodeport_namespaces(
    host_id: int = Query(gt=0),
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "k8s:nodeport:list")
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    try:
        namespaces = list_namespaces(cluster)
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster["id"], "unreachable", str(exc))
        logger.warning(
            "K8S NodePort Namespace 查询失败",
            extra={"event": "k8s_nodeport_namespace_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster["id"], "active", None)
    return {
        "host_id": host_id,
        "namespaces": namespaces,
        "policy": {"mode": "allow_all", "managed": False},
    }


@app.get("/api/k8s/nodeports")
def get_k8s_nodeports(
    host_id: int = Query(gt=0),
    namespace: str = Query(min_length=1, max_length=63),
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "k8s:nodeport:list")
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    host_rows = execute_query(
        """
        SELECT h.public_ip
        FROM machine_hosts h
        WHERE h.id = %s
        LIMIT 1
        """,
        (host_id,),
    )
    if not host_rows:
        raise HTTPException(status_code=404, detail="主机不存在")

    try:
        services = list_nodeport_services(cluster, namespace)
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster["id"], "unreachable", str(exc))
        logger.warning(
            "K8S NodePort 查询失败",
            extra={"event": "k8s_nodeport_query_failed", "host_id": host_id, "namespace": namespace, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc

    public_ip = (host_rows[0].get("public_ip") or "").strip()
    visible_services = [
        {
            **service,
            "public_address": _format_host_port(public_ip, service["node_port"]) if public_ip else None,
            "visible": True,
            "note": None,
        }
        for service in services
    ]
    update_k8s_cluster_status(cluster["id"], "active", None)
    logger.info(
        "用户查询 K8S NodePort",
        extra={
            "event": "k8s_nodeport_query_succeeded",
            "host_id": host_id,
            "namespace": namespace,
            "result_count": len(visible_services),
            "user_id": user_session.get("user", {}).get("id"),
        },
    )
    return {
        "cluster": _public_cluster(cluster),
        "namespace": namespace,
        "public_ip": public_ip or None,
        "policy": {"mode": "allow_all", "managed": False},
        "services": visible_services,
    }


@app.get("/api/k8s/env/hosts")
def list_k8s_env_hosts(
    user_session: dict = Depends(require_user_web_session),
) -> list[dict]:
    require_permission(user_session, "k8s:env:list")
    rows = execute_query(
        """
        SELECT h.id AS host_id, h.hostname, h.environment_id,
               e.name AS environment_name, h.namespace_keys,
               c.id AS cluster_id, c.status, c.last_seen_at
        FROM machine_hosts h
        JOIN infra_environments e ON e.id = h.environment_id
        JOIN k8s_clusters c ON c.host_id = h.id
        WHERE c.credential_ciphertext IS NOT NULL
          AND c.credential_nonce IS NOT NULL
          AND c.status <> 'disabled'
          AND h.namespace_keys IS NOT NULL
        ORDER BY e.name, h.hostname, h.id
        """
    )
    return [
        {**row, "namespace_keys": _decode_namespace_keys(row.get("namespace_keys"))}
        for row in rows
        if _decode_namespace_keys(row.get("namespace_keys"))
    ]


@app.get("/api/k8s/env/namespaces")
def get_k8s_env_namespaces(
    host_id: int = Query(gt=0),
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "k8s:env:list")
    allowed_namespaces = _require_allowed_namespaces(host_id)
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    try:
        available_namespaces = set(list_namespaces(cluster))
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster["id"], "unreachable", str(exc))
        logger.warning(
            "K8S 环境变量 Namespace 查询失败",
            extra={"event": "k8s_env_namespace_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster["id"], "active", None)
    return {
        "host_id": host_id,
        "status": "active",
        "namespaces": [item for item in allowed_namespaces if item in available_namespaces],
    }


@app.get("/api/k8s/env/workloads")
def get_k8s_env_workloads(
    host_id: int = Query(gt=0),
    namespace: str = Query(min_length=1, max_length=63),
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "k8s:env:list")
    _require_allowed_namespace(host_id, namespace)
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    try:
        workloads = list_env_workloads(cluster, namespace)
    except K8sIntegrationError as exc:
        update_k8s_cluster_status(cluster["id"], "unreachable", str(exc))
        logger.warning(
            "K8S 环境变量工作负载查询失败",
            extra={"event": "k8s_env_workload_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster["id"], "active", None)
    return {"namespace": namespace, "workloads": workloads}


@app.get("/api/k8s/env/keys")
def get_k8s_env_keys(
    host_id: int = Query(gt=0),
    namespace: str = Query(min_length=1, max_length=63),
    kind: str = Query(pattern=r"^(?i:deployment|statefulset)$"),
    workload: str = Query(min_length=1, max_length=253),
    user_session: dict = Depends(require_user_web_session),
) -> dict:
    require_permission(user_session, "k8s:env:list")
    _require_allowed_namespace(host_id, namespace)
    cluster = get_k8s_cluster_by_host(host_id, include_credentials=True)
    try:
        result = get_workload_environment_keys(cluster, namespace, kind, workload)
    except K8sIntegrationError as exc:
        logger.warning(
            "K8S 环境变量 Key 查询失败",
            extra={"event": "k8s_env_key_query_failed", "host_id": host_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=f"K8S API 查询失败：{exc}") from exc
    update_k8s_cluster_status(cluster["id"], "active", None)
    return result


@app.get("/api/hosts")
def list_hosts() -> list[dict]:
    rows = execute_query(
        """
        SELECT h.id, h.environment_id, e.code AS environment_code,
               e.name AS environment_name, h.hostname, h.public_ip,
               h.private_ip, h.node_exporter_url, h.namespace_keys,
               h.status, h.last_error,
               h.last_seen_at, h.created_at, h.updated_at,
               EXISTS(
                   SELECT 1 FROM k8s_clusters c
                   WHERE c.host_id = h.id
                     AND c.credential_ciphertext IS NOT NULL
                     AND c.credential_nonce IS NOT NULL
               ) AS has_k8s_credential
        FROM machine_hosts h
        LEFT JOIN infra_environments e ON e.id = h.environment_id
        ORDER BY h.id DESC
        """
    )
    return [_serialize_host(row) for row in rows]


@app.post("/api/hosts")
def create_host(payload: HostCreateRequest) -> dict:
    return save_host(payload)


@app.put("/api/hosts/{host_id}")
def update_host(host_id: int, payload: HostCreateRequest) -> dict:
    get_host_by_id(host_id)
    return save_host(payload, host_id=host_id)


@app.post("/api/hosts/{host_id}/probe")
def probe_host(host_id: int) -> dict:
    host = get_host_by_id(host_id)
    scrape = scrape_node_exporter(host["node_exporter_url"])
    update_host_scrape(host_id, scrape)
    logger.info(
        "主机连接检测完成",
        extra={
            "event": "host_probe_completed",
            "host_id": host_id,
            "target_url": scrape.normalized_url,
        },
    )
    return get_host_by_id(host_id)


def save_host(payload: HostCreateRequest, host_id: int | None = None) -> dict:
    credential_name = payload.k8s_credential_name.strip()
    credential_content = payload.k8s_credential_content.strip()
    encrypted_credential: tuple[bytes, bytes, str] | None = None
    if credential_content:
        try:
            validate_kubeconfig(credential_content)
            encrypted_credential = encrypt_credential(credential_content)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    scrape = scrape_node_exporter(payload.node_exporter_url)
    hostname = payload.hostname.strip()
    public_ip = payload.public_ip.strip() or scrape.public_ip
    private_ip = payload.private_ip.strip()
    environment_id = upsert_environment(payload.environment_name)

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            values = (
                environment_id,
                hostname,
                public_ip,
                private_ip,
                scrape.normalized_url,
                json.dumps(payload.namespace_keys, ensure_ascii=True),
                scrape.status,
                scrape.error,
                scrape.status,
            )
            if host_id is None:
                cursor.execute(
                    """
                    INSERT INTO machine_hosts (
                        environment_id, hostname, public_ip, private_ip,
                        node_exporter_url, namespace_keys, status, last_error, last_seen_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, IF(%s = 'active', NOW(), NULL))
                    """,
                    values,
                )
                host_id = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    UPDATE machine_hosts
                    SET environment_id = %s,
                        hostname = %s,
                        public_ip = %s,
                        private_ip = %s,
                        node_exporter_url = %s,
                        namespace_keys = %s,
                        status = %s,
                        last_error = %s,
                        last_seen_at = IF(%s = 'active', NOW(), last_seen_at)
                    WHERE id = %s
                    """,
                    (*values, host_id),
                )
        connection.commit()
    except IntegrityError as exc:
        connection.rollback()
        logger.warning(
            "主机保存失败：node-exporter URL 重复",
            extra={"event": "host_save_conflict", "host_id": host_id},
        )
        raise HTTPException(status_code=409, detail="node-exporter URL 已被其他主机使用") from exc
    finally:
        connection.close()

    sync_host_k8s_cluster(
        host_id=host_id,
        environment_id=environment_id,
        credential_name=credential_name or f"{hostname}.yaml",
        encrypted_credential=encrypted_credential,
    )

    saved_host = get_host_by_id(host_id)
    logger.info(
        "主机信息已保存",
        extra={
            "event": "host_saved",
            "host_id": host_id,
            "target_url": scrape.normalized_url,
        },
    )
    return saved_host


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
    logger.info("主机已删除", extra={"event": "host_deleted", "host_id": host_id})
    return {"deleted": True, "id": host_id}


@app.get("/api/hosts/{host_id}/metrics")
def get_host_metrics(host_id: int) -> dict:
    host = get_host_by_id(host_id)
    scrape = scrape_node_exporter(host["node_exporter_url"], include_cpu_usage=True)
    update_host_scrape(host_id, scrape)

    if scrape.status != "active" or scrape.metrics is None:
        raise HTTPException(status_code=503, detail=scrape.error or "node-exporter 无法连接")

    return {
        "host": get_host_by_id(host_id),
        "metrics": scrape.metrics,
    }


def get_host_by_id(host_id: int) -> dict:
    rows = execute_query(
        """
        SELECT h.id, h.environment_id, e.code AS environment_code,
               e.name AS environment_name, h.hostname, h.public_ip,
               h.private_ip, h.node_exporter_url, h.namespace_keys,
               h.status, h.last_error,
               h.last_seen_at, h.created_at, h.updated_at,
               EXISTS(
                   SELECT 1 FROM k8s_clusters c
                   WHERE c.host_id = h.id
                     AND c.credential_ciphertext IS NOT NULL
                     AND c.credential_nonce IS NOT NULL
               ) AS has_k8s_credential
        FROM machine_hosts h
        LEFT JOIN infra_environments e ON e.id = h.environment_id
        WHERE h.id = %s
        LIMIT 1
        """,
        (host_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="主机不存在")
    return _serialize_host(rows[0])


def get_host_by_url(node_exporter_url: str) -> dict:
    rows = execute_query(
        """
        SELECT h.id, h.environment_id, e.code AS environment_code,
               e.name AS environment_name, h.hostname, h.public_ip,
               h.private_ip, h.node_exporter_url, h.namespace_keys,
               h.status, h.last_error,
               h.last_seen_at, h.created_at, h.updated_at,
               EXISTS(
                   SELECT 1 FROM k8s_clusters c
                   WHERE c.host_id = h.id
                     AND c.credential_ciphertext IS NOT NULL
                     AND c.credential_nonce IS NOT NULL
               ) AS has_k8s_credential
        FROM machine_hosts h
        LEFT JOIN infra_environments e ON e.id = h.environment_id
        WHERE h.node_exporter_url = %s
        LIMIT 1
        """,
        (node_exporter_url,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="主机不存在")
    return _serialize_host(rows[0])


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


def upsert_environment(name: str) -> int:
    environment_name = name.strip()
    environment_code = f"env-{hashlib.sha256(environment_name.encode('utf-8')).hexdigest()[:16]}"

    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM infra_environments WHERE name = %s LIMIT 1",
                (environment_name,),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE infra_environments SET is_active = 1 WHERE id = %s",
                    (existing["id"],),
                )
                connection.commit()
                return existing["id"]
            cursor.execute(
                """
                INSERT INTO infra_environments (code, name, is_active)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE name = VALUES(name), is_active = 1
                """,
                (environment_code, environment_name),
            )
            cursor.execute(
                "SELECT id FROM infra_environments WHERE code = %s LIMIT 1",
                (environment_code,),
            )
            environment_id = cursor.fetchone()["id"]
        connection.commit()
        return environment_id
    finally:
        connection.close()


def _decode_namespace_keys(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if str(item).strip()]


def _serialize_host(host: dict) -> dict:
    return {
        **host,
        "namespace_keys": _decode_namespace_keys(host.get("namespace_keys")),
    }


def _require_allowed_namespaces(host_id: int) -> list[str]:
    rows = execute_query(
        """
        SELECT h.namespace_keys
        FROM machine_hosts h
        JOIN k8s_clusters c ON c.host_id = h.id
        WHERE h.id = %s
          AND c.credential_ciphertext IS NOT NULL
          AND c.credential_nonce IS NOT NULL
          AND c.status <> 'disabled'
        LIMIT 1
        """,
        (host_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="该主机尚未配置可用的 K8S 凭证")
    namespaces = _decode_namespace_keys(rows[0].get("namespace_keys"))
    if not namespaces:
        raise HTTPException(status_code=409, detail="该主机尚未配置 Namespace Key 白名单")
    return namespaces


def _require_allowed_namespace(host_id: int, namespace: str) -> None:
    if namespace not in _require_allowed_namespaces(host_id):
        raise HTTPException(status_code=403, detail="该 Namespace 不在环境变量 Key 查询白名单中")


def sync_host_k8s_cluster(
    host_id: int,
    environment_id: int,
    credential_name: str,
    encrypted_credential: tuple[bytes, bytes, str] | None,
) -> None:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM k8s_clusters WHERE host_id = %s LIMIT 1",
                (host_id,),
            )
            existing = cursor.fetchone()
            if encrypted_credential is None:
                if existing:
                    cursor.execute(
                        """
                        UPDATE k8s_clusters
                        SET environment_id = %s, name = %s
                        WHERE host_id = %s
                        """,
                        (environment_id, f"host-{host_id}", host_id),
                    )
                connection.commit()
                return

            ciphertext, nonce, fingerprint = encrypted_credential
            cursor.execute(
                """
                INSERT INTO k8s_clusters (
                    host_id, environment_id, name, api_server_url, credential_ref,
                    credential_name, credential_ciphertext, credential_nonce,
                    credential_fingerprint, context_name, verify_ssl, status, last_error
                )
                VALUES (%s, %s, %s, '', '', %s, %s, %s, %s, '', 1, 'configured', NULL)
                ON DUPLICATE KEY UPDATE
                    environment_id = VALUES(environment_id),
                    name = VALUES(name),
                    credential_ref = '',
                    credential_name = VALUES(credential_name),
                    credential_ciphertext = VALUES(credential_ciphertext),
                    credential_nonce = VALUES(credential_nonce),
                    credential_fingerprint = VALUES(credential_fingerprint),
                    status = 'configured',
                    last_error = NULL
                """,
                (
                    host_id,
                    environment_id,
                    f"host-{host_id}",
                    credential_name,
                    ciphertext,
                    nonce,
                    fingerprint,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def get_k8s_cluster(cluster_id: int, include_credentials: bool) -> dict:
    credential_column = (
        ", c.credential_ciphertext, c.credential_nonce"
        if include_credentials
        else ""
    )
    rows = execute_query(
        f"""
        SELECT c.id, c.host_id, h.hostname, c.environment_id, e.code AS environment_code,
               e.name AS environment_name, c.name, c.api_server_url,
               c.context_name, c.verify_ssl, c.status, c.last_error,
               c.last_seen_at, c.created_at, c.updated_at
               {credential_column}
        FROM k8s_clusters c
        LEFT JOIN machine_hosts h ON h.id = c.host_id
        JOIN infra_environments e ON e.id = c.environment_id
        WHERE c.id = %s
        LIMIT 1
        """,
        (cluster_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="K8S 集群不存在")
    if rows[0]["status"] == "disabled":
        raise HTTPException(status_code=409, detail="K8S 集群已停用")
    return rows[0]


def get_k8s_cluster_by_host(host_id: int, include_credentials: bool) -> dict:
    credential_column = (
        ", c.credential_ciphertext, c.credential_nonce"
        if include_credentials
        else ""
    )
    rows = execute_query(
        f"""
        SELECT c.id, c.host_id, h.hostname, c.environment_id,
               e.code AS environment_code, e.name AS environment_name,
               c.name, c.api_server_url, c.context_name, c.verify_ssl,
               c.status, c.last_error, c.last_seen_at, c.created_at,
               c.updated_at {credential_column}
        FROM k8s_clusters c
        JOIN machine_hosts h ON h.id = c.host_id
        JOIN infra_environments e ON e.id = c.environment_id
        WHERE c.host_id = %s
        LIMIT 1
        """,
        (host_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="该主机尚未配置 K8S 凭证")
    if rows[0]["status"] == "disabled":
        raise HTTPException(status_code=409, detail="该主机的 K8S 凭证已停用")
    return rows[0]


def update_k8s_cluster_status(cluster_id: int, status: str, error: str | None) -> None:
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE k8s_clusters
                SET status = %s,
                    last_error = %s,
                    last_seen_at = IF(%s = 'active', NOW(), last_seen_at)
                WHERE id = %s
                """,
                (status, error, status, cluster_id),
            )
        connection.commit()
    finally:
        connection.close()


def _public_cluster(cluster: dict) -> dict:
    secret_fields = {"credential_ciphertext", "credential_nonce"}
    return {key: value for key, value in cluster.items() if key not in secret_fields}


def _format_host_port(host: str, port: int) -> str:
    normalized_host = host.strip()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"{normalized_host}:{port}"
