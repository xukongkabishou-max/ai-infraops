from contextlib import contextmanager
import json
import re

import pymysql
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database_accounts as management
from app import database_account_client as remote


def test_generated_passwords_have_all_four_classes():
    values={remote.generate_password() for _ in range(100)}
    assert len(values)==100
    for password in values:
        assert len(password)==8
        assert all(re.search(pattern,password) for pattern in (r'[A-Z]',r'[a-z]',r'[0-9]',r'[^A-Za-z0-9]'))


def test_doris_clone_covers_roles_and_scopes_without_expanding_tables():
    quote=lambda text:pymysql.converters.escape_str(text,{})
    result=remote.doris_grants({'Roles':'reader','DatabasePrivs':'internal.app: Select_priv',
        'TablePrivs':'internal.limited.one: Load_priv','WorkloadGroupPrivs':'normal: Usage_priv'},"'copy'@'%'",quote)
    assert result==["GRANT SELECT_PRIV ON `internal`.`app`.* TO 'copy'@'%'",
        "GRANT LOAD_PRIV ON `internal`.`limited`.`one` TO 'copy'@'%'",
        "GRANT USAGE_PRIV ON WORKLOAD GROUP 'normal' TO 'copy'@'%'","GRANT 'reader' TO 'copy'@'%'"]
    with pytest.raises(remote.AccountError):remote.doris_grants({'ColPrivs':'unknown'},"'copy'@'%'",quote)
    with pytest.raises(remote.AccountError):remote.doris_grants({'TablePrivs':'ambiguous.name.with.dots: Select_priv'},"'copy'@'%'",quote)


def test_mysql_clone_rewrites_only_grantee_and_copies_default_roles(monkeypatch):
    class Connection:
        def escape(self,value):return pymysql.converters.escape_str(value,{})
    grants=[{'g':"GRANT SELECT ON `app`.`TO old` TO `old`@`%` WITH GRANT OPTION"},
        {'g':"GRANT `reader`@`%` TO `old`@`%`"},
        {'g':"REVOKE SELECT ON `excluded`.* FROM `old`@`%`"}]
    monkeypatch.setattr(remote,'query',lambda c,sql,params=None: grants if sql.startswith('SHOW') else [{'DEFAULT_ROLE_USER':'reader','DEFAULT_ROLE_HOST':'%'}])
    result=remote.clone_plan(Connection(),'mysql',"'old'@'%'","'new'@'%'")
    assert result[0]=="GRANT SELECT ON `app`.`TO old` TO 'new'@'%' WITH GRANT OPTION"
    assert result[-1]=="SET DEFAULT ROLE 'reader'@'%' TO 'new'@'%'"
    assert result[2]=="REVOKE SELECT ON `excluded`.* FROM 'new'@'%'"


@pytest.fixture
def api(monkeypatch):
    state={'user':1,'remote':[],'records':[],'existing':[],'fail_grant':False,'row':None}
    instance={'id':1,'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root'}
    def execute(sql,params=None):
        if 'FROM rbac_users' in sql:return [{'id':1}] if state['user']==1 else []
        if 'FROM database_managed_accounts' in sql:
            row=state['row']
            if row and 'WHERE operation_id=' in sql and params[0]==row['operation_id']:return [row.copy()]
            return []
        return []
    monkeypatch.setattr(management,'execute_query',execute)
    monkeypatch.setattr(management,'execute_queries',lambda statements:[execute(sql,params) for sql,params in statements])
    monkeypatch.setattr(management,'instance_for',lambda _:instance)
    def write(sql,params):
        state['records'].append((sql,params))
        if 'INSERT INTO' in sql:
            state['row']=dict(id=1,middleware_instance_id=params[0],user_identity=params[1],instance_fingerprint=params[2],
                password_ciphertext=params[3],password_nonce=params[4],expires_at=params[6],operation_id=params[8],request_digest=params[9],
                status='provisioning',confirmed_at=None,last_error=None,updated_at=management.now(),grant_plan=None)
        elif "status='active'" in sql:state['row'].update(status='active',confirmed_at=params[0])
        elif "status='failed'" in sql:state['row'].update(status='failed',confirmed_at=None)
        elif "status='uncertain'" in sql:state['row'].update(status='uncertain',last_error=params[0])
        elif "status='verifying'" in sql:state['row']['status']='verifying'
        elif 'SET grant_plan=' in sql:state['row']['grant_plan']=params[0]
        return 1
    monkeypatch.setattr(management,'write',write)
    monkeypatch.setattr(management,'record_audit_event',lambda *args,**kwargs:None)
    from app import middleware_crypto
    monkeypatch.setattr(middleware_crypto,'_encryption_key',lambda:b'x'*32)
    class Source:
        def escape(self,text):return pymysql.converters.escape_str(text,{})
    @contextmanager
    def connect(_):
        state['remote'].append('connect')
        yield Source()
    monkeypatch.setattr(remote,'connect',connect)
    monkeypatch.setattr(remote,'accounts',lambda *args:state['existing'])
    monkeypatch.setattr(remote,'capabilities',lambda *args:{'can_manage':True})
    monkeypatch.setattr(remote,'tables',lambda *args:['allowed'])
    monkeypatch.setattr(remote,'clone_plan',lambda *args:[])
    monkeypatch.setattr(remote,'verify_managed_account',lambda *args:None)
    monkeypatch.setattr(remote,'verify_grants',lambda *args:None)
    def query(c,sql,params=None):
        state['remote'].append(sql)
        if sql.startswith('CREATE USER'):
            state['existing']=[{'username':'new_user','user_identity':"'new_user'@'%'"}]
        elif sql.startswith('DROP USER'):state['existing']=[]
        if state['fail_grant'] and sql.startswith('GRANT'):raise RuntimeError('secret-bearing remote error')
        return []
    monkeypatch.setattr(remote,'query',query)
    app=FastAPI()
    app.include_router(management.build_database_account_router(lambda:{'user':{'id':state['user'],'username':'admin','isSuperuser':True}}))
    with TestClient(app) as client:yield client,state


