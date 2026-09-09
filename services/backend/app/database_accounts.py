import asyncio
import json
import logging
import pymysql
import hashlib
import hmac
from time import monotonic
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from . import database_account_client as remote
from .audit import mark_permission, record_audit_event
from .db import execute_query, execute_queries, get_connection
from .middleware_crypto import _encrypt_password, _decrypt_password, _encryption_key, decrypt_mysql_account_password, decrypt_doris_account_password, decrypt_middleware_password


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def aad(instance_id, user_identity):
    return f'infraops:database-account:v1:{instance_id}:{user_identity}'.encode()


def same_identity(left, right):
    try:
        return remote._parse_user_identity(left) == remote._parse_user_identity(right)
    except RuntimeError:
        return False


def write(sql, params):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.lastrowid
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def instance_for(instance_id):
    rows = execute_query('''SELECT m.*, e.name environment_name FROM middleware_instances m
        JOIN infra_environments e ON e.id=m.environment_id
        WHERE m.id=%s AND m.middleware_type IN ('mysql','doris') AND m.status<>'disabled' AND e.is_active=1''',(instance_id,))
    if not rows:
        raise HTTPException(404, '数据库实例不存在或已停用')
    return rows[0]


class AccountRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, '请检查账号名、密码、表级权限和有效天数；账号名须为字母开头的 2-32 位字母、数字或下划线') from None
            except remote.AccountError as exc:
                raise HTTPException(422, str(exc)) from None
        return handler


class TableGrant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    database: str = Field(min_length=1, max_length=255)
    table: str | None = Field(min_length=1, max_length=255)
    access: Literal['read','write'] | None = None


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID = Field(default_factory=uuid4)
    username: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{1,31}$')
    host: str = Field(default='%', pattern=r'^[A-Za-z0-9.%_:\-]{1,60}$')
    source_identity: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = None
    tables: list[TableGrant] = Field(default_factory=list, max_length=200)
    access: Literal['read','write'] = 'read'
    expires_days: int | None = Field(default=None, ge=1, le=3650, strict=True)

    @model_validator(mode='after')
    def validate_creation(self):
        if bool(self.source_identity) == bool(self.tables):
            raise ValueError('请选择权限克隆或勾选库表')
        if self.username.lower() in {'root','admin','mysql','doris'}:
            raise ValueError('不能创建保留账号')
        if self.password is not None and not 8 <= len(self.password.get_secret_value()) <= 128:
            raise ValueError('自定义密码长度须为 8-128 位')
        return self


class SavePassword(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_identity: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=256)


def load_operation(operation_id):
    rows = execute_query('SELECT * FROM database_managed_accounts WHERE operation_id=%s',(str(operation_id),))
    return rows[0] if rows else None


def operation_result(row):
    result = {'operation_id':row['operation_id'],'status':row['status'],
        'created':row['confirmed_at'] is not None and row['status'] in ('active','expired','expiring'),'user_identity':row['user_identity'],
        'message':row['last_error'] or '',
        'expires_at':row['expires_at'].replace(tzinfo=timezone.utc).isoformat() if row['expires_at'] else None}
    if result['created']:
        result['password'] = _decrypt_password(row['password_ciphertext'],row['password_nonce'],aad(row['middleware_instance_id'],row['user_identity']))
    return result


def verify_operation(row):
    instance = instance_for(row['middleware_instance_id'])
    if row['instance_fingerprint'] != remote.fingerprint(instance):
        raise remote.AccountError('实例地址已改变，不能核验原操作')
    expected = json.loads(row['grant_plan']) if isinstance(row['grant_plan'],str) else row['grant_plan']
    if expected is None:
        raise remote.AccountError('尚未保存完整目标权限，不能确认成功')
    with remote.connect(instance) as source:
        remote.verify_managed_account(source,instance['middleware_type'],row['user_identity'],row['id'])
        remote.verify_grants(source,instance['middleware_type'],row['user_identity'],expected)
    _decrypt_password(row['password_ciphertext'],row['password_nonce'],aad(row['middleware_instance_id'],row['user_identity']))


