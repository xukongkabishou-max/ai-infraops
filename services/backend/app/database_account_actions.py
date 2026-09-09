"""Confirmed, version-bound account disable/delete operations for the backend admin."""
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import pymysql
from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import database_account_client as remote
from .audit import record_audit_event
from .database_account_expiry import populate_doris_expiries
from .db import get_connection, execute_query
from .middleware_crypto import _encryption_key


def signed(value):
    return hmac.new(_encryption_key(),json.dumps(value,sort_keys=True,default=str).encode(),hashlib.sha256).hexdigest()


@contextmanager
def account_change_lock(instance,user_identity):
    try:user,host=remote._parse_user_identity(user_identity)
    except RuntimeError:raise remote.AccountError('账号标识格式无效') from None
    key=hashlib.sha256(json.dumps([remote.fingerprint(instance),user,host]).encode()).hexdigest()
    connection=get_connection();locked=False
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT GET_LOCK(%s,0) AS acquired',(key,))
            locked=cursor.fetchone()['acquired']==1
        if not locked:raise HTTPException(409,'此账号正在进行其他管理操作，请稍后刷新')
        yield
    finally:
        try:
            if locked:
                with connection.cursor() as cursor:cursor.execute('SELECT RELEASE_LOCK(%s)',(key,))
        finally:connection.close()


def account_state(connection,instance,user_identity):
    try:user,host=remote._parse_user_identity(user_identity)
    except RuntimeError:raise remote.AccountError('账号标识格式无效') from None
    destination=remote.identity(connection,user,host)
    protected=user.lower() in ('root','admin','mysql.sys','mysql.session','mysql.infoschema') or user.lower()==instance['username'].lower()
    if instance['middleware_type']=='mysql':
        rows=remote.query(connection,'''SELECT User,Host,plugin,account_locked,User_attributes,
            SHA2(authentication_string,256) AS credential_checksum,
            UNIX_TIMESTAMP(password_last_changed) AS password_changed_epoch,
            password_lifetime,password_expired FROM mysql.user WHERE User=%s AND Host=%s''',(user,host))
        if not rows:return {'exists':False,'user_identity':destination,'protected':protected}
        row=rows[0];grants=remote.query(connection,'SHOW GRANTS FOR '+destination)
        identity_fields={key:row[key] for key in ('User','Host','plugin','User_attributes','credential_checksum')}
        identity_hash=signed([remote.fingerprint(instance),identity_fields,grants])
        revision=signed([identity_hash,row])
        disabled=row['account_locked']=='Y'
    else:
        rows=remote.query(connection,'SHOW ALL GRANTS')
        row=next((item for item in rows if item.get('UserIdentity')==destination),None)
        if row is None:return {'exists':False,'user_identity':destination,'protected':protected}
        safe_row={key:value for key,value in row.items() if key!='Password'}
        policy=[{'user_identity':destination}]
        populate_doris_expiries(connection,policy,remote.query)
        expiry=policy[0]['password_expiry']
        identity_hash=signed([remote.fingerprint(instance),safe_row])
        revision=signed([identity_hash,{key:value for key,value in expiry.items() if key!='checked_at'}])
        # SHOW PROC exposes seconds, while Doris enforces the policy with a millisecond start.
        disabled=bool(expiry['state']=='expired' and expiry['lifetime_seconds']==1 and expiry['checked_at']
            and datetime.fromisoformat(expiry['checked_at'])>=datetime.fromisoformat(expiry['expires_at'])+timedelta(seconds=1))
    return {'exists':True,'user_identity':destination,'protected':protected,
        'identity_fingerprint':identity_hash,'revision':revision,'disabled':disabled}


def disable_account(connection,kind,destination):
    if kind=='mysql':remote.query(connection,'ALTER USER '+destination+' ACCOUNT LOCK')
    else:remote.query(connection,'ALTER USER '+destination+' PASSWORD_EXPIRE INTERVAL 1 SECOND')


