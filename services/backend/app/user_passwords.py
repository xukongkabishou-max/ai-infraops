from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from .audit import mark_permission, record_audit_event
from .db import get_connection
from .middleware_crypto import _decrypt_password, _encrypt_password


class PasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: SecretStr
    confirm_password: SecretStr

    @model_validator(mode="after")
    def validate_password(self):
        password = self.new_password.get_secret_value()
        if not password.strip() or len(password.encode("utf-8")) > 72:
            raise ValueError("密码不能为空，且不能超过 72 个 UTF-8 字节")
        if password != self.confirm_password.get_secret_value():
            raise ValueError("两次输入的密码不一致")
        return self


class PasswordRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # FastAPI's default validation response includes submitted input.
                raise HTTPException(422, "请填写两次相同的非空密码，且不超过 72 个 UTF-8 字节") from None
        return handler


def password_aad(user_id: int) -> bytes:
    return f"ai-infraops:rbac-user-password:v1:{user_id}".encode()


def build_user_password_router(require_admin, password_context):
    router = APIRouter(route_class=PasswordRoute)

    @router.put("/api/rbac/users/{user_id}/password")
    def reset_password(user_id: int, payload: PasswordRequest, request: Request,
                       response: Response, session=Depends(require_admin)):
        response.headers["Cache-Control"] = "no-store"
        mark_permission(session, "user:password:reset")
        operator_id = session["user"]["id"]
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                # Deterministic locking also covers two administrators changing each other's passwords.
                cursor.execute("""SELECT id,username,is_active,is_superuser,auth_version FROM rbac_users
                    WHERE id IN (%s,%s) ORDER BY id FOR UPDATE""", (operator_id, user_id))
                users = {row["id"]: row for row in cursor.fetchall()}
                operator = users.get(operator_id)
                if not operator or not operator["is_active"] or not operator["is_superuser"]:
                    raise HTTPException(403, "仅超级管理员可以修改用户密码")
                if session.get("_auth_version", 0) != operator["auth_version"]:
                    raise HTTPException(401, "登录已失效，请重新登录")
                target = users.get(user_id)
                if not target:
                    raise HTTPException(404, "用户不存在")
                if target["username"] == "admin" and operator["username"] != "admin":
                    raise HTTPException(403, "admin 的密码仅允许 admin 本人修改")
                password = payload.new_password.get_secret_value()
                try:
                    hashed = password_context.hash(password)
                    ciphertext, nonce = _encrypt_password(password, password_aad(user_id))
                except Exception:
                    raise HTTPException(503, "密码保存失败，请检查服务端加密配置") from None
                changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                cursor.execute("""UPDATE rbac_users SET password_hash=%s, password_ciphertext=%s,
                    password_nonce=%s,password_changed_at=%s,auth_version=auth_version+1 WHERE id=%s""",
                    (hashed, ciphertext, nonce, changed_at, user_id))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        record_audit_event(request, action="user_password_reset", status_code=200, session=session,
            client_type="backend_admin_web", resource_type="rbac_user", resource_id=str(user_id),
            details={"target_username": target["username"], "sessions_invalidated": True})
        return {"changed": True, "user_id": user_id, "reauthenticate": operator_id == user_id,
                "sessions_invalidated": True}

    @router.get("/api/rbac/users/{user_id}/password")
    def read_password(user_id: int, request: Request, response: Response, session=Depends(require_admin)):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        mark_permission(session, "user:password:read")
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT username,is_active,is_superuser,auth_version FROM rbac_users WHERE id=%s",
                               (session["user"]["id"],))
                operator = cursor.fetchone()
                if not operator or operator["username"] != "admin" or not operator["is_active"] or not operator["is_superuser"]:
                    raise HTTPException(403, "仅 admin 超级管理员可以查看明文密码")
                if session.get("_auth_version", 0) != operator["auth_version"]:
                    raise HTTPException(401, "登录已失效，请重新登录")
                cursor.execute("""SELECT username,password_hash,password_ciphertext,password_nonce,password_changed_at
                    FROM rbac_users WHERE id=%s""", (user_id,))
                target = cursor.fetchone()
        finally:
            connection.close()
        if not target:
            raise HTTPException(404, "用户不存在")
        password = None
        if target["password_ciphertext"] and target["password_nonce"]:
            try:
                candidate = _decrypt_password(target["password_ciphertext"], target["password_nonce"], password_aad(user_id))
                if password_context.verify(candidate, target["password_hash"]):
                    password = candidate
            except Exception:
                raise HTTPException(503, "已记录密码暂时无法解密") from None
        record_audit_event(request, action="user_password_view", status_code=200, session=session,
            client_type="backend_admin_web", resource_type="rbac_user", resource_id=str(user_id),
            details={"target_username": target["username"], "available": password is not None})
        return {"user_id": user_id, "available": password is not None, "password": password,
                "changed_at": target["password_changed_at"].replace(tzinfo=timezone.utc).isoformat() if target["password_changed_at"] else None}

    return router
