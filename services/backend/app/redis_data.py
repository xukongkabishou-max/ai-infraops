import base64
import hashlib
import json
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import quote

import redis
from redis.cluster import RedisCluster, ClusterNode
from redis.exceptions import RedisClusterException, RedisError, TimeoutError as RedisTimeout
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .audit import mark_permission, record_audit_event
from .db import execute_query, transaction
from .db import get_connection
from .middleware_crypto import decrypt_middleware_password
from .config import ROOT_DIR


class RedisDataError(RuntimeError):
    pass


_pools = {}
_pool_lock = Lock()
_KEY_RE = re.compile(r"^[\x20-\x7e\u4e00-\u9fff]{1,512}$")
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_IMPORT_BYTES = 16 * 1024 * 1024
_MAX_IMPORT_FILES = 3
_MAX_SCAN_PAGE = 100
_MAX_VALUE_PREVIEW_BYTES = 64 * 1024
_MAX_COLLECTION_ITEMS = 500
_MAX_TEXT_PREVIEW = 4096


class RedisKeyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=512)
    db: int = Field(default=0, ge=0)
    type: Literal["string", "hash", "list", "set", "zset"]
    value: object
    ttl_seconds: int = Field(default=0, ge=0, le=315360000)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def parse_endpoints(value):
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = [part.strip() for part in value.split(",")]
    else:
        parsed = value or []
    endpoints = []
    for item in parsed:
        if isinstance(item, dict):
            host = str(item.get("host", "")).strip()
            port = int(item.get("port", 6379))
        else:
            text = str(item).strip().replace("redis://", "").rstrip("/")
            if not text:
                continue
            host, _, port_text = text.partition(":")
            host = host.strip("[]")
            port = int(port_text or 6379)
        if not host or not 1 <= port <= 65535:
            raise RedisDataError("Redis 节点地址无效")
        endpoints.append({"host": host, "port": port})
    if not endpoints:
        raise RedisDataError("Redis 实例缺少可用节点")
    return endpoints


def config_endpoints(config):
    raw = config.get("bootstrap_endpoints_json", "[]")
    return parse_endpoints(raw if isinstance(raw, (list, dict)) else str(raw))


def instance_fingerprint(instance, config):
    return fingerprint([instance["base_url"], config["deployment_mode"], config_endpoints(config)])


@contextmanager
def connect(instance, config, db_index=0):
    endpoints = config_endpoints(config)
    mode = config.get("deployment_mode", "standalone")
    if mode == "cluster" and int(db_index) != 0:
        raise RedisDataError("Redis Cluster 只能使用 DB 0")
    password = decrypt_middleware_password(
        instance["password_ciphertext"], instance["password_nonce"]
    )
    pool_key = fingerprint([
        mode, endpoints, int(db_index), instance["username"],
        password, bool(config.get("tls_enabled")),
        bool(config.get("verify_tls")),
    ])
    now = datetime.now(timezone.utc).timestamp()
    with _pool_lock:
        for key in [key for key, (_, used) in _pools.items() if now - used > 600]:
            _pools[key][0].disconnect()
            del _pools[key]
        if pool_key not in _pools:
            timeout = int(config.get("connect_timeout_ms", 4000)) / 1000
            read_timeout = int(config.get("read_timeout_ms", 6000)) / 1000
            common = {
                "username": instance.get("username") or None,
                "password": password or None,
                "decode_responses": False,
                "socket_connect_timeout": timeout,
                "socket_timeout": read_timeout,
                "health_check_interval": 30,
            }
            if config.get("tls_enabled"):
                common.update(ssl=True, ssl_cert_reqs="required" if config.get("verify_tls") else "none")
            if mode == "cluster":
                nodes = [ClusterNode(item["host"], item["port"]) for item in endpoints]
                client = RedisCluster(startup_nodes=nodes, require_full_coverage=False, **common)
            else:
                endpoint = endpoints[0]
                client = redis.Redis(
                    host=endpoint["host"], port=endpoint["port"], db=int(db_index), **common
                )
            _pools[pool_key] = (client, now)
        else:
            _pools[pool_key] = (_pools[pool_key][0], now)
    client = _pools[pool_key][0]
    try:
        yield client
    except (RedisClusterException, RedisError, RedisTimeout, OSError) as exc:
        message = str(exc).strip()
        code = getattr(exc, "args", [None])[0]
        raise RedisDataError(f"Redis 操作失败：{code or '连接错误'}；请检查网络、凭证、DB 或集群状态") from None