@pytest.mark.parametrize('method,path,body',[
    ('GET','/instances',None),('GET','/1/accounts',None),('GET','/1/databases',None),('GET','/1/tables?database=app',None),
    ('POST','/1/accounts',{'username':'new_user','tables':[{'database':'app','table':'allowed'}]}),
    ('PUT','/1/password-record',{'user_identity':"'old'@'%'",'password':'known'}),
])
def test_non_admin_cannot_use_any_new_route_even_with_superuser_session(api,method,path,body):
    client,state=api;state['user']=2
    result=client.request(method,'/api/admin/database-accounts'+path,json=body)
    assert result.status_code==403
    assert not state['remote'] and not state['records']


def test_create_escapes_percent_host_and_password_and_saves_only_ciphertext(api):
    client,state=api
    password="X1'a%;$z"
    result=client.post('/api/admin/database-accounts/1/accounts',json={'username':'new_user','password':password,'tables':[{'database':'app','table':'allowed'}]})
    assert result.status_code==201,result.text
    assert result.json()['password']==password
    assert result.headers['cache-control']=='no-store, private'
    assert any("CREATE USER 'new_user'@'%'" in sql for sql in state['remote'])
    assert password not in str(state['records'])
    assert any("GRANT SELECT ON `app`.`allowed` TO 'new_user'@'%'"==sql for sql in state['remote'])


def test_create_never_overwrites_existing_user(api):
    client,state=api;state['existing']=[{'username':'existing'}]
    response=client.post('/api/admin/database-accounts/1/accounts',json={'username':'existing','tables':[{'database':'app','table':'allowed'}]})
    assert response.status_code==409
    assert not state['records']


def test_failed_grant_rolls_back_only_new_user_and_redacts_errors(api):
    client,state=api;state['fail_grant']=True
    response=client.post('/api/admin/database-accounts/1/accounts',json={'username':'new_user','tables':[{'database':'app','table':'allowed'}]})
    assert response.status_code==502 and 'secret' not in response.text
    assert "DROP USER 'new_user'@'%'" in state['remote']
    assert state['row']['status']=='failed'


@pytest.mark.parametrize('override',[
    {'username':"x';DROP USER root;--"},{'password':'secret'},{'expires_days':0},{'expires_days':1.2},
    {'source_identity':"'root'@'%'"},{'tables':[]},
])
def test_invalid_input_never_reaches_source_or_echoes_password(api,override):
    client,state=api
    response=client.post('/api/admin/database-accounts/1/accounts',json={'username':'new_user','tables':[{'database':'app','table':'allowed'}],**override})
    assert response.status_code==422 and 'secret' not in response.text
    assert not state['remote']


def test_expiry_refuses_recreated_account_marker(monkeypatch):
    monkeypatch.setattr(remote,'query',lambda *args:[{'marker':'different-owner'}])
    with pytest.raises(remote.AccountError):remote.verify_managed_account(None,'mysql',"'old'@'%'",1)


def test_success_is_idempotent_and_mismatched_retry_is_rejected(api):
    from uuid import uuid4
    client,state=api
    payload={'operation_id':str(uuid4()),'username':'new_user','tables':[{'database':'app','table':'allowed'}]}
    first=client.post('/api/admin/database-accounts/1/accounts',json=payload)
    assert first.status_code==201 and first.json()['created']
    calls=len(state['remote'])
    retry=client.post('/api/admin/database-accounts/1/accounts',json=payload)
    assert retry.status_code==200 and retry.json()['created']
    assert len(state['remote'])==calls
    assert client.post('/api/admin/database-accounts/1/accounts',json={**payload,'username':'another'}).status_code==409
    result=client.get('/api/admin/database-accounts/operations/'+payload['operation_id'])
    assert result.json()['password']==first.json()['password']


def test_privilege_verification_failure_never_reports_success(api,monkeypatch):
    client,state=api
    def fail(*args):raise remote.AccountError('scope mismatch')
    monkeypatch.setattr(remote,'verify_grants',fail)
    result=client.post('/api/admin/database-accounts/1/accounts',json={'username':'new_user','tables':[{'database':'app','table':'allowed'}]})
    assert result.status_code==502 and state['row']['status']=='failed'
    assert not management.operation_result(state['row'])['created']


