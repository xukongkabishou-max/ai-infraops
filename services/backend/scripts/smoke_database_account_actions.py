"""Validate disable/delete against isolated development users and a mock table only."""
import json
import secrets
import sys
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
    if sys.argv[1:]!=['--development-only']:raise SystemExit('Requires --development-only')
    app=FastAPI();app.include_router(management.build_database_account_router(lambda:{'user':{'id':1}}))
    with TestClient(app) as client:
        for instance_id,url in [(6,'mysql://125.46.107.44:9030'),(7,'mysql://8.130.29.241:8306')]:
            instance=management.instance_for(instance_id);assert instance['base_url']==url
            kind=instance['middleware_type'];suffix=secrets.token_hex(4);schema='infraops_life_'+suffix
            created_schema=False;identities=[];base=f'/api/admin/database-accounts/{instance_id}'
            try:
                with remote.connect(instance) as c:
                    remote.query(c,'CREATE DATABASE '+remote.identifier(schema));created_schema=True
                    sql='CREATE TABLE '+remote.identifier(schema)+'.`mock` (id INT)'
                    if kind=='doris':sql+=' DUPLICATE KEY(id) DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES("replication_num"="1")'
                    remote.query(c,sql)
                for mode in ('disable_delete','delete_active'):
                    username='qa_life_'+suffix+('_a' if mode=='disable_delete' else '_b');identity="'"+username+"'@'%'"
                    result=client.post(base+'/accounts',json={'username':username,'tables':[{'database':schema,'table':'mock','access':'read'}]})
                    assert result.status_code==201,result.text
                    identities.append(identity);password=result.json()['password'];address=urlsplit(url)
                    def login():
                        c=pymysql.connect(host=address.hostname,port=address.port,user=username,password=password,connect_timeout=5,read_timeout=5,autocommit=True)
                        try:
                            with c.cursor() as q:q.execute(f'SELECT * FROM {remote.identifier(schema)}.`mock`');q.fetchall()
                        finally:c.close()
                    login()
                    if mode=='disable_delete':
                        preview=client.get(base+'/accounts/action-preview',params={'user_identity':identity});assert preview.status_code==200,preview.text
                        data={'operation_id':str(uuid4()),'action':'disable','user_identity':identity,'confirm_identity':identity,'revision':preview.json()['revision']}
                        assert client.post(base+'/accounts/actions',json={**data,'confirm_identity':"'wrong'@'%'"}).status_code==422
                        assert client.post(base+'/accounts/actions',json={**data,'revision':'0'*64}).status_code==409
                        result=client.post(base+'/accounts/actions',json=data);assert result.status_code==200 and result.json()['confirmed'],result.text
                        try:login()
                        except pymysql.Error:pass
                        else:raise AssertionError('Disabled account accepted a new login')
                        listing=client.get(base+'/accounts',params={'keyword':username});assert listing.status_code==200,listing.text
                        row=listing.json()['items'][0];assert row['password']==password and row['status']=='disabled',row['status']
                        assert client.post(base+'/accounts/actions',json=data).json()['confirmed']
                    preview=client.get(base+'/accounts/action-preview',params={'user_identity':identity});assert preview.status_code==200
                    data={'operation_id':str(uuid4()),'action':'delete','user_identity':identity,'confirm_identity':identity,'revision':preview.json()['revision']}
                    result=client.post(base+'/accounts/actions',json=data);assert result.status_code==200 and result.json()['confirmed'],result.text
                    assert client.get(base+'/accounts',params={'keyword':username}).json()['total']==0
                    assert client.post(base+'/accounts/actions',json=data).json()['confirmed']
                    assert client.get('/api/admin/database-accounts/account-actions/'+data['operation_id']).json()['confirmed']
                    with remote.connect(instance) as c:remote.query(c,f'SELECT * FROM {remote.identifier(schema)}.`mock`')
                root=client.get(base+'/accounts/action-preview',params={'user_identity':"'root'@'%'"});assert root.status_code==200 and root.json()['protected']
                rejected=client.post(base+'/accounts/actions',json={'action':'delete','user_identity':"'root'@'%'",'confirm_identity':"'root'@'%'",'revision':root.json()['revision']})
                assert rejected.status_code==403
                print(json.dumps({'engine':kind,'result':'passed','checks':['confirmation mismatch rejected','stale preview rejected','disable blocks login','password record retained','delete disabled and active user','absence verified','idempotent retry','root protected','mock table preserved']}),flush=True)
            finally:
                with remote.connect(instance) as c:
                    existing={row['user_identity'] for row in remote.accounts(c,kind)}
                    for identity in identities:
                        if identity in existing:remote.query(c,'DROP USER '+identity)
                    if created_schema:remote.query(c,'DROP DATABASE '+remote.identifier(schema))
                for identity in identities:
                    management.write('DELETE FROM database_account_action_operations WHERE middleware_instance_id=%s AND user_identity=%s',(instance_id,identity))
                    management.write('DELETE FROM database_managed_accounts WHERE middleware_instance_id=%s AND user_identity=%s',(instance_id,identity))
                print(json.dumps({'engine':kind,'cleanup':'done','schema':schema}),flush=True)
    remote.dispose_pools()


if __name__=='__main__':main()