def rollback_operation(row):
    instance = instance_for(row['middleware_instance_id'])
    if row['instance_fingerprint'] != remote.fingerprint(instance):
        raise remote.AccountError('实例地址已改变，停止自动撤销')
    with remote.connect(instance) as source:
        identities = {item['user_identity'] for item in remote.accounts(source,instance['middleware_type'])}
        if row['user_identity'] in identities:
            remote.verify_managed_account(source,instance['middleware_type'],row['user_identity'],row['id'])
            user,host = remote._parse_user_identity(row['user_identity'])
            remote.query(source,'DROP USER '+remote.identity(source,user,host))
            if row['user_identity'] in {item['user_identity'] for item in remote.accounts(source,instance['middleware_type'])}:
                raise remote.AccountError('撤销后仍检测到账号，需继续核验')
    write("UPDATE database_managed_accounts SET status='failed',confirmed_at=NULL,last_error='创建未完成，已核验新账号不存在' WHERE id=%s",(row['id'],))


def expire_due_accounts():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT * FROM database_managed_accounts
                WHERE status IN ('active','expiring') AND expires_at<=UTC_TIMESTAMP(6)
                AND (expiry_claim_until IS NULL OR expiry_claim_until<UTC_TIMESTAMP(6))
                ORDER BY expires_at LIMIT 4 FOR UPDATE SKIP LOCKED''')
            rows = cursor.fetchall()
            for row in rows:
                cursor.execute("UPDATE database_managed_accounts SET status='expiring',expiry_claim_until=%s WHERE id=%s",
                    (now()+timedelta(minutes=2),row['id']))
        connection.commit()
    finally:
        connection.close()
    for row in rows:
        try:
            instance = instance_for(row['middleware_instance_id'])
            if row['instance_fingerprint'] != remote.fingerprint(instance):
                raise remote.AccountError('实例地址已变更，停止自动到期操作')
            with remote.connect(instance) as source:
                remote.verify_managed_account(source, instance['middleware_type'], row['user_identity'], row['id'])
                remote.expire_account(source, instance['middleware_type'], row['user_identity'])
            write("UPDATE database_managed_accounts SET status='expired',last_error=NULL WHERE id=%s",(row['id'],))
        except Exception:
            write("UPDATE database_managed_accounts SET last_error='到期处理失败，等待重试' WHERE id=%s",(row['id'],))


async def expiry_loop(stop):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(expire_due_accounts)
            except Exception:
                logging.getLogger('infraops.api').warning('数据库账号到期任务暂不可用',extra={'event':'database_account_expiry_failed'})


def build_database_account_router(require_admin):
    router = APIRouter(prefix='/api/admin/database-accounts', route_class=AccountRoute)

    def only_admin(response: Response, session=Depends(require_admin)):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Pragma'] = 'no-cache'
        mark_permission(session, 'admin:database-accounts')
        rows = execute_query("SELECT id FROM rbac_users WHERE id=%s AND BINARY username='admin' AND is_superuser=1 AND is_active=1",
            (session['user']['id'],))
        if not rows:
            raise HTTPException(403, '仅超级管理员 admin 可以管理数据库账号')
        return session

    @router.get('/instances')
    def instances(session=Depends(only_admin)):
        return execute_query('''SELECT m.id,m.middleware_type,m.base_url,m.instance_name,e.name environment_name
            FROM middleware_instances m JOIN infra_environments e ON e.id=m.environment_id
            WHERE m.middleware_type IN ('mysql','doris') AND m.status<>'disabled' AND e.is_active=1
            ORDER BY e.name,m.instance_name''')

    @router.get('/operations/{operation_id}')
    def read_operation(operation_id: UUID, session=Depends(only_admin)):
        row = load_operation(operation_id)
        if not row:
            raise HTTPException(404,'未找到此操作记录')
        return operation_result(row)

    @router.post('/operations/{operation_id}/verify')
    def check_operation(operation_id: UUID, session=Depends(only_admin)):
        row = load_operation(operation_id)
        if not row:
            raise HTTPException(404,'未找到此操作记录')
        if row['status'] in ('active','expired','expiring','failed'):
            return operation_result(row)
        if row['status'] in ('provisioning','verifying') and row['updated_at'] > now()-timedelta(minutes=5):
            return operation_result(row)
        try:
            verify_operation(row)
        except Exception:
            write("UPDATE database_managed_accounts SET status='cleanup_required',last_error='尚未确认目标权限；请检查或撤销本次新账号' WHERE id=%s",(row['id'],))
        else:
            write("UPDATE database_managed_accounts SET status='active',confirmed_at=%s,last_error=NULL WHERE id=%s",(now(),row['id']))
        return operation_result(load_operation(operation_id))

    @router.post('/operations/{operation_id}/rollback')
    def undo_operation(operation_id: UUID, request: Request, session=Depends(only_admin)):
        row = load_operation(operation_id)
        if not row or row['status'] not in ('uncertain','cleanup_required','failed'):
            raise HTTPException(409,'仅允许撤销未确认成功的创建操作')
        rollback_operation(row)
        record_audit_event(request,session=session,action='database_account_rollback',status_code=200,
            resource_type='database_account_operation',resource_id=str(operation_id))
        return operation_result(load_operation(operation_id))

    @router.get('/{instance_id}/accounts')
    def list_accounts(instance_id: int, page: int=Query(1,ge=1), keyword: str=Query('',max_length=100), session=Depends(only_admin)):
        instance = instance_for(instance_id)
        with remote.connect(instance) as source:
            accounts = remote.accounts(source,instance['middleware_type'])
            capability = remote.capabilities(source,instance['middleware_type'])
        kind = instance['middleware_type']
        stored, legacy_rows = execute_queries([
            ('SELECT * FROM database_managed_accounts WHERE instance_fingerprint=%s',(remote.fingerprint(instance),)),
            (f'SELECT * FROM {kind}_account_credentials WHERE middleware_instance_id=%s',(instance_id,)),
        ])
        records = {row['user_identity']:row for row in stored}
        legacy = {row['user_identity']:row for row in legacy_rows}
        accounts = [row for row in accounts if keyword.lower() in (row['username']+'@'+row['host']).lower()]
        page_rows = accounts[(page-1)*20:page*20]
        for account in page_rows:
            record = records.get(account['user_identity'])
            account.update(password=None, password_updated_at=None, expires_at=account.get('native_expires_at'), status='existing')
            if record:
                account.update(status=record['status'],password_updated_at=record['updated_at'],expires_at=record['expires_at'],last_error=record['last_error'])
                if record['instance_fingerprint'] == remote.fingerprint(instance):
                    try: account['password'] = _decrypt_password(record['password_ciphertext'],record['password_nonce'],aad(record['middleware_instance_id'],account['user_identity']))
                    except Exception: account['last_error'] = '历史密码无法解密，待手动添加'
                else:
                    account['last_error'] = '实例已变更，待重新登记密码'
            elif account['user_identity'] in legacy:
                old = legacy[account['user_identity']]
                try:
                    account['password'] = (decrypt_mysql_account_password if kind=='mysql' else decrypt_doris_account_password)(old['password_ciphertext'],old['password_nonce'])
                    account['password_updated_at'] = old['updated_at']
                except Exception: pass
            elif same_identity(account['user_identity'],capability['current_user']):
                account['password'] = decrypt_middleware_password(instance['password_ciphertext'],instance['password_nonce'])
                account['status'] = 'instance_credential'
            for field in ('expires_at','password_updated_at','native_expires_at'):
                if isinstance(account.get(field),datetime): account[field] = account[field].replace(tzinfo=timezone.utc).isoformat()
        return {'items':page_rows,'total':len(accounts),'page':page,'capabilities':capability}

    @router.get('/{instance_id}/databases')
    def list_databases(instance_id: int, session=Depends(only_admin)):
        with remote.connect(instance_for(instance_id)) as source:
            return remote.databases(source)

    @router.get('/{instance_id}/tables')
    def list_tables(instance_id: int, database: str=Query(min_length=1,max_length=255), session=Depends(only_admin)):
        with remote.connect(instance_for(instance_id)) as source:
            return remote.tables(source,database)

    @router.put('/{instance_id}/password-record')
    def save_password(instance_id: int, payload: SavePassword, request: Request, session=Depends(only_admin)):
        instance = instance_for(instance_id)
        with remote.connect(instance) as source:
            accounts = remote.accounts(source,instance['middleware_type'])
            if payload.user_identity not in {row['user_identity'] for row in accounts}:
                raise HTTPException(404,'账号不存在，请刷新')
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT id,middleware_instance_id FROM database_managed_accounts WHERE instance_fingerprint=%s AND user_identity=%s FOR UPDATE',
                    (remote.fingerprint(instance),payload.user_identity))
                prior = cursor.fetchone()
                binding_id = prior['middleware_instance_id'] if prior else instance_id
                cipher,nonce = _encrypt_password(payload.password.get_secret_value(),aad(binding_id,payload.user_identity))
                if prior:
                    cursor.execute('UPDATE database_managed_accounts SET password_ciphertext=%s,password_nonce=%s,updated_by=%s WHERE id=%s',
                        (cipher,nonce,session['user']['id'],prior['id']))
                else:
                    cursor.execute('''INSERT INTO database_managed_accounts (middleware_instance_id,user_identity,instance_fingerprint,
                        password_ciphertext,password_nonce,updated_by) VALUES (%s,%s,%s,%s,%s,%s)''',
                        (instance_id,payload.user_identity,remote.fingerprint(instance),cipher,nonce,session['user']['id']))
                cursor.execute('SELECT password_ciphertext,password_nonce FROM database_managed_accounts WHERE instance_fingerprint=%s AND user_identity=%s',
                    (remote.fingerprint(instance),payload.user_identity))
                saved = cursor.fetchone()
                if _decrypt_password(saved['password_ciphertext'],saved['password_nonce'],aad(binding_id,payload.user_identity)) != payload.password.get_secret_value():
                    raise HTTPException(503,'密码记录保存后核验失败')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        record_audit_event(request,session=session,action='database_password_recorded',status_code=200,
            resource_type='middleware',resource_id=str(instance_id),details={'identity':payload.user_identity})
        return {'saved':True}

    @router.post('/{instance_id}/accounts',status_code=201)
    def create_account(instance_id: int,payload: CreateAccount,request: Request,response: Response,session=Depends(only_admin)):
        body = payload.model_dump(mode='json')
        body['password'] = payload.password.get_secret_value() if payload.password is not None else None
        digest = hmac.new(_encryption_key(),json.dumps([instance_id,body],sort_keys=True).encode(),hashlib.sha256).hexdigest()
        prior = load_operation(payload.operation_id)
        if prior:
            if not hmac.compare_digest(prior['request_digest'],digest):
                raise HTTPException(409,'操作编号已用于不同请求，不能重复执行')
            response.status_code = 200 if prior['confirmed_at'] else 202
            return operation_result(prior)
        instance = instance_for(instance_id)
        password = payload.password.get_secret_value() if payload.password is not None else remote.generate_password()
        kind = instance['middleware_type']
        with remote.connect(instance) as source:
            if not remote.capabilities(source,kind)['can_manage']:
                raise HTTPException(403,'当前数据库管理账号缺少全局授权能力，请更新实例管理凭证；未创建或修改任何账号')
            current = remote.accounts(source,kind)
            if any(row['username'].lower() == payload.username.lower() for row in current):
                raise HTTPException(409,'同名账号已存在，不能覆盖或克隆到已有账号')
            destination = remote.identity(source,payload.username,payload.host)
            plans = remote.clone_plan(source,kind,payload.source_identity,destination) if payload.source_identity else remote.table_plan(source,kind,payload.tables,payload.access,destination)
            cipher,nonce = _encrypt_password(password,aad(instance_id,destination))
            existing = execute_query('SELECT id FROM database_managed_accounts WHERE instance_fingerprint=%s AND user_identity=%s',(remote.fingerprint(instance),destination))
            if existing:
                raise HTTPException(409,'此账号已有管理记录，请使用新名称，避免覆盖历史记录')
            expires_at = now()+timedelta(days=payload.expires_days) if payload.expires_days else None
            try:
                record_id = write('''INSERT INTO database_managed_accounts (middleware_instance_id,user_identity,instance_fingerprint,
                    password_ciphertext,password_nonce,source_identity,status,expires_at,updated_by,operation_id,request_digest)
                    VALUES (%s,%s,%s,%s,%s,%s,'provisioning',%s,%s,%s,%s)''',
                    (instance_id,destination,remote.fingerprint(instance),cipher,nonce,payload.source_identity,expires_at,session['user']['id'],str(payload.operation_id),digest))
            except pymysql.IntegrityError:
                prior = load_operation(payload.operation_id)
                if prior and hmac.compare_digest(prior['request_digest'],digest):
                    response.status_code = 202
                    return operation_result(prior)
                raise HTTPException(409,'同名账号正在由另一个请求处理，未重复创建') from None
            try:
                policy = ('PASSWORD EXPIRE' if kind=='mysql' else 'PASSWORD_EXPIRE') + (f' INTERVAL {payload.expires_days} DAY' if payload.expires_days else ' NEVER')
                remote.query(source,f'CREATE USER {destination} IDENTIFIED BY {source.escape(password)} {policy} COMMENT '
                    + source.escape(f'infraops-managed:{record_id}'))
                baseline = remote.clone_plan(source,kind,destination,destination)
                expected = plans+baseline
                write('UPDATE database_managed_accounts SET grant_plan=%s WHERE id=%s',(json.dumps(expected),record_id))
                deadline = monotonic()+120
                for statement in plans:
                    if monotonic()>deadline:
                        raise remote.AccountError('授权操作超时')
                    remote.query(source,statement)
                write("UPDATE database_managed_accounts SET status='verifying' WHERE id=%s",(record_id,))
                remote.verify_managed_account(source,kind,destination,record_id)
                remote.verify_grants(source,kind,destination,expected)
                stored = load_operation(payload.operation_id)
                if _decrypt_password(stored['password_ciphertext'],stored['password_nonce'],aad(instance_id,destination)) != password:
                    raise remote.AccountError('密码保存回查不一致')
                write("UPDATE database_managed_accounts SET status='active',confirmed_at=%s,last_error=NULL WHERE id=%s",(now(),record_id))
            except Exception as exc:
                message = '创建结果待核验，可按操作编号查询，请勿换新编号重复创建'
                try:
                    latest = load_operation(payload.operation_id)
                    if latest and latest['status']=='active' and latest['confirmed_at']:
                        return operation_result(latest)
                    rollback_operation(latest)
                    message = '创建未完成，已核验新账号不存在'
                except Exception:
                    try:write("UPDATE database_managed_accounts SET status='uncertain',last_error=%s WHERE id=%s",(message,record_id))
                    except Exception:pass
                if isinstance(exc,pymysql.Error) and exc.args and exc.args[0] in (1142,1227):
                    message = '管理账号缺少目标权限的授权能力；'+message
                raise HTTPException(502,{'message':message,'operation_id':str(payload.operation_id)}) from None
        record_audit_event(request,session=session,action='database_account_created',status_code=201,
            resource_type='middleware',resource_id=str(instance_id),details={'identity':destination,'source_identity':payload.source_identity,'access':payload.access,'tables':[item.model_dump() for item in payload.tables],'expires_days':payload.expires_days})
        return operation_result(load_operation(payload.operation_id))

    from .database_permission_routes import install_permission_routes
    install_permission_routes(router,only_admin)
    return router