def test_unknown_result_preserves_operation_and_never_reexecutes_create(api,monkeypatch):
    from uuid import uuid4
    client,state=api;state['fail_grant']=True
    def disconnected(*args):raise OSError('source not reachable')
    monkeypatch.setattr(management,'rollback_operation',disconnected)
    payload={'operation_id':str(uuid4()),'username':'new_user','tables':[{'database':'app','table':'allowed'}]}
    result=client.post('/api/admin/database-accounts/1/accounts',json=payload)
    assert result.status_code==502 and state['row']['status']=='uncertain'
    calls=len(state['remote'])
    retry=client.post('/api/admin/database-accounts/1/accounts',json=payload)
    assert retry.status_code==202 and not retry.json()['created']
    assert 'password' not in retry.json() and len(state['remote'])==calls


def test_normalization_preserves_sql_identifiers():
    assert remote.canonical_grants(['GRANT SELECT, INSERT ON `app`.`a b` TO `u`'])==remote.canonical_grants(['GRANT SELECT,INSERT ON `app`.`a b` TO `u`'])
    assert remote.canonical_grants(['GRANT SELECT ON `app`.`a b` TO `u`'])!=remote.canonical_grants(['GRANT SELECT ON `app`.`ab` TO `u`'])


def test_source_capability_preflight_prevents_all_mutations(api,monkeypatch):
    client,state=api
    monkeypatch.setattr(remote,'capabilities',lambda *args:{'can_manage':False})
    result=client.post('/api/admin/database-accounts/1/accounts',json={'username':'new_user','tables':[{'database':'app','table':'allowed'}]})
    assert result.status_code==403 and not state['records']
    assert not any(x.startswith('CREATE') for x in state['remote'])


def test_external_connections_are_reused_and_capacity_is_bounded(monkeypatch):
    created=[]
    class Connection:
        def rollback(self):pass
        def ping(self,reconnect=False):pass
        def close(self):pass
    def create(**kwargs):
        assert kwargs['connect_timeout']==5 and kwargs['read_timeout']==10
        created.append(kwargs)
        return Connection()
    monkeypatch.setattr(remote.pymysql,'connect',create)
    monkeypatch.setattr(remote,'decrypt_middleware_password',lambda *args:'fixture')
    remote.dispose_pools()
    instance={'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root','password_ciphertext':b'x','password_nonce':b'y'}
    try:
        with remote.connect(instance) as first:original=first.dbapi_connection
        with remote.connect(instance) as second:assert second.dbapi_connection is original
        assert len(created)==1
        pool=next(iter(remote._pools.values()))[0]
        assert pool.size()==2 and pool._max_overflow==0
    finally:remote.dispose_pools()


def test_password_record_does_not_override_native_expiry(api,monkeypatch):
    client,state=api
    expiry={'state':'scheduled','expires_at':'2026-09-16T03:16:03+00:00','lifetime_seconds':604800,'source':'mysql:user'}
    state['existing']=[{'username':'reader','host':'%','user_identity':"'reader'@'%'",'password_expiry':expiry}]
    instance={'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root'}
    cipher,nonce=management._encrypt_password('fixture',management.aad(1,"'reader'@'%'"))
    record={'user_identity':"'reader'@'%'",'middleware_instance_id':1,'instance_fingerprint':remote.fingerprint(instance),
        'status':'recorded','updated_at':management.now(),'expires_at':None,'last_error':None,'password_ciphertext':cipher,'password_nonce':nonce}
    monkeypatch.setattr(management,'execute_queries',lambda statements:([record],[],[]))
    result=client.get('/api/admin/database-accounts/1/accounts')
    assert result.status_code==200,result.text
    account=result.json()['items'][0]
    assert account['password_expiry']==expiry
    assert account['account_expires_at'] is None and account['expires_at'] is None
    assert account['password']=='fixture'


def test_recreated_account_does_not_inherit_deleted_accounts_password_or_deadline(api,monkeypatch):
    client,state=api
    state['existing']=[{'username':'reader','host':'%','user_identity':"'reader'@'%'",'password_expiry':{'state':'never'}}]
    instance={'middleware_type':'mysql','base_url':'mysql://fixture:3306','username':'root'}
    cipher,nonce=management._encrypt_password('old-password',management.aad(1,"'reader'@'%'"))
    record={'user_identity':"'reader'@'%'",'middleware_instance_id':1,'instance_fingerprint':remote.fingerprint(instance),
        'status':'deleted','updated_at':management.now(),'expires_at':management.now(),'last_error':None,'password_ciphertext':cipher,'password_nonce':nonce}
    monkeypatch.setattr(management,'execute_queries',lambda statements:([record],[],[]))
    result=client.get('/api/admin/database-accounts/1/accounts');assert result.status_code==200
    account=result.json()['items'][0]
    assert account['status']=='recreated' and account['password'] is None
    assert account['account_expires_at'] is None and account['expires_at'] is None
    assert 'old-password' not in result.text
