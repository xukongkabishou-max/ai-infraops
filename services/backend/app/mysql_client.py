from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import MySQLError, OperationalError, ProgrammingError

from .config import settings


class MySQLIntegrationError(RuntimeError):
    pass


def fetch_mysql_accounts(
    connection_address: str,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    host, port = _parse_connection_address(connection_address)
    connection = None
    try:
        connection = _connect(host, port, username, password, DictCursor)
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    SELECT User, Host, plugin, account_locked, password_expired
                    FROM mysql.user
                    ORDER BY User, Host
                    """
                )
            except ProgrammingError as exc:
                if not exc.args or exc.args[0] != 1054:
                    raise
                cursor.execute(
                    """
                    SELECT User, Host, plugin
                    FROM mysql.user
                    ORDER BY User, Host
                    """
                )
            rows = cursor.fetchall()
    except OperationalError as exc:
        raise _translate_operational_error(exc, "账号查询") from exc
    except ProgrammingError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code in {1044, 1142, 1227}:
            raise MySQLIntegrationError(
                "MySQL 登记账号没有读取 mysql.user 的权限"
            ) from exc
        raise MySQLIntegrationError("MySQL 账号查询失败") from exc
    except (MySQLError, OSError) as exc:
        raise MySQLIntegrationError("MySQL 账号查询失败") from exc
    finally:
        if connection is not None:
            connection.close()

    return [_map_account_row(row) for row in rows]


def verify_mysql_account_password(
    connection_address: str,
    user_identity: str,
    candidate_password: str,
) -> bool:
    host, port = _parse_connection_address(connection_address)
    expected_username, expected_host = _parse_user_identity(user_identity)
    connection = None
    try:
        connection = _connect(host, port, expected_username, candidate_password)
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER()")
            row = cursor.fetchone()
    except OperationalError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code == 1045:
            return False
        raise _translate_operational_error(exc, "密码校验") from exc
    except (MySQLError, OSError) as exc:
        raise MySQLIntegrationError("MySQL 密码校验失败") from exc
    finally:
        if connection is not None:
            connection.close()

    current_identity = row[0] if row else ""
    try:
        current_username, current_host = _parse_user_identity(str(current_identity))
    except MySQLIntegrationError:
        return False
    return (current_username, current_host) == (expected_username, expected_host)


def set_mysql_account_password(
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
        connection = _connect(host, port, admin_username, admin_password)
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER USER {quoted_identity} IDENTIFIED BY %s",
                (new_password,),
            )
    except OperationalError as exc:
        error_code = exc.args[0] if exc.args else None
        if error_code in {1044, 1142, 1227}:
            raise MySQLIntegrationError(
                "MySQL 登记账号没有修改用户密码的权限"
            ) from exc
        raise _translate_operational_error(exc, "密码修改") from exc
    except (MySQLError, OSError) as exc:
        raise MySQLIntegrationError("MySQL 密码修改失败") from exc
    finally:
        if connection is not None:
            connection.close()


def _connect(
    host: str,
    port: int,
    username: str,
    password: str,
    cursorclass=None,
):
    options = {
        "host": host,
        "port": port,
        "user": username,
        "password": password,
        "charset": "utf8mb4",
        "connect_timeout": settings.doris_connect_timeout_seconds,
        "read_timeout": settings.doris_read_timeout_seconds,
        "write_timeout": settings.doris_read_timeout_seconds,
        "autocommit": True,
    }
    if cursorclass is not None:
        options["cursorclass"] = cursorclass
    return pymysql.connect(**options)


def _translate_operational_error(
    exc: OperationalError,
    operation: str,
) -> MySQLIntegrationError:
    error_code = exc.args[0] if exc.args else None
    if error_code == 1045:
        return MySQLIntegrationError("MySQL 管理凭证认证失败")
    if error_code in {2002, 2003, 2013}:
        return MySQLIntegrationError("无法连接 MySQL 服务")
    return MySQLIntegrationError(f"MySQL {operation}失败")


def _parse_connection_address(connection_address: str) -> tuple[str, int]:
    parts = urlsplit(connection_address)
    if parts.scheme != "mysql" or not parts.hostname or parts.port is None:
        raise MySQLIntegrationError("MySQL 连接地址格式无效")
    return parts.hostname, parts.port


def _map_account_row(row: dict[str, Any]) -> dict[str, Any]:
    username = str(row.get("User") or "")
    host = str(row.get("Host") or "")
    details = []
    plugin = str(row.get("plugin") or "").strip()
    if plugin:
        details.append(f"认证插件：{plugin}")
    if str(row.get("account_locked") or "").upper() == "Y":
        details.append("账号已锁定")
    if str(row.get("password_expired") or "").upper() == "Y":
        details.append("密码已过期")
    return {
        "user_identity": _quote_user_identity(username, host),
        "username": username,
        "host": host,
        "comment": "；".join(details),
        "roles": [],
        "privileges": [],
    }


def _parse_user_identity(identity: str) -> tuple[str, str]:
    quoted_match = re.fullmatch(r"'((?:''|[^'])*)'@'((?:''|[^'])*)'", identity)
    if quoted_match:
        return tuple(value.replace("''", "'") for value in quoted_match.groups())

    plain_match = re.fullmatch(r"([^@\s]+)@([^@\s]+)", identity)
    if plain_match:
        return plain_match.group(1), plain_match.group(2)

    raise MySQLIntegrationError("MySQL 用户标识格式无效")


def _quote_user_identity(username: str, host: str) -> str:
    def quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"

    return f"{quote(username)}@{quote(host)}"
