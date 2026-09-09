"""Native password policy metadata, independent of platform account shutdown schedules."""
from datetime import datetime, timezone

import pymysql


def expiry_metadata(lifetime_seconds, created_epoch=None, server_epoch=None, forced_expired=False, source='unknown'):
    result={'state':'unknown','expires_at':None,'lifetime_seconds':lifetime_seconds,'source':source}
    if lifetime_seconds is None or lifetime_seconds < 0:
        return {**result,'state':'expired' if forced_expired else 'unknown'}
    if lifetime_seconds == 0:
        return {**result,'state':'expired' if forced_expired else 'never'}
    if created_epoch is None or float(created_epoch) <= 0:
        return {**result,'state':'expired' if forced_expired else 'unknown'}
    try:
        end=float(created_epoch)+lifetime_seconds
        expires_at=datetime.fromtimestamp(end,timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):
        return result
    expired=forced_expired or (server_epoch is not None and end <= float(server_epoch))
    return {**result,'state':'expired' if expired else 'scheduled','expires_at':expires_at}


def mysql_expiry(row):
    days=row.get('password_lifetime')
    source='mysql:user' if days is not None else 'mysql:global-default'
    if days is None:days=row.get('default_lifetime')
    return expiry_metadata(int(days)*86400 if days is not None else None,
        row.get('password_changed_epoch'),row.get('server_epoch'),
        str(row.get('password_expired','')).upper()=='Y',source)


def populate_doris_expiries(connection, rows, query):
    pending=[]
    for account in rows:
        account['password_expiry']=expiry_metadata(None,source='doris:password-policy')
        # Proc paths identify both the username and Host; do not collapse identities by username.
        if '/' in account['user_identity']:
            continue
        try:
            raw=query(connection,'SHOW PROC %s',('/auth/'+account['user_identity'],))
            policy={row.get('Key'):row.get('Value') for row in raw
                if row.get('Key') in ('password_policy.expiration_seconds','password_policy.password_creation_time')}
            setting=str(policy.get('password_policy.expiration_seconds','')).upper()
            duration=0 if setting=='NEVER' else -1 if setting=='DEFAULT' else int(setting)
            pending.append((account,duration,policy.get('password_policy.password_creation_time') or None))
        except (ValueError,TypeError,pymysql.Error):
            continue
    if not pending:return
    # Let Doris convert its own session-local formatted times to epochs in one round trip.
    try:
        columns=['UNIX_TIMESTAMP() AS server_epoch','@@global.default_password_lifetime AS default_days']
        params=[]
        for index,(_,duration,created) in enumerate(pending):
            if created:
                columns.append(f'UNIX_TIMESTAMP(%s) AS created_{index}')
                params.append(created)
        clock=query(connection,'SELECT '+','.join(columns),tuple(params) if params else None)[0]
    except (pymysql.Error,IndexError,KeyError):
        return
    for index,(account,duration,created) in enumerate(pending):
        source='doris:global-default' if duration==-1 else 'doris:user'
        seconds=int(clock['default_days'])*86400 if duration==-1 and clock.get('default_days') is not None else duration
        account['password_expiry']=expiry_metadata(seconds,clock.get(f'created_{index}'),clock.get('server_epoch'),source=source)