def install_action_routes(router,only_admin):
    from .database_accounts import instance_for,now,write

    class ActionRequest(BaseModel):
        model_config=ConfigDict(extra='forbid')
        operation_id:UUID=Field(default_factory=uuid4)
        action:Literal['disable','delete']
        user_identity:str=Field(min_length=1,max_length=255)
        confirm_identity:str=Field(min_length=1,max_length=255)
        revision:str=Field(pattern=r'^[0-9a-f]{64}$')
        @model_validator(mode='after')
        def confirmed(self):
            if self.confirm_identity!=self.user_identity:raise ValueError('确认账号与目标不一致')
            return self

    def load(operation_id):
        rows=execute_query('SELECT * FROM database_account_action_operations WHERE operation_id=%s',(str(operation_id),))
        return rows[0] if rows else None

    def result(row):
        return {'operation_id':row['operation_id'],'action':row['action'],'user_identity':row['user_identity'],
            'status':row['status'],'confirmed':row['status']=='succeeded','message':row['message']}

    def finish(row):
        action=row['action'];message='已回查确认账号已删除' if action=='delete' else '已回查确认账号已禁用，新的登录将被拒绝'
        # Record both the completed operation and managed-account state in one local transaction.
        c=get_connection()
        try:
            with c.cursor() as cursor:
                cursor.execute("UPDATE database_account_action_operations SET status='succeeded',message=%s,lock_key=NULL WHERE operation_id=%s",(message,row['operation_id']))
                cursor.execute('UPDATE database_managed_accounts SET status=%s,last_error=NULL WHERE instance_fingerprint=%s AND user_identity=%s',
                    ('deleted' if action=='delete' else 'disabled',row['instance_fingerprint'],row['user_identity']))
            c.commit()
        except Exception:c.rollback();raise
        finally:c.close()

    def outcome(source,instance,row):
        current=account_state(source,instance,row['user_identity'])
        if row['action']=='delete' and not current['exists']:return True
        if not current['exists'] or current['identity_fingerprint']!=row['identity_fingerprint']:
            raise HTTPException(409,'账号不存在或身份已变化，不能把当前状态认作原操作结果')
        return current['disabled'] if row['action']=='disable' else False

    @router.get('/{instance_id}/accounts/action-preview')
    def preview(instance_id:int,user_identity:str=Query(min_length=1,max_length=255),session=Depends(only_admin)):
        instance=instance_for(instance_id)
        with remote.connect(instance) as source:
            state=account_state(source,instance,user_identity)
        if not state['exists']:raise HTTPException(404,'目标账号已不存在，请刷新列表')
        state.pop('identity_fingerprint',None)
        state['disable_method']='MySQL 原生账号锁' if instance['middleware_type']=='mysql' else 'Doris 2.1 原生密码立即过期'
        return state

    @router.get('/account-actions/{operation_id}')
    def status(operation_id:UUID,session=Depends(only_admin)):
        row=load(operation_id)
        if not row:raise HTTPException(404,'账号操作记录不存在')
        return result(row)

    @router.post('/account-actions/{operation_id}/verify')
    def verify(operation_id:UUID,request:Request,session=Depends(only_admin)):
        row=load(operation_id)
        if not row:raise HTTPException(404,'账号操作记录不存在')
        if row['status'] in ('succeeded','not_applied','conflict'):return result(row)
        if row['status']=='applying' and row['updated_at']>now()-timedelta(seconds=30):return result(row)
        instance=instance_for(row['middleware_instance_id'])
        if remote.fingerprint(instance)!=row['instance_fingerprint']:raise HTTPException(409,'实例地址已变化，不能核验原操作')
        with account_change_lock(instance,row['user_identity']), remote.connect(instance) as source:
            if outcome(source,instance,row):finish(row)
            else:write("UPDATE database_account_action_operations SET status='not_applied',message='回查确认操作未生效，可刷新后重新提交',lock_key=NULL WHERE operation_id=%s",(str(operation_id),))
        record_audit_event(request,session=session,action='database_account_action_verify',status_code=200,resource_type='database_account_action',resource_id=str(operation_id))
        return result(load(operation_id))

    @router.post('/{instance_id}/accounts/actions')
    def perform(instance_id:int,payload:ActionRequest,request:Request,response:Response,session=Depends(only_admin)):
        op=str(payload.operation_id);digest=signed([instance_id,payload.model_dump(mode='json')]);prior=load(op)
        if prior:
            if prior['request_digest']!=digest:raise HTTPException(409,'操作编号已用于不同请求')
            response.status_code=200 if prior['status']=='succeeded' else 202
            return result(prior)
        instance=instance_for(instance_id)
        with account_change_lock(instance,payload.user_identity),remote.connect(instance) as source:
            if not remote.capabilities(source,instance['middleware_type'])['can_manage']:raise HTTPException(403,'当前管理凭证缺少账号管理权限')
            state=account_state(source,instance,payload.user_identity)
            if state['protected']:raise HTTPException(403,'不能禁用或删除内置管理账号及当前实例使用的管理账号')
            if not state['exists']:raise HTTPException(404,'账号已不存在，请刷新')
            if state['revision']!=payload.revision:raise HTTPException(409,'账号状态或权限已变化，请重新打开确认弹窗')
            busy=execute_query("SELECT operation_id FROM database_permission_operations WHERE instance_fingerprint=%s AND user_identity=%s AND lock_key IS NOT NULL",
                (remote.fingerprint(instance),state['user_identity']))
            if busy:raise HTTPException(409,'该账号有待核验的权限修改，请先完成该操作')
            try:
                write('''INSERT INTO database_account_action_operations (operation_id,middleware_instance_id,instance_fingerprint,
                    user_identity,identity_fingerprint,request_digest,action,status,actor_id,lock_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'applying',%s,%s)''',
                    (op,instance_id,remote.fingerprint(instance),state['user_identity'],state['identity_fingerprint'],digest,payload.action,session['user']['id'],signed([instance_id,state['user_identity']])))
            except pymysql.IntegrityError:
                previous=load(op)
                if previous and previous['request_digest']==digest:response.status_code=202;return result(previous)
                raise HTTPException(409,'账号已有待核验操作，请先查询原操作结果') from None
            try:
                if payload.action=='delete':remote.query(source,'DROP USER '+state['user_identity'])
                elif not state['disabled']:disable_account(source,instance['middleware_type'],state['user_identity'])
                deadline=time.monotonic()+4
                row=load(op)
                while not outcome(source,instance,row):
                    if time.monotonic()>=deadline:raise remote.AccountError('账号状态暂未达到预期')
                    time.sleep(0.25)
                finish(row)
            except Exception:
                previous=load(op)
                if not previous or previous['status']!='succeeded':
                    write("UPDATE database_account_action_operations SET status='uncertain',message='操作结果待核验，未报告成功；请查询结果，勿重复执行' WHERE operation_id=%s",(op,))
                    response.status_code=202
            completed=load(op)
            record_audit_event(request,session=session,action='database_account_'+payload.action,status_code=200 if completed['status']=='succeeded' else 202,
                resource_type='database_account_action',resource_id=op,details={'instance_id':instance_id,'identity':state['user_identity'],'status':completed['status']})
            return result(completed)
