import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pymysql
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database_accounts as management
from app import database_account_actions as actions
from app import database_account_client as remote


@pytest.fixture
def system(monkeypatch):
    db=sqlite3.connect(':memory:',check_same_thread=False);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE database_account_action_operations (
      operation_id TEXT PRIMARY KEY,middleware_instance_id INT,instance_fingerprint TEXT,user_identity TEXT,
      identity_fingerprint TEXT,request_digest TEXT,action TEXT,status TEXT,actor_id INT,lock_key TEXT UNIQUE,
      message TEXT DEFAULT '',updated_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
    state={'user':1,'exists':True,'protected':False,'disabled':False,'revision':'a'*64,'fingerprint':'b'*64,'writes':[],'disconnect':False,'pending_permission':False}
    instance={'id':1,'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root'}
    def execute(sql,params=None):
        if 'FROM rbac_users' in sql:return [{'id':1}] if state['user']==1 else []
        if 'FROM database_permission_operations' in sql:return [{'operation_id':'pending'}] if state['pending_permission'] else []
        rows=[dict(row) for row in db.execute(sql.replace('%s','?'),params or ())]
        for row in rows:
            if 'updated_at' in row:row['updated_at']=datetime.fromisoformat(row['updated_at'])
        return rows
    def write(sql,params):
        try:cursor=db.execute(sql.replace('%s','?'),params);db.commit();return cursor.lastrowid
        except sqlite3.IntegrityError:raise pymysql.IntegrityError(1062,'duplicate')
    monkeypatch.setattr(management,'execute_query',execute);monkeypatch.setattr(actions,'execute_query',execute)
    monkeypatch.setattr(management,'write',write);monkeypatch.setattr(management,'instance_for',lambda _:instance)
    monkeypatch.setattr(actions,'record_audit_event',lambda *args,**kwargs:None)
    monkeypatch.setattr(actions,'_encryption_key',lambda:b'x'*32)
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params=None):
            if 'UPDATE database_managed_accounts' not in sql:self.rows=write(sql,params)
    class Connection:
        def cursor(self):return Cursor()
        def commit(self):db.commit()
        def rollback(self):db.rollback()
        def close(self):pass
    monkeypatch.setattr(actions,'get_connection',Connection)
    @contextmanager
    def connection(*args):yield Connection()
    monkeypatch.setattr(actions,'account_change_lock',connection);monkeypatch.setattr(remote,'connect',connection)
    monkeypatch.setattr(remote,'capabilities',lambda *args:{'can_manage':True})
    def account_state(*args):
        if state['disconnect']:raise OSError('source unreachable')
        return {'user_identity':"'reader'@'%'",'exists':state['exists'],'protected':state['protected'],'revision':state['revision'],
            'identity_fingerprint':state['fingerprint'],'disabled':state['disabled']}
    monkeypatch.setattr(actions,'account_state',account_state)
    def disable(*args):state['writes'].append('disable');state['disabled']=True
    def query(c,sql,params=None):
        assert sql=="DROP USER 'reader'@'%'";state['writes'].append('delete');state['exists']=False
    monkeypatch.setattr(actions,'disable_account',disable);monkeypatch.setattr(remote,'query',query)
    app=FastAPI();app.include_router(management.build_database_account_router(lambda:{'user':{'id':state['user']}}))
    with TestClient(app) as client:yield client,state,db
    db.close()


def body(action='disable'):
    return {'operation_id':str(uuid4()),'action':action,'user_identity':"'reader'@'%'",'confirm_identity':"'reader'@'%'",'revision':'a'*64}


@pytest.mark.parametrize('action',['disable','delete'])
def test_action_requires_confirmation_then_verifies_and_is_idempotent(system,action):
    client,state,_=system;payload=body(action);url='/api/admin/database-accounts/1/accounts/actions'
    assert client.post(url,json={**payload,'confirm_identity':'different'}).status_code==422
    assert client.post(url,json={**payload,'revision':'0'*64}).status_code==409
    assert not state['writes']
    result=client.post(url,json=payload);assert result.status_code==200 and result.json()['confirmed'],result.text
    assert result.headers['cache-control']=='no-store, private'
    assert client.post(url,json=payload).json()['confirmed']
    assert state['writes']==[action]
    assert client.post(url,json={**payload,'action':'delete' if action=='disable' else 'disable'}).status_code==409


def test_root_and_configured_manager_protection_is_enforced_by_backend(system):
    client,state,_=system;state['protected']=True
    assert client.post('/api/admin/database-accounts/1/accounts/actions',json=body()).status_code==403
    assert not state['writes']


@pytest.mark.parametrize('path,method',[
    ('/1/accounts/action-preview?user_identity=reader@%','GET'),('/1/accounts/actions','POST'),
    ('/account-actions/00000000-0000-0000-0000-000000000001','GET'),
    ('/account-actions/00000000-0000-0000-0000-000000000001/verify','POST'),
])
def test_other_superusers_or_users_cannot_access_actions(system,path,method):
    client,state,_=system;state['user']=2
    assert client.request(method,'/api/admin/database-accounts'+path,json=body() if path.endswith('/actions') else None).status_code==403
    assert not state['writes']


def test_lost_delete_response_is_not_reported_success_or_reexecuted(system,monkeypatch):
    client,state,db=system;payload=body('delete')
    def disconnect(*args):state['writes'].append('delete');state['exists']=False;state['disconnect']=True;raise OSError('response lost')
    monkeypatch.setattr(remote,'query',disconnect)
    url='/api/admin/database-accounts/1/accounts/actions';result=client.post(url,json=payload)
    assert result.status_code==202 and not result.json()['confirmed']
    assert client.post(url,json=payload).status_code==202 and len(state['writes'])==1
    state['disconnect']=False
    result=client.post('/api/admin/database-accounts/account-actions/'+payload['operation_id']+'/verify')
    assert result.json()['confirmed'] and len(state['writes'])==1


def test_pending_permission_change_blocks_destructive_action(system):
    client,state,_=system;state['pending_permission']=True
    assert client.post('/api/admin/database-accounts/1/accounts/actions',json=body('delete')).status_code==409
    assert not state['writes']


def test_doris_preview_revision_ignores_query_clock(monkeypatch):
    instance={'middleware_type':'doris','base_url':'mysql://fixture:9030','username':'root'}
    class Connection:
        def escape(self,value):return pymysql.converters.escape_str(value,{})
    monkeypatch.setattr(actions,'_encryption_key',lambda:b'x'*32)
    monkeypatch.setattr(remote,'query',lambda *args:[{'UserIdentity':"'reader'@'%'",'Comment':'fixture','Roles':'','Password':'Yes'}])
    clock={'at':'2026-09-09T00:00:00+00:00'}
    def expiry(c,rows,query):
        rows[0]['password_expiry']={'state':'never','lifetime_seconds':0,'expires_at':None,'checked_at':clock['at'],'password_changed_at':'2026-09-01T00:00:00+00:00'}
    monkeypatch.setattr(actions,'populate_doris_expiries',expiry)
    first=actions.account_state(Connection(),instance,"'reader'@'%'")
    clock['at']='2026-09-09T00:05:00+00:00'
    assert actions.account_state(Connection(),instance,"'reader'@'%'")['revision']==first['revision']
