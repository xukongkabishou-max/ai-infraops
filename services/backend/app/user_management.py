from datetime import datetime, timezone
from typing import Literal

import pymysql
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .audit import mark_permission, record_audit_event
from .db import get_connection
from .database_account_client import generate_password
from .middleware_crypto import _encrypt_password, _decrypt_password
from .user_passwords import password_aad


class UserFields(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    username:str=Field(pattern=r'^[A-Za-z][A-Za-z0-9_.-]{1,63}$')
    display_name:str=Field(min_length=1,max_length=128)
    role:Literal['super_admin','rd']='rd'
    is_active:bool=True


class NewUser(UserFields):
    password:SecretStr|None=None
    @model_validator(mode='after')
    def validate_password(self):
        if self.password is not None:
            value=self.password.get_secret_value()
            if len(value)<8 or len(value.encode())>72 or not value.strip():raise ValueError('密码长度不合法')
        return self


class UserRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handler(request):
            try:return await original(request)
            except RequestValidationError:raise HTTPException(422,'请检查账号、名称及角色；自定义密码至少 8 位且不超过 72 个 UTF-8 字节') from None
        return handler


def authorize(cursor,session):
    cursor.execute('SELECT id,username,is_active,is_superuser,auth_version FROM rbac_users WHERE id=%s FOR UPDATE',(session['user']['id'],))
    operator=cursor.fetchone()
    if not operator or operator['username']!='admin' or not operator['is_active'] or not operator['is_superuser']:
        raise HTTPException(403,'仅 admin 超级管理员可以新增或编辑用户')
    if operator['auth_version']!=session.get('_auth_version',0):raise HTTPException(401,'登录已失效，请重新登录')
    return operator


def assign_role(cursor,user_id,role):
    cursor.execute('SELECT id FROM rbac_roles WHERE code=%s AND is_active=1',(role,))
    row=cursor.fetchone()
    if not row:raise HTTPException(409,'所选角色尚未配置或已停用')
    cursor.execute('DELETE FROM rbac_user_roles WHERE user_id=%s',(user_id,))
    cursor.execute('INSERT INTO rbac_user_roles (user_id,role_id) VALUES (%s,%s)',(user_id,row['id']))


def build_user_management_router(require_admin,password_context):
    router=APIRouter(route_class=UserRoute)

    @router.post('/api/rbac/users',status_code=201)
    def create(payload:NewUser,request:Request,response:Response,session=Depends(require_admin)):
        response.headers['Cache-Control']='no-store, private';mark_permission(session,'user:create')
        password=payload.password.get_secret_value() if payload.password is not None else generate_password()
        hashed=password_context.hash(password)
        c=get_connection()
        try:
            with c.cursor() as cursor:
                operator=authorize(cursor,session)
                if payload.username.lower()=='admin':raise HTTPException(409,'内置 admin 账号不可重复创建')
                cursor.execute('SELECT id FROM rbac_users WHERE username=%s',(payload.username,))
                if cursor.fetchone():raise HTTPException(409,'账号已存在，请使用其他名称')
                added_at=datetime.now(timezone.utc).replace(tzinfo=None)
                cursor.execute('''INSERT INTO rbac_users (username,display_name,email,password_hash,is_active,is_superuser,
                    added_at,added_by,added_by_name,password_changed_at)
                    VALUES (%s,%s,'',%s,%s,%s,%s,%s,%s,%s)''',
                    (payload.username,payload.display_name,hashed,payload.is_active,payload.role=='super_admin',added_at,operator['id'],operator['username'],added_at))
                user_id=cursor.lastrowid
                cipher,nonce=_encrypt_password(password,password_aad(user_id))
                cursor.execute('UPDATE rbac_users SET password_ciphertext=%s,password_nonce=%s WHERE id=%s',(cipher,nonce,user_id))
                assign_role(cursor,user_id,payload.role)
                cursor.execute('SELECT password_hash,password_ciphertext,password_nonce FROM rbac_users WHERE id=%s',(user_id,))
                saved=cursor.fetchone()
                if not password_context.verify(password,saved['password_hash']) or _decrypt_password(saved['password_ciphertext'],saved['password_nonce'],password_aad(user_id))!=password:
                    raise HTTPException(503,'密码保存核验失败')
            c.commit()
        except pymysql.IntegrityError:
            c.rollback();raise HTTPException(409,'账号已存在，请刷新后重试') from None
        except Exception:c.rollback();raise
        finally:c.close()
        record_audit_event(request,session=session,action='user_create',status_code=201,resource_type='rbac_user',resource_id=str(user_id),
            details={'username':payload.username,'role':payload.role,'is_active':payload.is_active})
        return {'id':user_id,'username':payload.username,'password':password,'role':payload.role,'added_at':added_at.replace(tzinfo=timezone.utc).isoformat(),'added_by_name':operator['username']}

    @router.put('/api/rbac/users/{user_id}')
    def edit(user_id:int,payload:UserFields,request:Request,response:Response,session=Depends(require_admin)):
        response.headers['Cache-Control']='no-store, private';mark_permission(session,'user:edit')
        c=get_connection()
        try:
            with c.cursor() as cursor:
                authorize(cursor,session)
                cursor.execute('SELECT id,username FROM rbac_users WHERE id=%s FOR UPDATE',(user_id,))
                target=cursor.fetchone()
                if not target:raise HTTPException(404,'用户不存在')
                if target['username']=='admin' and (payload.username!='admin' or payload.role!='super_admin' or not payload.is_active):
                    raise HTTPException(409,'不能重命名、禁用或降低内置 admin 权限')
                if target['username']!='admin' and payload.username.lower()=='admin':raise HTTPException(409,'admin 为保留账号')
                cursor.execute('SELECT id FROM rbac_users WHERE username=%s AND id<>%s',(payload.username,user_id))
                if cursor.fetchone():raise HTTPException(409,'账号名已被使用')
                assign_role(cursor,user_id,payload.role)
                cursor.execute('''UPDATE rbac_users SET username=%s,display_name=%s,is_active=%s,is_superuser=%s,
                    auth_version=auth_version+1 WHERE id=%s''',(payload.username,payload.display_name,payload.is_active,payload.role=='super_admin',user_id))
            c.commit()
        except pymysql.IntegrityError:c.rollback();raise HTTPException(409,'账号名已被使用') from None
        except Exception:c.rollback();raise
        finally:c.close()
        record_audit_event(request,session=session,action='user_edit',status_code=200,resource_type='rbac_user',resource_id=str(user_id),
            details={'username':payload.username,'role':payload.role,'is_active':payload.is_active})
        return {'updated':True,'reauthenticate':user_id==session['user']['id'],'sessions_invalidated':True}

    return router
