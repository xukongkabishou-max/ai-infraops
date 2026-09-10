import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import user_management, user_passwords
from test_user_passwords import system as password_system


@pytest.fixture
def system(password_system,monkeypatch):
    _,db,actor,context,audit=password_system
    for column in ('display_name TEXT','email TEXT','added_at timestamp','added_by INT','added_by_name TEXT'):
        db.execute('ALTER TABLE rbac_users ADD COLUMN '+column)
    db.executescript('''CREATE TABLE rbac_roles (id INT PRIMARY KEY,code TEXT,is_active INT);
      INSERT INTO rbac_roles VALUES (1,'rd',1),(2,'super_admin',1);
      CREATE TABLE rbac_user_roles (user_id INT,role_id INT,PRIMARY KEY(user_id,role_id));
      INSERT INTO rbac_user_roles VALUES (1,2),(2,1),(3,2);''')
    base=user_passwords.get_connection
    class Cursor:
        def __init__(self):self.inner=base().cursor()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,*args):return self.inner.execute(*args)
        def fetchone(self):return self.inner.fetchone()
        @property
        def lastrowid(self):return self.inner.result.lastrowid
    class Connection:
        def cursor(self):return Cursor()
        def commit(self):db.commit()
        def rollback(self):db.rollback()
        def close(self):pass
    monkeypatch.setattr(user_management,'get_connection',Connection)
    monkeypatch.setattr(user_management,'record_audit_event',audit)
    app=FastAPI();app.include_router(user_management.build_user_management_router(lambda:{'user':{'id':actor['id']},'_auth_version':actor['version']},context))
    with TestClient(app) as client:yield client,db,actor,context,audit


@pytest.mark.parametrize('role',['rd','super_admin'])
def test_create_generated_password_role_and_creation_attribution(system,role):
    client,db,_,context,audit=system
    result=client.post('/api/rbac/users',json={'username':'new_user','display_name':'New User','role':role})
    assert result.status_code==201,result.text
    data=result.json();password=data['password'];assert len(password)==8
    assert all(re.search(pattern,password) for pattern in ('[A-Z]','[a-z]','[0-9]','[^A-Za-z0-9]'))
    row=db.execute('SELECT * FROM rbac_users WHERE id=?',(data['id'],)).fetchone()
    assert row['added_by']==1 and row['added_by_name']=='admin' and row['added_at']
    assert bool(row['is_superuser'])==(role=='super_admin')
    assert context.verify(password,row['password_hash']) and password.encode() not in row['password_ciphertext']
    assert password not in str(audit.call_args_list)
    assert db.execute('SELECT role_id FROM rbac_user_roles WHERE user_id=?',(data['id'],)).fetchone()[0]==(1 if role=='rd' else 2)
    assert result.headers['cache-control']=='no-store, private'
    assert db.execute('SELECT added_at FROM rbac_users WHERE id=2').fetchone()[0] is None


def test_custom_password_and_edit_preserve_password_and_added_metadata(system):
    client,db,_,context,_=system
    result=client.post('/api/rbac/users',json={'username':'new_user','display_name':'Name','password':'Qa$19%xy','role':'rd'})
    uid=result.json()['id'];before=dict(db.execute('SELECT * FROM rbac_users WHERE id=?',(uid,)).fetchone())
    result=client.put(f'/api/rbac/users/{uid}',json={'username':'renamed','display_name':'Changed','role':'super_admin','is_active':False})
    assert result.status_code==200 and result.json()['sessions_invalidated']
    after=dict(db.execute('SELECT * FROM rbac_users WHERE id=?',(uid,)).fetchone())
    assert after['auth_version']==before['auth_version']+1
    assert not after['is_active'] and after['is_superuser']
    for key in ('password_hash','password_ciphertext','added_at','added_by','added_by_name'):assert before[key]==after[key]


def test_live_admin_identity_and_builtin_admin_protection(system):
    client,db,actor,_,_=system
    for uid in (2,3,4):
        actor['id']=uid
        assert client.post('/api/rbac/users',json={'username':'new_user','display_name':'Name'}).status_code==403
        assert client.put('/api/rbac/users/2',json={'username':'developer','display_name':'Name'}).status_code==403
    actor['id']=1
    for override in ({'role':'rd'},{'is_active':False},{'username':'renamed'}):
        assert client.put('/api/rbac/users/1',json={'username':'admin','display_name':'Admin','role':'super_admin',**override}).status_code==409
    assert db.execute('SELECT is_active,is_superuser FROM rbac_users WHERE id=1').fetchone()[:]==(1,1)


def test_role_failure_rolls_back_and_validation_never_echoes_secrets(system):
    client,db,_,_,_=system
    db.execute("UPDATE rbac_roles SET is_active=0 WHERE code='rd'");db.commit()
    result=client.post('/api/rbac/users',json={'username':'new_user','display_name':'Name','password':'secret!123'})
    assert result.status_code==409 and 'secret!123' not in result.text
    assert db.execute("SELECT COUNT(*) FROM rbac_users WHERE username='new_user'").fetchone()[0]==0
    assert client.post('/api/rbac/users',json={'username':'new_user','display_name':'Name','password':'short'}).status_code==422