def dispose_redis_pools():
    with _pool_lock:
        for client, _ in _pools.values():
            try:
                client.close()
            except Exception:
                pass
        _pools.clear()


def decode_text(value, preview=False):
    if isinstance(value, str):
        return value
    try:
        return bytes(value).decode("utf-8")
    except (UnicodeDecodeError, TypeError):
        text = base64.b64encode(bytes(value)).decode("ascii")
    if preview and len(text) > _MAX_TEXT_PREVIEW:
        return text[:_MAX_TEXT_PREVIEW] + " ...[truncated]"
    return text


def parse_cluster_nodes(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    nodes = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 8:
            continue
        node_id, address, flags, _, ping, pong, _, link = fields[:8]
        host, _, port_text = address.rpartition(":")
        port_text = port_text.split("@", 1)[0]
        if not host or not port_text.isdigit():
            continue
        slots = []
        for token in fields[8:]:
            if re.fullmatch(r"\d+-\d+|\d+", token):
                slots.append(token)
        nodes.append({
            "node_id": node_id,
            "host": host,
            "port": int(port_text),
            "role": "master" if "master" in flags else "replica",
            "status": "active" if "fail" not in flags and link == "connected" else "unreachable",
            "slots": slots,
        })
    if not nodes:
        raise RedisDataError("无法解析 Redis Cluster 节点拓扑")
    return nodes


def refresh_topology(instance, config):
    mode = config.get("deployment_mode", "standalone")
    endpoints = config_endpoints(config)
    with connect(instance, config) as client:
        client.ping()
        if mode == "cluster":
            raw_nodes = client.cluster("NODES")
            nodes = parse_cluster_nodes(raw_nodes)
        else:
            info = client.info("replication")
            nodes = [{
                "node_id": info.get("run_id") or "",
                "host": endpoints[0]["host"],
                "port": endpoints[0]["port"],
                "role": info.get("role", "standalone"),
                "status": "active",
                "slots": [],
            }]
    topology = {"mode": mode, "nodes": sorted(nodes, key=lambda item: (item["host"], item["port"]))}
    mark = utcnow()
    return topology, fingerprint(topology), nodes, mark


def validate_db(config, db_index):
    db_index = int(db_index)
    if config.get("deployment_mode") == "cluster" and db_index != 0:
        raise HTTPException(422, "Redis Cluster 只能使用 DB 0")
    if not 0 <= db_index < int(config.get("database_count", 16)):
        raise HTTPException(422, "DB 编号超出实例配置范围")
    return db_index


def scan_keys(client, cursor, pattern, limit):
    raw_cursor, keys = client.scan(int(cursor), match=pattern, count=limit)
    keys = keys[:limit]
    items = []
    for raw_key in keys:
        key = decode_text(raw_key)
        key_type = decode_text(client.type(raw_key)).lower()
        ttl = client.ttl(raw_key)
        items.append({
            "key": key,
            "type": key_type,
            "ttl": int(ttl),
            "persistent": int(ttl) == -1,
        })
    return int(raw_cursor), items


def key_detail(client, key, max_value_bytes):
    raw_key = key.encode("utf-8")
    key_type = decode_text(client.type(raw_key)).lower()
    if key_type == "none":
        raise HTTPException(404, "Redis key 不存在")
    max_value_bytes = min(int(max_value_bytes), _MAX_VALUE_PREVIEW_BYTES)
    ttl = int(client.ttl(raw_key))
    value = None
    length = 0
    truncated = False
    if key_type == "string":
        raw = client.get(raw_key) or b""
        length = len(raw)
        truncated = length > max_value_bytes
        raw = raw[:max_value_bytes]
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            value = base64.b64encode(raw).decode("ascii")
    elif key_type == "hash":
        _, pairs = client.hscan(raw_key, cursor=0, count=_MAX_COLLECTION_ITEMS)
        value = {decode_text(k, True): decode_text(v, True)
                 for k, v in list(pairs.items())[:_MAX_COLLECTION_ITEMS]}
        length = len(value)
        truncated = length > _MAX_COLLECTION_ITEMS
        value = dict(list(value.items())[:_MAX_COLLECTION_ITEMS])
    elif key_type == "list":
        value = [decode_text(item) for item in client.lrange(raw_key, 0, 199)]
        length = int(client.llen(raw_key) or 0)
        truncated = length > len(value)
    elif key_type == "set":
        _, members = client.sscan(raw_key, cursor=0, count=_MAX_COLLECTION_ITEMS)
        value = sorted(decode_text(item, True) for item in members[:_MAX_COLLECTION_ITEMS])
        length = len(value)
        truncated = length > _MAX_COLLECTION_ITEMS
        value = value[:_MAX_COLLECTION_ITEMS]
    elif key_type == "zset":
        value = [{"member": decode_text(member), "score": score}
                 for member, score in client.zrange(raw_key, 0, 199, withscores=True)]
        length = int(client.zcard(raw_key) or 0)
        truncated = length > len(value)
    elif key_type == "stream":
        rows = client.xrange(raw_key, count=200)
        value = [{"id": decode_text(item_id), "fields": {decode_text(k): decode_text(v) for k, v in fields.items()}}
                 for item_id, fields in rows]
        length = int(client.xlen(raw_key) or 0)
        truncated = length > len(value)
    else:
        raise HTTPException(422, f"暂不支持查看 Redis 类型：{key_type}")
    return {"key": key, "type": key_type, "ttl": ttl, "persistent": ttl == -1,
            "length": length, "truncated": truncated, "value": value}


def write_key(client, key, key_type, value, ttl_seconds):
    raw_key = key.encode("utf-8")
    pipe = client.pipeline(transaction=True)
    try:
        if key_type == "string":
            raw = value.encode("utf-8")
            pipe.set(raw_key, raw)
        elif key_type == "hash":
            if not isinstance(value, dict) or not value:
                raise ValueError("hash value 必须是非空对象")
            mapping = {str(k).encode(): str(v).encode() for k, v in value.items()}
            pipe.delete(raw_key).hset(raw_key, mapping=mapping)
        elif key_type == "list":
            if not isinstance(value, list):
                raise ValueError("list value 必须是数组")
            pipe.delete(raw_key)
            if value:
                pipe.rpush(raw_key, *[str(item).encode() for item in value])
        elif key_type == "set":
            if not isinstance(value, list):
                raise ValueError("set value 必须是数组")
            pipe.delete(raw_key)
            if value:
                pipe.sadd(raw_key, *[str(item).encode() for item in value])
        elif key_type == "zset":
            if not isinstance(value, list):
                raise ValueError("zset value 必须是 [{member,score}] 数组")
            mapping = {str(item["member"]).encode(): float(item["score"]) for item in value}
            if not mapping:
                raise ValueError("zset value 不能为空")
            pipe.delete(raw_key).zadd(raw_key, mapping)
        else:
            raise ValueError("支持的类型：string、hash、list、set、zset")
        if int(ttl_seconds) > 0:
            pipe.expire(raw_key, int(ttl_seconds))
        elif int(ttl_seconds) == 0:
            pipe.persist(raw_key)
        else:
            raise ValueError("TTL 必须大于等于 0；0 表示永不过期")
        pipe.execute()
    except (RedisError, ValueError) as exc:
        raise RedisDataError(str(exc)) from None


def build_redis_data_router(require_user_web_session):
    router = APIRouter(prefix="/api/redis", dependencies=[Depends(require_user_web_session)])

    def current_actor(session):
        return session["user"]

    def load_instance(instance_id):
        rows = execute_query("""
            SELECT m.id,m.environment_id,e.name environment_name,m.instance_name,m.base_url,
                   m.username,m.password_ciphertext,m.password_nonce,m.status,m.last_error,m.last_seen_at,
                   c.id config_id,c.deployment_mode,c.database_count,c.tls_enabled,c.verify_tls,
                   c.connect_timeout_ms,c.read_timeout_ms,c.max_value_bytes,c.scan_batch_size,
                   c.bootstrap_endpoints_json,c.topology_json,c.topology_fingerprint,c.topology_checked_at
            FROM middleware_instances m
            JOIN infra_environments e ON e.id=m.environment_id
            JOIN redis_instance_configs c ON c.middleware_instance_id=m.id
            WHERE m.id=%s AND m.middleware_type='redis' AND m.status<>'disabled' AND e.is_active=1
        """,(instance_id,))
        if not rows:
            raise HTTPException(404, "Redis 实例不存在或未启用")
        return rows[0]

    def guard(session, permission):
        mark_permission(session, permission)
        require = permission
        if require not in session.get("permissions", []) and not session.get("user", {}).get("isSuperuser"):
            raise HTTPException(403, "当前账号没有 Redis 数据操作权限")

    @router.get("/instances")
    def instances(response: Response, session=Depends(require_user_web_session)):
        guard(session, "redis:data:read")
        response.headers["Cache-Control"] = "no-store, private"
        rows = execute_query("""
            SELECT m.id,e.name environment_name,m.instance_name,m.base_url,m.status,
                   m.last_error,m.last_seen_at,c.deployment_mode,c.database_count,
                   c.bootstrap_endpoints_json,c.topology_json,c.topology_fingerprint,c.topology_checked_at
            FROM middleware_instances m
            JOIN infra_environments e ON e.id=m.environment_id
            JOIN redis_instance_configs c ON c.middleware_instance_id=m.id
            WHERE m.middleware_type='redis' AND m.status<>'disabled' AND e.is_active=1
            ORDER BY e.name,m.instance_name
        """)
        for row in rows:
            raw = row.get("bootstrap_endpoints_json", "[]")
            row["endpoints"] = json.loads(raw) if isinstance(raw, str) else raw
            raw = row.get("topology_json") or "{}"
            row["topology"] = json.loads(raw) if isinstance(raw, str) else raw
            row["databases"] = ([0] if row["deployment_mode"] == "cluster"
                                else list(range(int(row.get("database_count", 16)))))
        return rows

    @router.post("/instances/{instance_id}/refresh")
    def refresh(instance_id: int, request: Request, session=Depends(require_user_web_session)):
        guard(session, "redis:data:read")
        instance = load_instance(instance_id)
        try:
            topology, mark, nodes, checked = refresh_topology(instance, instance)
        except RedisDataError as exc:
            with transaction() as cursor:
                cursor.execute("UPDATE middleware_instances SET status='unreachable',last_error=%s,last_seen_at=NOW(6) WHERE id=%s",
                               (str(exc), instance_id))
            raise HTTPException(502, str(exc)) from None
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT id FROM redis_instance_configs WHERE middleware_instance_id=%s",(instance_id,))
            config_id = cursor.fetchone()["id"]
            cursor.execute("DELETE FROM redis_instance_nodes WHERE redis_config_id=%s",(config_id,))
            for node in nodes:
                cursor.execute("""INSERT INTO redis_instance_nodes
                    (redis_config_id,node_id,host,port,role,status,is_seed,last_checked_at)
                    VALUES (%s,%s,%s,%s,%s,%s,0,%s)""",
                    (config_id,node["node_id"],node["host"],node["port"],node["role"],node["status"],checked))
            cursor.execute("""UPDATE redis_instance_configs SET topology_json=%s,topology_fingerprint=%s,topology_checked_at=%s
                WHERE id=%s""",(json.dumps(topology,ensure_ascii=False),mark,checked,config_id))
            cursor.execute("UPDATE middleware_instances SET status='active',last_error=NULL,last_seen_at=%s WHERE id=%s",(checked,instance_id))
        record_audit_event(request,session=session,action="redis_instance_refreshed",status_code=200,
            resource_type="redis_instance",resource_id=str(instance_id))
        return {"status":"active","topology":topology,"topology_fingerprint":mark,"checked_at":checked.replace(tzinfo=timezone.utc).isoformat()}

    @router.get("/instances/{instance_id}/keys")
    def list_keys(instance_id:int,response:Response,db_index:int=Query(0,alias="db"),cursor:int=Query(0,ge=0),
                  pattern:str=Query("*",max_length=256),count:int=Query(50,ge=1,le=_MAX_SCAN_PAGE),
                  session=Depends(require_user_web_session)):
        guard(session,"redis:data:read");response.headers["Cache-Control"]="no-store, private"
        instance=load_instance(instance_id); validate_db(instance,db_index)
        if "*" not in pattern and "?" not in pattern and "[" not in pattern: pattern += "*"
        count = min(count, _MAX_SCAN_PAGE, int(instance.get("scan_batch_size", 200)))
        try:
            with connect(instance,instance,db_index) as client:
                next_cursor,items=scan_keys(client,cursor,pattern,count)
        except RedisDataError as exc: raise HTTPException(502,str(exc)) from None
        return {"items":items,"cursor":next_cursor,"completed":next_cursor==0}

    @router.get("/instances/{instance_id}/key")
    def read_key(instance_id:int,response:Response,key:str=Query(min_length=1,max_length=512),db_index:int=Query(0,alias="db"),session=Depends(require_user_web_session)):
        guard(session,"redis:data:read");response.headers["Cache-Control"]="no-store, private"
        instance=load_instance(instance_id);validate_db(instance,db_index)
        try:
            with connect(instance,instance,db_index) as client:return key_detail(client,key,int(instance["max_value_bytes"]))
        except RedisDataError as exc:raise HTTPException(502,str(exc)) from None

    @router.put("/instances/{instance_id}/key")
    def upsert_key(instance_id:int,payload:RedisKeyWrite,request:Request,session=Depends(require_user_web_session)):
        guard(session,"redis:data:write");instance=load_instance(instance_id);db=validate_db(instance,payload.db)
        if not _KEY_RE.fullmatch(payload.key):raise HTTPException(422,"key 只能包含可打印字符、中文，长度 1-512")
        try:
            with connect(instance,instance,db) as client:
                existed=bool(client.exists(payload.key.encode()));write_key(client,payload.key,payload.type,payload.value,payload.ttl_seconds)
        except RedisDataError as exc:raise HTTPException(502,str(exc)) from None
        record_audit_event(request,session=session,action="redis_key_upserted",status_code=200,resource_type="redis_key",
            resource_id=payload.key,details={"instance_id":instance_id,"db":db,"type":payload.type,"created":not existed})
        return {"key":payload.key,"created":not existed}

    @router.delete("/instances/{instance_id}/key")
    def delete_key(instance_id:int,request:Request,key:str=Query(min_length=1,max_length=512),db_index:int=Query(0,alias="db"),session=Depends(require_user_web_session)):
        guard(session,"redis:data:write");instance=load_instance(instance_id);db=validate_db(instance,db_index)
        try:
            with connect(instance,instance,db) as client:affected=int(client.delete(key.encode()))
        except RedisDataError as exc:raise HTTPException(502,str(exc)) from None
        if not affected:raise HTTPException(404,"Redis key 不存在")
        record_audit_event(request,session=session,action="redis_key_deleted",status_code=200,resource_type="redis_key",resource_id=key,details={"instance_id":instance_id,"db":db})
        return {"deleted":True}

    @router.post("/instances/{instance_id}/files")
    async def import_files(instance_id:int,request:Request,files:list[UploadFile]=File(...),db_index:int=Query(0,alias="db"),key_prefix:str=Query("import",max_length=128),overwrite:bool=Query(False),session=Depends(require_user_web_session)):
        guard(session,"redis:data:write");instance=load_instance(instance_id);db=validate_db(instance,db_index)
        if not files:raise HTTPException(422,"请至少选择一个文件")
        if len(files)>_MAX_IMPORT_FILES:raise HTTPException(422,"一次最多上传 3 个文件")
        if not key_prefix or any(char in key_prefix for char in "\x00\r\n "):raise HTTPException(422,"key 前缀不能为空或包含空白字符")
        total=0
        for item in files:
            if item.size and item.size>_MAX_FILE_BYTES:raise HTTPException(422,f"{item.filename} 超过 8MB")
        operation_id=str(uuid.uuid4())
        mark=instance_fingerprint(instance,instance)
        import_root=ROOT_DIR / ".local" / "redis-imports" / operation_id
        connection=None
        try:
            connection=get_connection()
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO redis_import_batches
                    (operation_id,middleware_instance_id,instance_fingerprint,database_index,key_prefix,overwrite,file_count,status,actor_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'running',%s)""",
                    (operation_id,instance_id,mark,db,key_prefix,int(overwrite),len(files),session["user"]["id"]))
                batch_id=cursor.lastrowid
            connection.commit()
        except Exception:
            if connection:connection.rollback()
            if connection:connection.close()
            raise
        import_root.mkdir(parents=True,exist_ok=True)
        results=[]
        try:
            with connect(instance,instance,db) as client:
                for upload in files:
                    safe_name=Path(upload.filename or "file.bin").name
                    stored=import_root/f"{secrets.token_hex(8)}-{safe_name}"
                    size=0;sha=hashlib.sha256()
                    try:
                        with stored.open("wb") as output:
                            while chunk:=await upload.read(256*1024):
                                size+=len(chunk)
                                if size>_MAX_FILE_BYTES:raise ValueError("单文件不能超过 8MB")
                                sha.update(chunk);output.write(chunk)
                        redis_key=f"{key_prefix}:{safe_name}"
                        if not overwrite and client.exists(redis_key.encode()):raise ValueError("目标 key 已存在")
                        client.set(redis_key.encode(),stored.read_bytes())
                        client.hset(f"{redis_key}:__meta__",mapping={b"original_name":safe_name.encode(),b"size":str(size).encode(),b"sha256":sha.hexdigest().encode()})
                        cursor=connection.cursor();cursor.execute("""INSERT INTO redis_import_files
                            (batch_id,original_name,stored_path,redis_key,content_type,size_bytes,sha256,status)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,'written')""",
                            (batch_id,safe_name,str(stored),redis_key,upload.content_type or "",size,sha.hexdigest()))
                        connection.commit();results.append({"filename":safe_name,"redis_key":redis_key,"size":size,"status":"written"})
                    except Exception as exc:
                        error=str(exc).strip() or "导入失败"
                        cursor=connection.cursor();cursor.execute("""INSERT INTO redis_import_files
                            (batch_id,original_name,stored_path,redis_key,content_type,size_bytes,sha256,status,error_message)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,'failed',%s)""",
                            (batch_id,safe_name,str(stored),f"{key_prefix}:{safe_name}",upload.content_type or "",size,sha.hexdigest(),error[:1000]))
                        connection.commit();results.append({"filename":safe_name,"status":"failed","error":error})
                    finally:
                        await upload.close()
                        try:stored.unlink()
                        except FileNotFoundError:pass
            written=sum(item["status"]=="written" for item in results);failed=len(results)-written
            status="partial" if written and failed else "succeeded" if written else "failed"
            with transaction() as db_connection:
                cursor=db_connection.cursor()
                cursor.execute("""UPDATE redis_import_batches SET status=%s,written_files=%s,failed_files=%s,
                    written_keys=%s,failed_keys=%s,finished_at=NOW(6) WHERE id=%s""",(status,written,failed,written,failed,batch_id))
            record_audit_event(request,session=session,action="redis_files_imported",status_code=200,
                resource_type="redis_import",resource_id=str(batch_id),details={"operation_id":operation_id,"results":results})
            return JSONResponse(status_code=200 if status!="failed" else 207,content={"operation_id":operation_id,"batch_id":batch_id,"status":status,"files":results})
        except RedisDataError as exc:
            with transaction() as db_connection:
                cursor=db_connection.cursor()
                cursor.execute("UPDATE redis_import_batches SET status='failed',error_summary=%s,finished_at=NOW(6) WHERE id=%s",(str(exc),batch_id))
            raise HTTPException(502,str(exc)) from None

    return router
