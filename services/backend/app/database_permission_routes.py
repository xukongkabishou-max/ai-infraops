import hashlib
import hmac
import json
from datetime import timedelta
from time import monotonic
from uuid import UUID, uuid4

import pymysql
from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import database_account_client as remote
from . import database_permissions as permissions
from .audit import record_audit_event
from .db import execute_query
from .database_account_actions import account_change_lock


def install_permission_routes(router, only_admin):
    from .database_accounts import TableGrant, instance_for, now, write

    class UpdatePermissions(BaseModel):
        model_config=ConfigDict(extra='forbid')
        operation_id: UUID=Field(default_factory=uuid4)
        user_identity: str=Field(min_length=1,max_length=255)
        revision: str=Field(pattern=r'^[0-9a-f]{64}$')
        tables: list[TableGrant]=Field(max_length=200)

    def load(operation_id):
        rows=execute_query('SELECT * FROM database_permission_operations WHERE operation_id=%s',(str(operation_id),))
        return rows[0] if rows else None

    def result(row):
        return {'operation_id':row['operation_id'],'status':row['status'],'updated':row['status']=='applied',
            'user_identity':row['user_identity'],'message':row['message']}

    def finish(operation_id,status,message=''):
        write('UPDATE database_permission_operations SET status=%s,message=%s,lock_key=NULL WHERE operation_id=%s',
            (status,message,str(operation_id)))

    def decoded(row,key):
        value=row[key]
        return json.loads(value) if isinstance(value,str) else value

    def check_incarnation(instance,state,row):
        if remote.fingerprint(instance)!=row['instance_fingerprint'] or state['marker']!=decoded(row,'account_marker'):
            raise remote.AccountError('实例或账号身份已变化，停止自动恢复')

    def restore(source,instance,row):
        current=permissions.snapshot(source,instance,row['user_identity'])
        check_incarnation(instance,current,row)
        before=decoded(row,'before_plan');after=decoded(row,'after_plan')
        allowed=remote.canonical_grants(before)|remote.canonical_grants(after)
        if not remote.canonical_grants(current['plans']) <= allowed:
            raise remote.AccountError('检测到其他权限修改，停止自动覆盖')
        for statement in permissions.delta(current['plans'],before,instance['middleware_type'],row['user_identity']):
            remote.query(source,statement)
        restored=permissions.snapshot(source,instance,row['user_identity'])
        check_incarnation(instance,restored,row)
        remote.verify_grants(source,instance['middleware_type'],row['user_identity'],before)

    @router.get('/{instance_id}/permissions')
    def read_permissions(instance_id:int,user_identity:str=Query(min_length=1,max_length=255),session=Depends(only_admin)):
        instance=instance_for(instance_id)
        with remote.connect(instance) as source:
            return permissions.public(permissions.snapshot(source,instance,user_identity))

    @router.get('/permission-operations/{operation_id}')
    def get_operation(operation_id:UUID,session=Depends(only_admin)):
        row=load(operation_id)
        if not row:raise HTTPException(404,'权限操作记录不存在')
        return result(row)

    def reconcile(operation_id,restore_before,request,session):
        row=load(operation_id)
        if not row:raise HTTPException(404,'权限操作记录不存在')
        if row['status'] in ('applied','restored','conflict'):return result(row)
        if row['status']=='applying' and row['updated_at']>now()-timedelta(minutes=5):return result(row)
        instance=instance_for(row['middleware_instance_id'])
        with account_change_lock(instance,row['user_identity']),remote.connect(instance) as source:
            current=permissions.snapshot(source,instance,row['user_identity'])
            check_incarnation(instance,current,row)
            if remote.canonical_grants(current['plans'])==remote.canonical_grants(decoded(row,'after_plan')) and not restore_before:
                finish(operation_id,'applied','已回查确认权限修改成功')
            elif remote.canonical_grants(current['plans'])==remote.canonical_grants(decoded(row,'before_plan')):
                finish(operation_id,'restored','当前权限与修改前一致')
            elif restore_before:
                restore(source,instance,row)
                finish(operation_id,'restored','已回查确认恢复修改前权限')
            else:
                write("UPDATE database_permission_operations SET status='uncertain',message='当前权限处于部分修改状态，可恢复修改前权限' WHERE operation_id=%s",(str(operation_id),))
        record_audit_event(request,session=session,action='database_permissions_restore' if restore_before else 'database_permissions_verify',
            status_code=200,resource_type='database_permission_operation',resource_id=str(operation_id))
        return result(load(operation_id))

    @router.post('/permission-operations/{operation_id}/verify')
    def verify(operation_id:UUID,request:Request,session=Depends(only_admin)):
        return reconcile(operation_id,False,request,session)

    @router.post('/permission-operations/{operation_id}/restore')
    def restore_before(operation_id:UUID,request:Request,session=Depends(only_admin)):
        return reconcile(operation_id,True,request,session)

    @router.put('/{instance_id}/permissions')
    def update_permissions(instance_id:int,payload:UpdatePermissions,request:Request,response:Response,session=Depends(only_admin)):
        op=str(payload.operation_id)
        digest=hashlib.sha256(json.dumps([instance_id,payload.model_dump(mode='json')],sort_keys=True).encode()).hexdigest()
        prior=load(op)
        if prior:
            if not hmac.compare_digest(prior['request_digest'],digest):raise HTTPException(409,'操作编号已用于不同请求')
            response.status_code=200 if prior['status'] in ('applied','restored','conflict') else 202
            return result(prior)
        instance=instance_for(instance_id);kind=instance['middleware_type']
        with account_change_lock(instance,payload.user_identity),remote.connect(instance) as source:
            if not remote.capabilities(source,kind)['can_manage']:raise HTTPException(403,'实例管理账号缺少授权能力')
            pending_actions=execute_query("SELECT operation_id FROM database_account_action_operations WHERE instance_fingerprint=%s AND user_identity=%s AND lock_key IS NOT NULL",
                (remote.fingerprint(instance),payload.user_identity))
            if pending_actions:raise HTTPException(409,'该账号有待核验的禁用或删除操作，请先查询原操作')
            state=permissions.snapshot(source,instance,payload.user_identity)
            if not state['editable']:raise HTTPException(422,state['message'])
            if not hmac.compare_digest(state['revision'],payload.revision):raise HTTPException(409,'当前权限已变更，请刷新后重新编辑')
            desired=remote.table_plan(source,kind,payload.tables,'read',state['user_identity'])
            _,protected,_=permissions.unpack(state['plans'],kind)
            after=protected+desired
            commands=permissions.delta(state['plans'],after,kind,state['user_identity'])
            lock_key=hashlib.sha256((remote.fingerprint(instance)+'\0'+state['user_identity']).encode()).hexdigest()
            try:
                write('''INSERT INTO database_permission_operations (operation_id,middleware_instance_id,instance_fingerprint,user_identity,
                    request_digest,lock_key,before_plan,after_plan,account_marker,status,actor_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'applying',%s)''',
                    (op,instance_id,remote.fingerprint(instance),state['user_identity'],digest,lock_key,json.dumps(state['plans']),json.dumps(after),json.dumps(state['marker']),session['user']['id']))
            except pymysql.IntegrityError:
                previous=load(op)
                if previous and previous['request_digest']==digest:
                    response.status_code=202;return result(previous)
                raise HTTPException(409,'此账号已有进行中或待核验的权限操作，请先处理原操作') from None
            started=False
            try:
                fresh=permissions.snapshot(source,instance,state['user_identity'])
                if fresh['revision']!=state['revision']:
                    finish(op,'conflict','执行前权限已变更，未修改数据库')
                    return result(load(op))
                deadline=monotonic()+120
                for statement in commands:
                    if monotonic()>deadline:raise remote.AccountError('权限修改超时')
                    started=True
                    remote.query(source,statement)
                final=permissions.snapshot(source,instance,state['user_identity'])
                check_incarnation(instance,final,load(op))
                remote.verify_grants(source,kind,state['user_identity'],after)
                finish(op,'applied','已回查确认权限修改成功')
            except Exception:
                previous=load(op)
                if previous and previous['status']=='applied':return result(previous)
                try:
                    if started:restore(source,instance,previous)
                    finish(op,'restored','修改未完成，已确认恢复修改前权限')
                except Exception:
                    write("UPDATE database_permission_operations SET status='uncertain',message='权限修改结果待核验，未报告成功' WHERE operation_id=%s",(op,))
                response.status_code=202
            record_audit_event(request,session=session,action='database_permissions_update',status_code=response.status_code or 200,
                resource_type='database_permission_operation',resource_id=op,
                details={'instance_id':instance_id,'identity':state['user_identity'],'before':state['tables'],'requested':[item.model_dump() for item in payload.tables],'status':load(op)['status']})
            return result(load(op))
