import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import execute_query, get_connection
from .k8s_client import get_workload_environment_keys
from .middleware_crypto import _encrypt_password, _decrypt_password, decrypt_middleware_password
from .nacos_client import fetch_nacos_config_content
from .nacos_config_redactor import NacosConfigParseError
from .nacos_value_selection import parse_config_document, selection_scope, verify_selection


class ValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    category: Literal["environment", "nacos"]
    reason: str = Field(default="", max_length=1000)
    release_ticket: str = Field(default="", max_length=200)
    release_version: str = Field(default="", max_length=200)
    host_id: int | None = Field(default=None, gt=0)
    namespace: str = Field(default="", max_length=63)
    kind: Literal["Deployment", "StatefulSet"] = "Deployment"
    workload: str = Field(default="", max_length=253)
    container: str = Field(default="", max_length=253)
    key: str = Field(default="", max_length=255)
    instance_id: int | None = Field(default=None, gt=0)
    namespace_id: str = Field(default="", max_length=255)
    group: str = Field(default="", max_length=255)
    data_id: str = Field(default="", max_length=255)
    line_number: int | None = Field(default=None, ge=1, le=40000, strict=True)
    config_type: Literal["yaml", "yml", "json"] | None = None
    config_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_target(self):
        if self.category == "environment":
            if not all((self.host_id, self.namespace, self.workload, self.container, self.key)):
                raise ValueError("请选择环境、工作负载、容器和 Key")
            if not self.key.isidentifier():
                raise ValueError("Key 格式无效")
        elif not all((self.instance_id, self.group, self.data_id)):
            raise ValueError("请选择 Nacos 实例、Group 和配置")
        elif self.category == "nacos" and not all((self.line_number, self.config_type, self.config_revision)):
            raise ValueError("Nacos 申请必须填写结构行号，并携带当前配置版本")
        return self

    def target(self):
        fields = ("host_id", "namespace", "kind", "workload", "container", "key") if self.category == "environment" else ("instance_id", "namespace_id", "group", "data_id", "line_number", "config_type", "config_revision")
        return self.model_dump(include=set(fields))


class ValueReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)
    validity_minutes: int = Field(default=60, ge=5, le=1440)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def live_permission(user_id, permission):
    # Read current grants so a cached login cannot outlive a permission revocation.
    rows = execute_query("""
        SELECT u.id FROM rbac_users u WHERE u.id=%s AND u.is_active=1 AND
        (u.is_superuser=1 OR EXISTS (
          SELECT 1 FROM rbac_user_roles ur
          JOIN rbac_roles r ON r.id=ur.role_id AND r.is_active=1
          JOIN rbac_role_permissions rp ON rp.role_id=r.id
          JOIN rbac_permissions p ON p.id=rp.permission_id AND p.is_active=1
          WHERE ur.user_id=u.id AND p.code=%s))
    """, (user_id, permission))
    if not rows:
        raise HTTPException(403, "当前账号没有此操作权限")


def source_permission(category):
    return "k8s:env:list" if category == "environment" else "nacos:config-structure:read"


def load_nacos(instance_id):
    rows = execute_query("""
        SELECT m.*, e.name AS environment_name FROM middleware_instances m
        JOIN infra_environments e ON e.id=m.environment_id
        WHERE m.id=%s AND m.middleware_type='nacos' AND m.status<>'disabled' AND e.is_active=1
    """, (instance_id,))
    if not rows:
        raise HTTPException(404, "Nacos 实例不存在或已停用")
    return rows[0]


def decode_target(row):
    return json.loads(row["target"]) if isinstance(row["target"], str) else row["target"]


def metadata(row):
    result = {key: value for key, value in row.items() if key not in {"snapshot_ciphertext", "snapshot_nonce"}}
    result["target"] = decode_target(row)
    if row["category"] == "nacos" and not is_scoped_target(result["target"]):
        result["status"] = "invalidated"
    elif row["status"] == "approved" and row["expires_at"] <= now_utc():
        result["status"] = "expired"
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.replace(tzinfo=timezone.utc).isoformat()
    return result


def is_scoped_target(target):
    return target.get("scope_version") == 1 and all(key in target for key in (
        "line_number", "config_path", "source_line", "source_end_line", "config_revision", "config_type"))


