"""Explicit development-only mixed grants and live permission editing smoke test."""
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database_accounts as management
from app import database_account_client as remote
from app.db import execute_query


def main():
    if sys.argv[1:]!=['--development-only']:raise SystemExit('Requires --development-only')
    app=FastAPI();app.include_router(management.build_database_account_router(lambda:{'user':{'id':1}}))
    with TestClient(app) as client:
        for instance_id,url in [(6,'mysql://125.46.107.44:9030'),(7,'mysql://8.130.29.241:8306')]:
            instance=management.instance_for(instance_id);assert instance['base_url']==url
            kind=instance['middleware_type'];suffix=secrets.token_hex(4)
            schemas=[f'infraops_mix_{suffix}_{char}' for char in 'abc']
            a,b,c=schemas;user='qa_mix_'+suffix;identity="'"+user+"'@'%'";created_schemas=[];account_created=False
            base=f'/api/admin/database-accounts/{instance_id}'
            try:
                with remote.connect(instance) as connection:
                    for database in schemas:
                        remote.query(connection,'CREATE DATABASE '+remote.identifier(database));created_schemas.append(database)
                        for table in ('d','e','f'):
                            sql=f'CREATE TABLE {remote.identifier(database)}.{remote.identifier(table)} (id INT, content VARCHAR(40))'
                            if kind=='doris':sql+=' UNIQUE KEY(id) DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES("replication_num"="1","enable_unique_key_merge_on_write"="true")'
                            remote.query(connection,sql)
                payload={'username':user,'operation_id':str(uuid4()),'tables':[
                    {'database':a,'table':None,'access':'read'}, {'database':b,'table':None,'access':'read'},
                    {'database':c,'table':'d','access':'write'}, {'database':c,'table':'f','access':'write'}]}
                result=client.post(base+'/accounts',json=payload)
                assert result.status_code==201,result.text
                account_created=True;password=result.json()['password']
                info=client.get(base+'/permissions',params={'user_identity':identity});assert info.status_code==200,info.text
                current=info.json();assert current['editable'],current
                assert sorted((x['database'],x['table'] or '*',x['access']) for x in current['tables'])==sorted((x['database'],x['table'] or '*',x['access']) for x in payload['tables'])
                def access(database,table,write=False,allowed=True):
                    address=urlsplit(url)
                    connection=pymysql.connect(host=address.hostname,port=address.port,user=user,password=password,autocommit=True,connect_timeout=5,read_timeout=10)
                    try:
                        with connection.cursor() as cursor:
                            sql=f'INSERT INTO {remote.identifier(database)}.{remote.identifier(table)} VALUES (1,\'mock\')' if write else f'SELECT * FROM {remote.identifier(database)}.{remote.identifier(table)}'
                            try:cursor.execute(sql);cursor.fetchall()
                            except pymysql.Error:
                                if allowed:raise
                            else:assert allowed,(database,table,'unexpected access',write)
                    finally:connection.close()
                for database in (a,b):
                    for table in ('d','e','f'):access(database,table);access(database,table,write=True,allowed=False)
                for table in ('d','f'):access(c,table);access(c,table,write=True)
                access(c,'e',allowed=False)
                # Whole-database scope includes tables created after the grant.
                with remote.connect(instance) as connection:
                    remote.query(connection,f'CREATE TABLE {remote.identifier(a)}.`new_table` LIKE {remote.identifier(a)}.`d`')
                access(a,'new_table');access(a,'new_table',write=True,allowed=False)
                edit={'operation_id':str(uuid4()),'user_identity':identity,'revision':current['revision'],'tables':[
                    {'database':a,'table':None,'access':'write'},
                    {'database':c,'table':'d','access':'read'}, {'database':c,'table':'e','access':'write'}]}
                result=client.put(base+'/permissions',json=edit);assert result.status_code==200 and result.json()['updated'],result.text
                access(a,'d',write=True);access(b,'d',allowed=False);access(c,'d');access(c,'d',write=True,allowed=False)
                access(c,'e',write=True);access(c,'f',allowed=False)
                retry=client.put(base+'/permissions',json=edit);assert retry.status_code==200 and retry.json()['updated']
                stale=client.put(base+'/permissions',json={**edit,'operation_id':str(uuid4())});assert stale.status_code==409
                current=client.get(base+'/permissions',params={'user_identity':identity}).json()
                empty=client.put(base+'/permissions',json={'operation_id':str(uuid4()),'user_identity':identity,'revision':current['revision'],'tables':[]})
                assert empty.status_code==200 and empty.json()['updated'],empty.text
                assert client.get(base+'/permissions',params={'user_identity':identity}).json()['tables']==[]
                for database in schemas:access(database,'d',allowed=False)
                print(json.dumps({'engine':kind,'checks':['mixed two whole databases read and two tables write','future table read','upgrade','downgrade','remove','add','empty revoke','idempotent retry','stale revision rejection','password unchanged'],'result':'passed'}),flush=True)
            finally:
                with remote.connect(instance) as connection:
                    if account_created:remote.query(connection,'DROP USER '+remote.identity(connection,user,'%'))
                    for database in created_schemas:remote.query(connection,'DROP DATABASE '+remote.identifier(database))
                management.write('DELETE FROM database_permission_operations WHERE middleware_instance_id=%s AND user_identity=%s',(instance_id,identity))
                management.write('DELETE FROM database_managed_accounts WHERE middleware_instance_id=%s AND user_identity=%s',(instance_id,identity))
                print(json.dumps({'engine':kind,'cleanup':'done','schemas':created_schemas,'user':user}),flush=True)
    remote.dispose_pools()


if __name__=='__main__':main()
