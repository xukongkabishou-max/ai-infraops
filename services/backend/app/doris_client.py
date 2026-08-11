from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import MySQLError, OperationalError

from .config import settings


class DorisIntegrationError(RuntimeError):
    pass


SENSITIVE_COLUMNS = {
    "password",
    "passwordhash",
    "password_hash",
    "authenticationstring",
    "authentication_string",
}

PRIVILEGE_LABELS = {
    "globalprivs": "全局权限",
    "catalogprivs": "Catalog 权限",
    "databaseprivs": "数据库权限",
    "tableprivs": "表权限",
    "colprivs": "列权限",
    "resourceprivs": "资源权限",
    "workloadgroupprivs": "Workload Group 权限",
    "cloudclusterprivs": "Cloud Cluster 权限",
    "cloudstageprivs": "Cloud Stage 权限",
    "storagevaultprivs": "Storage Vault 权限",
}


def fetch_doris_accounts(
    connection_address: str,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    host, port = _parse_connection_address(connection_address)
    connection = None
    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            charset="utf8mb4",
            connect_timeout=settings.doris_connect_timeout_seconds,
            read_timeout=settings.doris_read_timeout_seconds,
            write_timeout=settings.doris_read_timeout_seconds,
            autocommit=True,
            cursorclass=DictCursor,
        )
        with connection.cursor() as cursor:
            cursor.execute("SHOW ALL GRANTS")
            rows = cursor.fetchall()
    except OperationalError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code == 1045:
            raise DorisIntegrationError("Doris 凭证认证失败") from exc
        if error_code in {1044, 1142, 1227}:
            raise DorisIntegrationError(
                "Doris 登记账号没有执行 SHOW ALL GRANTS 的权限"
            ) from exc
        if error_code in {2002, 2003, 2013}:
            raise DorisIntegrationError("无法连接 Doris FE 查询端口") from exc
        raise DorisIntegrationError("Doris 账号查询失败") from exc
    except (MySQLError, OSError) as exc:
        raise DorisIntegrationError("Doris 账号查询失败") from exc
    finally:
        if connection is not None:
            connection.close()

    return [_map_account_row(row) for row in rows]


def verify_doris_account_password(
    connection_address: str,
    user_identity: str,
    candidate_password: str,
) -> bool:
    host, port = _parse_connection_address(connection_address)
    expected_username, expected_host = _parse_user_identity(user_identity)
    connection = None
    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=expected_username,
            password=candidate_password,
            charset="utf8mb4",
            connect_timeout=settings.doris_connect_timeout_seconds,
            read_timeout=settings.doris_read_timeout_seconds,
            write_timeout=settings.doris_read_timeout_seconds,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER()")
            row = cursor.fetchone()
    except OperationalError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code == 1045:
            return False
        if error_code in {2002, 2003, 2013}:
            raise DorisIntegrationError("无法连接 Doris FE 查询端口") from exc
        raise DorisIntegrationError("Doris 密码校验失败") from exc
    except (MySQLError, OSError) as exc:
        raise DorisIntegrationError("Doris 密码校验失败") from exc
    finally:
        if connection is not None:
            connection.close()

    current_identity = row[0] if row else ""
    try:
        current_username, current_host = _parse_user_identity(str(current_identity))
    except DorisIntegrationError:
        return False
    return (current_username, current_host) == (expected_username, expected_host)


def set_doris_account_password(
    connection_address: str,
    admin_username: str,
    admin_password: str,
    user_identity: str,
    new_password: str,
) -> None:
    host, port = _parse_connection_address(connection_address)
    username, account_host = _parse_user_identity(user_identity)
    quoted_identity = _quote_user_identity(username, account_host)
    connection = None
    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=admin_username,
            password=admin_password,
            charset="utf8mb4",
            connect_timeout=settings.doris_connect_timeout_seconds,
            read_timeout=settings.doris_read_timeout_seconds,
            write_timeout=settings.doris_read_timeout_seconds,
            autocommit=True,
        )
        escaped_password = connection.escape(new_password)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET PASSWORD FOR {quoted_identity} = PASSWORD({escaped_password})"
            )
    except OperationalError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code == 1045:
            raise DorisIntegrationError("Doris 管理凭证认证失败") from exc
        if error_code in {1044, 1142, 1227}:
            raise DorisIntegrationError("Doris 登记账号没有修改用户密码的权限") from exc
        if error_code in {2002, 2003, 2013}:
            raise DorisIntegrationError("无法连接 Doris FE 查询端口") from exc
        raise DorisIntegrationError("Doris 密码修改失败") from exc
    except (MySQLError, OSError) as exc:
        raise DorisIntegrationError("Doris 密码修改失败") from exc
    finally:
        if connection is not None:
            connection.close()


def _parse_connection_address(connection_address: str) -> tuple[str, int]:
    parts = urlsplit(connection_address)
    if parts.scheme != "mysql" or not parts.hostname or parts.port is None:
        raise DorisIntegrationError("Doris FE 连接地址格式无效")
    return parts.hostname, parts.port


def _map_account_row(row: dict[str, Any]) -> dict[str, Any]:
    safe_row = {
        str(column): value
        for column, value in row.items()
        if _normalized_column(column) not in SENSITIVE_COLUMNS
    }
    user_identity = _find_value(safe_row, "useridentity", "user_identity")
    username, host = _split_user_identity(user_identity)
    roles = _split_csv(_find_value(safe_row, "roles"))
    privileges = []
    for column, value in safe_row.items():
        normalized = _normalized_column(column)
        if normalized not in PRIVILEGE_LABELS or _is_empty_value(value):
            continue
        privileges.append(
            {
                "scope": PRIVILEGE_LABELS[normalized],
                "value": str(value),
            }
        )
    return {
        "user_identity": user_identity,
        "username": username,
        "host": host,
        "comment": _find_value(safe_row, "comment"),
        "roles": roles,
        "privileges": privileges,
    }


def _normalized_column(column: object) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(column).lower())


def _find_value(row: dict[str, Any], *names: str) -> str:
    expected = set(names)
    for column, value in row.items():
        if _normalized_column(column) in expected and not _is_empty_value(value):
            return str(value)
    return ""


def _split_user_identity(identity: str) -> tuple[str, str]:
    match = re.fullmatch(r"'((?:''|[^'])*)'@'((?:''|[^'])*)'", identity)
    if not match:
        return identity, ""
    return match.group(1).replace("''", "'"), match.group(2).replace("''", "'")


def _parse_user_identity(identity: str) -> tuple[str, str]:
    quoted_match = re.fullmatch(r"'((?:''|[^'])*)'@'((?:''|[^'])*)'", identity)
    if quoted_match:
        return (
            quoted_match.group(1).replace("''", "'"),
            quoted_match.group(2).replace("''", "'"),
        )
    plain_match = re.fullmatch(r"([^@\s]+)@([^@\s]+)", identity)
    if plain_match:
        return plain_match.group(1), plain_match.group(2)
    raise DorisIntegrationError("Doris 用户标识格式无效")


def _quote_user_identity(username: str, host: str) -> str:
    def quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    return f"{quote(username)}@{quote(host)}"


def _split_csv(value: str) -> list[str]:
    return [item.strip().strip("'") for item in value.split(",") if item.strip()]


def _is_empty_value(value: Any) -> bool:
    return value is None or str(value).strip().upper() in {"", "NULL"}
