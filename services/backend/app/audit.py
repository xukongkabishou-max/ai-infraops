from __future__ import annotations

import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .db import get_connection
from .logging_config import request_id_context


logger = logging.getLogger("infraops.audit")


def attach_audit_session(request: Request, session: dict, client_type: str) -> None:
    request.state.auth_session = session
    request.state.auth_client_type = client_type


def mark_permission(session: dict, permission_code: str) -> None:
    session["_audit_permission"] = permission_code


def record_audit_event(
    request: Request,
    *,
    action: str,
    status_code: int,
    session: dict | None = None,
    client_type: str = "",
    permission_code: str = "",
    actor_username: str = "",
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    session = session or {}
    user = session.get("user", {})
    result = "success" if status_code < 400 else "denied" if status_code in {401, 403} else "error"
    role_codes = session.get("roles", [])
    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rbac_audit_events (
                    request_id, actor_user_id, actor_username, role_codes,
                    client_type, action, permission_code, resource_type,
                    resource_id, request_method, request_path, result,
                    status_code, source_ip, user_agent, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    request_id_context.get(),
                    user.get("id"),
                    actor_username or user.get("username", ""),
                    json.dumps(role_codes, ensure_ascii=True),
                    client_type or session.get("client_type", ""),
                    action,
                    permission_code or session.get("_audit_permission", ""),
                    resource_type,
                    resource_id,
                    request.method,
                    request.url.path,
                    result,
                    status_code,
                    request.client.host if request.client else "",
                    request.headers.get("user-agent", "")[:512],
                    json.dumps(details, ensure_ascii=True) if details else None,
                ),
            )
        connection.commit()
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        logger.warning(
            "安全审计事件写入失败",
            extra={"event": "security_audit_write_failed", "error_type": type(exc).__name__},
        )
    finally:
        if connection is not None:
            connection.close()


class SecurityAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            session = getattr(request.state, "auth_session", None)
            if session:
                record_audit_event(
                    request,
                    action="api_request",
                    status_code=500,
                    session=session,
                    client_type=getattr(request.state, "auth_client_type", ""),
                )
            raise

        session = getattr(request.state, "auth_session", None)
        if session:
            record_audit_event(
                request,
                action="api_request",
                status_code=response.status_code,
                session=session,
                client_type=getattr(request.state, "auth_client_type", ""),
            )
        return response
