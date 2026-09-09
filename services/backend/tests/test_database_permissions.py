import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pymysql
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database_accounts as management
from app import database_permissions as permissions
from app import database_permission_routes as routes
from app import database_account_client as remote


def test_scopes_preserve_quoted_dots_and_backticks():
    assert permissions.split_scope('`internal`.`a.b`.`c``d`')==['internal','a.b','c`d']
    assert permissions.split_scope('`a_b`.*')==['a_b',None]
    assert permissions.split_scope('RESOURCE "all"') is None


def test_delta_removes_writes_without_losing_select():
    before=["GRANT SELECT,INSERT,UPDATE,DELETE ON `app`.`one` TO 'u'@'%'"]
    after=["GRANT SELECT ON `app`.`one` TO 'u'@'%'", "GRANT SELECT ON `b`.* TO 'u'@'%'"]
    result=permissions.delta(before,after,'mysql',"'u'@'%'")
    assert result==["REVOKE DELETE,INSERT,UPDATE ON `app`.`one` FROM 'u'@'%'","GRANT SELECT ON `b`.* TO 'u'@'%'"]


def test_merged_grants_compare_by_privilege_not_statement_order():
    first=["GRANT SELECT,INSERT ON `app`.`one` TO 'u'@'%'"]
    second=["GRANT INSERT ON `app`.`one` TO 'u'@'%'","GRANT SELECT ON `app`.`one` TO 'u'@'%'"]
    assert remote.canonical_grants(first)==remote.canonical_grants(second)


@pytest.mark.parametrize('kind,statement',[
    ('mysql',"GRANT ALL PRIVILEGES ON *.* TO 'u'@'%'"),
    ('mysql',"GRANT SELECT ON `app`.* TO 'u'@'%' WITH GRANT OPTION"),
    ('mysql',"GRANT `role`@`%` TO 'u'@'%'"),
    ('doris',"GRANT ADMIN_PRIV ON *.*.* TO 'u'@'%'"),
])
def test_complex_grants_cannot_be_silently_removed(kind,statement):
    _,protected,reasons=permissions.unpack([statement],kind)
    assert protected and reasons
    with pytest.raises(remote.AccountError):permissions.delta([statement],[],kind,"'u'@'%'")