def load_document(source, target):
    try:
        password = decrypt_middleware_password(source["password_ciphertext"], source["password_nonce"])
        content = fetch_nacos_config_content(source["base_url"], source["username"], password,
            target["namespace_id"], target["group"], target["data_id"])
        return parse_config_document(content, target["config_type"], selection_scope(
            target["instance_id"], target["namespace_id"], target["group"], target["data_id"], target["config_type"]))
    except NacosConfigParseError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(502, "无法读取 Nacos 配置，请检查源服务后重试") from None


def aad(request_id):
    return f"ai-infraops:value-snapshot:v1:{request_id}".encode()


SELECT_META = """
    SELECT a.id,a.requester_id,u.username AS requester_name,a.category,
           a.environment_name,a.resource_name,a.target,a.reason,a.status,
           a.reviewer_id,r.username AS reviewer_name,a.review_note,a.created_at,
           a.reviewed_at,a.captured_at,a.expires_at,a.release_ticket,a.release_version
    FROM value_access_requests a JOIN rbac_users u ON u.id=a.requester_id
    LEFT JOIN rbac_users r ON r.id=a.reviewer_id
"""


def build_value_access_router(require_user, require_admin, get_cluster, require_namespace):
    router = APIRouter()

    def check_target(category, target):
        if category == "environment":
            require_namespace(target["host_id"], target["namespace"])
            cluster = get_cluster(target["host_id"], include_credentials=True)
            hosts = execute_query("""SELECT h.hostname,e.name AS environment_name
                FROM machine_hosts h JOIN infra_environments e ON e.id=h.environment_id
                WHERE h.id=%s AND e.is_active=1 AND h.status<>'disabled'""", (target["host_id"],))
            if not hosts:
                raise HTTPException(404, "主机不存在或已停用")
            return cluster, hosts[0]["environment_name"], hosts[0]["hostname"]
        instance = load_nacos(target["instance_id"])
        return instance, instance["environment_name"], instance["instance_name"]

    def admin_access(session):
        live_permission(session["user"]["id"], "admin:console:access")
        live_permission(session["user"]["id"], "value:approve")
        session["_audit_permission"] = "value:approve"

    @router.post("/api/value-requests", status_code=201)
    def create_request(payload: ValueRequest, response: Response, session=Depends(require_user)):
        response.headers["Cache-Control"] = "no-store"
        uid = session["user"]["id"]
        live_permission(uid, source_permission(payload.category))
        session["_audit_permission"] = source_permission(payload.category)
        target = payload.target()
        source, environment, resource = check_target(payload.category, target)
        if payload.category == "nacos":
            document = load_document(source, target)
            try:
                selected = verify_selection(document, target)
            except NacosConfigParseError as exc:
                raise HTTPException(409, str(exc)) from None
            target.update({key: selected[key] for key in ("config_path", "source_line", "source_end_line")})
            target["scope_version"] = 1
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO value_access_requests
                    (requester_id,category,environment_name,resource_name,target,reason,created_at,release_ticket,release_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (uid, payload.category, environment, resource, json.dumps(target), payload.reason, now_utc(), payload.release_ticket, payload.release_version))
                request_id = cursor.lastrowid
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"id": request_id, "status": "pending", "detail_path": f"/approvals/{request_id}"}

    def list_records(response, category, page, status, owner=None, date_from=None, date_to=None, keyword=""):
        response.headers["Cache-Control"] = "no-store"
        clauses, params = [], []
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "开始日期不能晚于结束日期")
        try:
            local_zone = timezone(timedelta(hours=8))
            if date_from:
                clauses.append("a.created_at>=%s")
                params.append(datetime.combine(date_from, time.min, local_zone).astimezone(timezone.utc).replace(tzinfo=None))
            if date_to:
                clauses.append("a.created_at<=%s")
                params.append(datetime.combine(date_to, time.max, local_zone).astimezone(timezone.utc).replace(tzinfo=None))
        except OverflowError:
            raise HTTPException(422, "日期超出支持范围") from None
        if keyword.strip():
            pattern = "%" + keyword.strip().replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"
            clauses.append("(a.environment_name LIKE %s ESCAPE '=' OR a.resource_name LIKE %s ESCAPE '=' OR a.target LIKE %s ESCAPE '=' OR u.username LIKE %s ESCAPE '=' OR a.release_ticket LIKE %s ESCAPE '=')")
            params.extend([pattern] * 5)
        if owner is not None:
            clauses.append("a.requester_id=%s")
            params.append(owner)
        if category:
            clauses.append("a.category=%s")
            params.append(category)
        if status:
            if status == "expired":
                clauses.append("a.status='approved' AND a.expires_at<=%s")
                params.append(now_utc())
            elif status == "approved":
                clauses.append("a.status='approved' AND a.expires_at>%s")
                params.append(now_utc())
            else:
                clauses.append("a.status=%s")
                params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        count = execute_query("SELECT COUNT(*) AS total FROM value_access_requests a JOIN rbac_users u ON u.id=a.requester_id" + where, tuple(params))[0]["total"]
        rows = execute_query(SELECT_META + where + " ORDER BY a.created_at DESC,a.id DESC LIMIT 20 OFFSET %s", (*params, (page-1)*20))
        return {"items": [metadata(row) for row in rows], "total": count, "page": page,
                "server_now": now_utc().replace(tzinfo=timezone.utc).isoformat()}

    @router.get("/api/value-requests")
    def own_requests(response: Response, category: Literal["environment", "nacos"] | None = None,
                     status: Literal["pending", "approved", "rejected", "expired", "invalidated"] | None = None,
                     date_from: date | None = None, date_to: date | None = None,
                     keyword: str = Query(default="", max_length=200),
                     page: int = Query(default=1, ge=1), session=Depends(require_user)):
        uid = session["user"]["id"]
        if category:
            live_permission(uid, source_permission(category))
        else:
            if not execute_query("SELECT id FROM rbac_users WHERE id=%s AND is_active=1", (uid,)):
                raise HTTPException(403, "账号已停用")
        return list_records(response, category, page, status, uid, date_from, date_to, keyword)

    @router.get("/api/admin/value-requests")
    def all_requests(response: Response, category: Literal["environment", "nacos"] | None = None,
                     status: Literal["pending", "approved", "rejected", "expired", "invalidated"] | None = None,
                     date_from: date | None = None, date_to: date | None = None,
                     keyword: str = Query(default="", max_length=200),
                     page: int = Query(default=1, ge=1), session=Depends(require_admin)):
        admin_access(session)
        return list_records(response, category, page, status, date_from=date_from, date_to=date_to, keyword=keyword)

    @router.get("/api/value-requests/{request_id}")
    def request_detail(request_id: int, response: Response, session=Depends(require_user)):
        response.headers["Cache-Control"] = "no-store, private"
        rows = execute_query(SELECT_META + " WHERE a.id=%s", (request_id,))
        if not rows:
            raise HTTPException(404, "申请不存在或无权访问")
        row = rows[0]
        owner = row["requester_id"] == session["user"]["id"]
        administrator = False
        try:
            admin_access(session)
            administrator = True
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
        if owner and not administrator:
            session["_audit_permission"] = source_permission(row["category"])
            live_permission(session["user"]["id"], source_permission(row["category"]))
        elif not owner and not administrator:
            raise HTTPException(404, "申请不存在或无权访问")
        item = metadata(row)
        item["can_review"] = administrator and not owner and item["status"] == "pending"
        item["can_view_value"] = (owner or administrator) and item["status"] in {"approved", "expired"}
        return {"items": [item], "total": 1, "page": 1,
                "server_now": now_utc().replace(tzinfo=timezone.utc).isoformat()}

    @router.post("/api/value-requests/{request_id}/review")
    def review_from_detail(request_id: int, payload: ValueReview, response: Response, session=Depends(require_user)):
        # The shared detail page uses a user-web login; the same live administrator checks still apply.
        return review(request_id, payload, response, session)

    @router.post("/api/admin/value-requests/{request_id}/review")
    def review(request_id: int, payload: ValueReview, response: Response, session=Depends(require_admin)):
        response.headers["Cache-Control"] = "no-store"
        admin_access(session)
        rows = execute_query(SELECT_META + " WHERE a.id=%s", (request_id,))
        if not rows:
            raise HTTPException(404, "申请不存在")
        row = rows[0]
        if row["category"] == "nacos" and not is_scoped_target(decode_target(row)):
            raise HTTPException(409, "旧的整份配置申请已失效，请按行号重新申请")
        if row["requester_id"] == session["user"]["id"]:
            raise HTTPException(403, "不能审批自己的申请")
        if row["status"] != "pending":
            raise HTTPException(409, "该申请已处理，请刷新")
        ciphertext = nonce = captured_at = expires_at = None
        if payload.decision == "approved":
            live_permission(row["requester_id"], source_permission(row["category"]))
            target = decode_target(row)
            source, _, _ = check_target(row["category"], target)
            try:
                if row["category"] == "environment":
                    snapshot = get_workload_environment_keys(source, target["namespace"], target["kind"],
                        target["workload"], value_container=target["container"], value_key=target["key"])
                else:
                    document = load_document(source, target)
                    try:
                        selected = verify_selection(document, target)
                    except NacosConfigParseError as exc:
                        raise HTTPException(409, str(exc)) from None
                    snapshot = {**target, "value": selected["value"]}
                captured_at = now_utc()
                encoded = json.dumps(snapshot, ensure_ascii=False)
                if len(encoded.encode()) > 2 * 1024 * 1024:
                    raise ValueError("snapshot too large")
                ciphertext, nonce = _encrypt_password(encoded, aad(request_id))
                expires_at = captured_at + timedelta(minutes=payload.validity_minutes)
            except HTTPException:
                raise
            except Exception:
                # Do not return source errors, which can contain secret-bearing output.
                raise HTTPException(502, "采集数值失败，申请仍待审批。请检查源服务、Key 和权限后重试") from None
        admin_access(session)
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""UPDATE value_access_requests SET status=%s,reviewer_id=%s,
                    review_note=%s,reviewed_at=%s,captured_at=%s,expires_at=%s,
                    snapshot_ciphertext=%s,snapshot_nonce=%s WHERE id=%s AND status='pending'""",
                    (payload.decision,session["user"]["id"],payload.note,now_utc(),captured_at,expires_at,
                     ciphertext,nonce,request_id))
                if cursor.rowcount != 1:
                    raise HTTPException(409, "该申请已被其他管理员处理")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"id": request_id, "status": payload.decision}

    def historical_snapshot(request_id, response, session, administrative=False):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        if administrative:
            admin_access(session)
            rows = execute_query("SELECT * FROM value_access_requests WHERE id=%s", (request_id,))
        else:
            rows = execute_query("SELECT * FROM value_access_requests WHERE id=%s AND requester_id=%s",
                                 (request_id, session["user"]["id"]))
            if not rows:
                try:
                    admin_access(session)
                except HTTPException as exc:
                    if exc.status_code == 403:
                        raise HTTPException(404, "申请不存在或无权访问") from None
                    raise
                administrative = True
                rows = execute_query("SELECT * FROM value_access_requests WHERE id=%s", (request_id,))
        if not rows:
            raise HTTPException(404, "申请不存在")
        row = rows[0]
        target = decode_target(row)
        if row["category"] == "nacos" and not is_scoped_target(target):
            raise HTTPException(410, "旧的整份配置授权已失效，请按行号重新申请")
        if not administrative:
            try:
                live_permission(session["user"]["id"], source_permission(row["category"]))
                session["_audit_permission"] = source_permission(row["category"])
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
                admin_access(session)
        if row["status"] != "approved":
            raise HTTPException(403, "申请尚未通过审批")
        # Historical reads never contact the source or expand the original approved scope.
        try:
            snapshot = json.loads(_decrypt_password(row["snapshot_ciphertext"], row["snapshot_nonce"], aad(request_id)))
        except Exception:
            raise HTTPException(503, "快照暂时无法读取") from None
        if row["category"] == "nacos":
            binding = ("scope_version", "instance_id", "namespace_id", "group", "data_id", "line_number",
                       "config_path", "source_line", "source_end_line", "config_type", "config_revision")
            if any(snapshot.get(key) != target.get(key) for key in binding):
                raise HTTPException(410, "快照授权范围不匹配，请重新申请")
        return {"snapshot": snapshot, "captured_at": row["captured_at"].replace(tzinfo=timezone.utc).isoformat(),
                "historical": True,
                "server_now": now_utc().replace(tzinfo=timezone.utc).isoformat(),
                "expires_at": row["expires_at"].replace(tzinfo=timezone.utc).isoformat()}

    @router.get("/api/value-requests/{request_id}/value")
    def read_value(request_id: int, response: Response, session=Depends(require_user)):
        return historical_snapshot(request_id, response, session)

    @router.get("/api/admin/value-requests/{request_id}/value")
    def read_admin_value(request_id: int, response: Response, session=Depends(require_admin)):
        return historical_snapshot(request_id, response, session, administrative=True)

    return router
