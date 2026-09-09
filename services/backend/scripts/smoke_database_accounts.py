"""Opt-in integration test: only registered development instances 6 and 7, isolated objects."""
import json
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database_accounts as management
from app import database_account_client as remote
from app.db import execute_query


def main():
    if sys.argv[1:] != ['--development-only']:
        raise SystemExit('Use --development-only to run this explicitly isolated test')
    operator = {'user':{'id':1,'username':'admin','isSuperuser':True}}
    app=FastAPI()
    app.include_router(management.build_database_account_router(lambda:operator))
    suffix=secrets.token_hex(4)
    schema='infraops_qa_'+suffix
    schema_two=schema+'_second'
    try:
      with TestClient(app) as client:
        for instance_id,address in [(6,'mysql://125.46.107.44:9030'),(7,'mysql://8.130.29.241:8306')]:
            instance=management.instance_for(instance_id)
            assert instance['base_url']==address, 'Development target changed; refusing test'
            kind=instance['middleware_type'];base=f'/api/admin/database-accounts/{instance_id}'
            usernames=[];records=[];role='qa_role_'+suffix
            role_created=False;schemas_created=[]
            try:
                with remote.connect(instance) as connection:
                    for database in [schema,schema_two]:
                        remote.query(connection,'CREATE DATABASE '+remote.identifier(database));schemas_created.append(database)
                        for table in ['allowed','denied','role_table']:
                            sql='CREATE TABLE '+remote.identifier(database)+'.'+remote.identifier(table)+' (id INT, content VARCHAR(40))'
                            if kind=='doris':sql+=' UNIQUE KEY(id) DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES("replication_num"="1","enable_unique_key_merge_on_write"="true")'
                            remote.query(connection,sql)
                    remote.query(connection,'CREATE ROLE '+remote.identifier(role));role_created=True
                for mode in ['read','clone','write','multi_read','multi_write']:
                    username='qa_'+suffix+'_'+mode
                    writable='write' in mode
                    selected=[schema,schema_two] if mode.startswith('multi') else [schema]
                    payload={'username':username,'tables':[{'database':database,'table':'allowed'} for database in selected],
                        'access':'write' if writable else 'read','expires_days':None if mode=='read' else 1}
                    if mode=='clone':payload={'username':username,'source_identity':source_identity,'expires_days':1}
                    payload['operation_id']=str(uuid4())
                    if mode=='write':payload['password']="Qa!7%_zX"
                    result=client.post(base+'/accounts',json=payload)
                    assert result.status_code==201,(kind,mode,result.text)
                    data=result.json();usernames.append(username)
                    record_id=execute_query('SELECT id FROM database_managed_accounts WHERE middleware_instance_id=%s AND user_identity=%s',(instance_id,data['user_identity']))[0]['id'];records.append(record_id)
                    if mode=='read':
                        source_identity=data['user_identity']
                        with remote.connect(instance) as connection:
                            obj=('`internal`.' if kind=='doris' else '')+remote.identifier(schema)+'.`role_table`'
                            role_sql=connection.escape(role) if kind=='doris' else remote.identifier(role)
                            remote.query(connection,f'GRANT {"SELECT_PRIV" if kind=="doris" else "SELECT"} ON {obj} TO {"ROLE " if kind=="doris" else ""}'+role_sql)
                            remote.query(connection,f'GRANT {role_sql} TO {source_identity}')
                            if kind=='mysql':remote.query(connection,f'SET DEFAULT ROLE {remote.identifier(role)} TO {source_identity}')
                    with remote.connect(instance) as connection:
                        remote.verify_managed_account(connection,kind,data['user_identity'],record_id)
                    url=urlsplit(address)
                    connection=pymysql.connect(host=url.hostname,port=url.port,user=username,password=data['password'],connect_timeout=5,read_timeout=10,autocommit=True)
                    try:
                        with connection.cursor() as cursor:
                            for database in selected:
                                cursor.execute(f'SELECT * FROM {remote.identifier(database)}.`allowed`');cursor.fetchall()
                            if mode=='clone':cursor.execute(f'SELECT * FROM {remote.identifier(schema)}.`role_table`');cursor.fetchall()
                            for database in [schema,schema_two]:
                                try:cursor.execute(f'SELECT * FROM {remote.identifier(database)}.`denied`')
                                except pymysql.Error:pass
                                else:raise AssertionError('Unexpected access to unselected table')
                            for database in selected:
                                try:cursor.execute(f"INSERT INTO {remote.identifier(database)}.`allowed` VALUES (1,'fixture')")
                                except pymysql.Error:
                                    assert not writable,'Writer could not write'
                                else:assert writable,'Reader could write'
                                if writable:
                                    cursor.execute(f"UPDATE {remote.identifier(database)}.`allowed` SET content='updated' WHERE id=1")
                                    cursor.execute(f'DELETE FROM {remote.identifier(database)}.`allowed` WHERE id=1')
                    finally:connection.close()
                    listing=client.get(base+'/accounts',params={'keyword':username}).json()
                    assert listing['items'][0]['password']==data['password']
                    saved=client.put(base+'/password-record',json={'user_identity':data['user_identity'],'password':data['password']})
                    assert saved.status_code==200,saved.text
                    assert client.get(base+'/accounts',params={'keyword':username}).json()['items'][0]['password']==data['password']
                    assert bool(listing['items'][0]['expires_at'])==(mode!='read')
                    assert len(data['password'])==8
                    retry=client.post(base+'/accounts',json=payload)
                    assert retry.status_code==200 and retry.json()['created'] and retry.json()['operation_id']==data['operation_id']
                    result=client.get('/api/admin/database-accounts/operations/'+data['operation_id'])
                    assert result.status_code==200 and result.json()['created']
                    duplicate=client.post(base+'/accounts',json={**payload,'operation_id':str(uuid4())})
                    assert duplicate.status_code==409
                    if mode=='multi_write':
                        management.write('UPDATE database_managed_accounts SET expires_at=%s WHERE id=%s',(management.now()-timedelta(seconds=1),record_id))
                        management.expire_due_accounts()
                        assert execute_query('SELECT status FROM database_managed_accounts WHERE id=%s',(record_id,))[0]['status']=='expired'
                        try:pymysql.connect(host=url.hostname,port=url.port,user=username,password=data['password'],connect_timeout=5,read_timeout=5)
                        except pymysql.Error:pass
                        else:raise AssertionError('Expired account could still log in')
                print(json.dumps({'engine':kind,'result':'passed','checks':['create','clone direct and role grants','reader isolation','writer','password record','expiry denies login','existing account protected']}),flush=True)
            finally:
                with remote.connect(instance) as connection:
                    for username in usernames:
                        remote.query(connection,'DROP USER '+remote.identity(connection,username,'%'))
                    if role_created:remote.query(connection,'DROP ROLE '+remote.identifier(role))
                    for database in schemas_created:remote.query(connection,'DROP DATABASE '+remote.identifier(database))
                for record_id in records:
                    management.write('DELETE FROM database_managed_accounts WHERE id=%s',(record_id,))
                management.write("DELETE FROM database_managed_accounts WHERE middleware_instance_id=%s AND user_identity LIKE %s AND status='failed'",(instance_id,"'qa_"+suffix+"_%"))
                print(json.dumps({'engine':kind,'cleanup':'completed','schema':schema}),flush=True)
    finally:
      remote.dispose_pools()


if __name__=='__main__':main()