@pytest.fixture
def system(monkeypatch):
    db=sqlite3.connect(':memory:',check_same_thread=False);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE database_permission_operations (
      operation_id TEXT PRIMARY KEY,middleware_instance_id INT,instance_fingerprint TEXT,user_identity TEXT,
      request_digest TEXT,lock_key TEXT UNIQUE,before_plan TEXT,after_plan TEXT,account_marker TEXT,status TEXT,
      message TEXT DEFAULT '',actor_id INT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
    state={'user':1,'grants':["GRANT SELECT ON `a`.`d` TO 'reader'@'%'"],'mutations':[],'fail':False,'disconnect':False}
    instance={'id':1,'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root'}
    def execute(sql,params=None):
        if 'FROM rbac_users' in sql:return [{'id':1}] if state['user']==1 else []
        if 'FROM database_managed_accounts' in sql:return []
        if 'FROM database_account_action_operations' in sql:return []
        rows=[dict(row) for row in db.execute(sql.replace('%s','?'),params or ())]
        for row in rows:
            if 'updated_at' in row:row['updated_at']=datetime.fromisoformat(row['updated_at'])
        return rows
    def write(sql,params):
        try:cursor=db.execute(sql.replace('%s','?'),params);db.commit();return cursor.lastrowid
        except sqlite3.IntegrityError:raise pymysql.IntegrityError(1062,'duplicate')
    monkeypatch.setattr(management,'execute_query',execute);monkeypatch.setattr(routes,'execute_query',execute)
    monkeypatch.setattr(management,'write',write);monkeypatch.setattr(management,'instance_for',lambda _:instance)
    monkeypatch.setattr(routes,'record_audit_event',lambda *args,**kwargs:None)
    monkeypatch.setattr(permissions,'_encryption_key',lambda:b'x'*32)
    class Connection:
        def escape(self,text):return pymysql.converters.escape_str(text,{})
    @contextmanager
    def connect(_):yield Connection()
    monkeypatch.setattr(remote,'connect',connect)
    @contextmanager
    def lock(*args):yield
    monkeypatch.setattr(routes,'account_change_lock',lock)
    monkeypatch.setattr(remote,'capabilities',lambda *args:{'can_manage':True})
    monkeypatch.setattr(remote,'databases',lambda *args:['a','b','c'])
    monkeypatch.setattr(remote,'tables',lambda *args:['d','e','f'])
    monkeypatch.setattr(remote,'clone_plan',lambda *args:state['grants'].copy())
    def query(c,sql,params=None):
        if sql.startswith('SELECT User_attributes'):
            if state['disconnect']:raise OSError('disconnected')
            return [{'User_attributes':'fixture-marker'}]
        if sql.startswith('SELECT @@partial_revokes'):return [{'enabled':0}]
        state['mutations'].append(sql)
        if state['fail'] and sql.startswith('GRANT'):
            state['fail']=False
            raise ValueError('injected failure')
        match=re.fullmatch(r'(GRANT|REVOKE) (.+) ON (.+) (?:TO|FROM) (.+)',sql)
        assert match,sql
        old,_,_=permissions.unpack(state['grants'],'mysql')
        scope=tuple(permissions.split_scope(match[3]));privileges={x.strip() for x in match[2].split(',')}
        if match[1]=='GRANT':old.setdefault(scope,set()).update(privileges)
        else:old[scope]-=privileges
        state['grants']=[f"GRANT {','.join(sorted(privs))} ON {remote.identifier(database)}.{remote.identifier(table) if table else '*'} TO 'reader'@'%'" for (database,table),privs in old.items() if privs]
        return []
    monkeypatch.setattr(remote,'query',query)
    app=FastAPI();app.include_router(management.build_database_account_router(lambda:{'user':{'id':state['user']}}))
    with TestClient(app) as client:yield client,state,db
    db.close()


def current(client):
    result=client.get('/api/admin/database-accounts/1/permissions',params={'user_identity':"'reader'@'%'"})
    assert result.status_code==200,result.text
    return result.json()


def payload(client):
    return {'operation_id':str(uuid4()),'user_identity':"'reader'@'%'",'revision':current(client)['revision'],
        'tables':[{'database':'b','table':None,'access':'read'},{'database':'c','table':'f','access':'write'}]}


def test_live_read_edit_idempotence_and_stale_revision(system):
    client,state,_=system;body=payload(client)
    response=client.put('/api/admin/database-accounts/1/permissions',json=body)
    assert response.status_code==200 and response.json()['updated'],response.text
    assert response.headers['cache-control']=='no-store, private'
    count=len(state['mutations'])
    assert client.put('/api/admin/database-accounts/1/permissions',json=body).json()['updated']
    assert len(state['mutations'])==count
    assert client.put('/api/admin/database-accounts/1/permissions',json={**body,'operation_id':str(uuid4())}).status_code==409
    assert len(state['mutations'])==count
    view=current(client)
    assert len(view['tables'])==2
    response=client.put('/api/admin/database-accounts/1/permissions',json={**body,'operation_id':str(uuid4()),'revision':view['revision'],'tables':[]})
    assert response.json()['updated'] and current(client)['tables']==[]


def test_failed_grant_restores_before_and_never_returns_success(system):
    client,state,_=system;before=state['grants'].copy();body=payload(client);state['fail']=True
    response=client.put('/api/admin/database-accounts/1/permissions',json=body)
    assert response.status_code==202 and response.json()['status']=='restored',response.text
    assert not response.json()['updated']
    assert remote.canonical_grants(state['grants'])==remote.canonical_grants(before)


@pytest.mark.parametrize('method,path',[
    ('GET','/1/permissions?user_identity=reader@%'),
    ('PUT','/1/permissions'),
    ('GET','/permission-operations/00000000-0000-0000-0000-000000000001'),
    ('POST','/permission-operations/00000000-0000-0000-0000-000000000001/verify'),
    ('POST','/permission-operations/00000000-0000-0000-0000-000000000001/restore'),
])
def test_only_actual_admin_can_read_or_modify_permissions(system,method,path):
    client,state,_=system;body=payload(client);state['user']=2
    response=client.request(method,'/api/admin/database-accounts'+path,json=body if method=='PUT' else None)
    assert response.status_code==403
    assert state['mutations']==[]


def test_global_write_cannot_be_presented_as_effective_read_only(system):
    client,state,_=system;state['grants']=["GRANT SELECT,INSERT,UPDATE,DELETE ON *.* TO 'reader'@'%'"]
    assert not current(client)['editable']


def test_disconnected_update_stays_uncertain_and_can_restore_without_repeating(system,monkeypatch):
    client,state,_=system;body=payload(client);before=state['grants'].copy()
    original=remote.query
    def disconnect(c,sql,params=None):
        if sql.startswith('GRANT') and not state['disconnect']:
            state['disconnect']=True
            raise OSError('response lost')
        return original(c,sql,params)
    monkeypatch.setattr(remote,'query',disconnect)
    result=client.put('/api/admin/database-accounts/1/permissions',json=body)
    assert result.status_code==202 and result.json()['status']=='uncertain'
    assert not result.json()['updated']
    count=len(state['mutations'])
    retry=client.put('/api/admin/database-accounts/1/permissions',json=body)
    assert retry.status_code==202 and len(state['mutations'])==count
    state['disconnect']=False;monkeypatch.setattr(remote,'query',original)
    other=payload(client)
    assert client.put('/api/admin/database-accounts/1/permissions',json=other).status_code==409
    op='/api/admin/database-accounts/permission-operations/'+body['operation_id']
    result=client.post(op+'/restore')
    assert result.json()['status']=='restored' and not result.json()['updated']
    assert remote.canonical_grants(state['grants'])==remote.canonical_grants(before)


def test_mixed_scope_validation_escapes_mysql_database_patterns(monkeypatch):
    monkeypatch.setattr(remote,'databases',lambda *args:['a_b','b%db'])
    monkeypatch.setattr(remote,'query',lambda *args:[{'enabled':0}])
    grants=[management.TableGrant(database='a_b',table=None,access='read'),management.TableGrant(database='b%db',table=None,access='write')]
    statements=remote.table_plan(None,'mysql',grants,'read',"'reader'@'%'")
    assert statements[0]=="GRANT SELECT ON `a\\_b`.* TO 'reader'@'%'"
    assert statements[1]=="GRANT SELECT,INSERT,UPDATE,DELETE ON `b\\%db`.* TO 'reader'@'%'"
    with pytest.raises(Exception):management.TableGrant(database='a_b')
