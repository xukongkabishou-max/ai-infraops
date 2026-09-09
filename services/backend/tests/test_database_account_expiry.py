from datetime import datetime, timezone

import pymysql

from app.database_account_expiry import expiry_metadata, mysql_expiry, populate_doris_expiries


def test_mysql_explicit_default_never_and_forced_expiration():
    row={'password_changed_epoch':1788900000,'server_epoch':1788900001,'password_lifetime':7,'default_lifetime':0,'password_expired':'N'}
    result=mysql_expiry(row)
    assert result['state']=='scheduled' and result['lifetime_seconds']==604800 and result['source']=='mysql:user'
    assert mysql_expiry({**row,'password_lifetime':None,'default_lifetime':7})['source']=='mysql:global-default'
    assert mysql_expiry({**row,'password_lifetime':0})['state']=='never'
    assert mysql_expiry({**row,'password_lifetime':0,'password_expired':'Y'})['state']=='expired'
    assert mysql_expiry({**row,'server_epoch':1788900000+604800})['state']=='expired'


def test_missing_policy_or_timestamp_is_unknown_not_permanent():
    assert expiry_metadata(None)['state']=='unknown'
    assert expiry_metadata(604800,None)['state']=='unknown'
    assert expiry_metadata(604800,0)['state']=='unknown'
    assert mysql_expiry({})['state']=='unknown'


def test_doris_rd_tmp_epoch_conversion_and_policy_does_not_leak_history():
    account={'user_identity':"'rd_tmp'@'%'"}
    calls=[]
    start=int(datetime(2026,9,9,3,16,3,tzinfo=timezone.utc).timestamp())
    def query(c,sql,params=None):
        calls.append((sql,params))
        if sql.startswith('SHOW PROC'):
            return [{'Key':'password_policy.expiration_seconds','Value':'604800'},
                {'Key':'password_policy.password_creation_time','Value':'2026-09-09 11:16:03'},
                {'Key':'password_policy.history_passwords','Value':'sensitive-hash'}]
        assert params==('2026-09-09 11:16:03',)
        return [{'server_epoch':start+60,'default_days':0,'created_0':start}]
    populate_doris_expiries(None,[account],query)
    assert account['password_expiry']['expires_at']=='2026-09-16T03:16:03+00:00'
    assert 'sensitive-hash' not in str(account)
    assert calls[0][1]==("/auth/'rd_tmp'@'%'",)


def test_doris_batch_uses_each_identity_and_distinguishes_unknown_from_never():
    rows=[{'user_identity':"'same'@'%'"},{'user_identity':"'same'@'localhost'"},{'user_identity':"'legacy'@'%'"}]
    def query(c,sql,params=None):
        if sql.startswith('SHOW PROC'):
            if 'localhost' in params[0]:return [{'Key':'password_policy.expiration_seconds','Value':'NEVER'}]
            if 'legacy' in params[0]:raise pymysql.ProgrammingError(1227,'denied')
            return [{'Key':'password_policy.expiration_seconds','Value':'DEFAULT'},
                {'Key':'password_policy.password_creation_time','Value':'2026-09-09 11:16:03'}]
        return [{'server_epoch':1000000,'default_days':7,'created_0':100}]
    populate_doris_expiries(None,rows,query)
    assert [row['password_expiry']['state'] for row in rows]==['expired','never','unknown']
    assert rows[0]['password_expiry']['source']=='doris:global-default'
