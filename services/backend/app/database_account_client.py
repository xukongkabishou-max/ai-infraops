"""Bounded connections and engine-specific account operations; no application table writes."""
import hashlib
import json
import re
import secrets
import string
from contextlib import contextmanager
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

import pymysql
import sqlparse
from sqlparse import tokens as sql_tokens
from sqlalchemy.dialects.mysql.pymysql import MySQLDialect_pymysql
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import TimeoutError as PoolTimeout

from .middleware_crypto import decrypt_middleware_password
from .mysql_client import _parse_user_identity, _map_account_row as mysql_account
from .doris_client import _map_account_row as doris_account
from .database_account_expiry import mysql_expiry


class AccountError(ValueError):
    pass


_pools = {}
_pool_lock = Lock()
_dialect = MySQLDialect_pymysql(dbapi=pymysql)
SYSTEM_DATABASES = {'mysql', 'information_schema', 'performance_schema', 'sys', '__internal_schema'}


def fingerprint(instance):
    return hashlib.sha256(json.dumps([instance['middleware_type'], instance['base_url']], separators=(',', ':')).encode()).hexdigest()


def generate_password(length=8):
    groups = (string.ascii_uppercase, string.ascii_lowercase, string.digits, '!@#$%_+-')
    characters = [secrets.choice(group) for group in groups]
    characters += [secrets.choice(''.join(groups)) for _ in range(length - len(groups))]
    secrets.SystemRandom().shuffle(characters)
    return ''.join(characters)


def identifier(value):
    if not value or len(value) > 255 or any(char in value for char in ('\0', '\n', '\r')):
        raise AccountError('数据库对象名称无效')
    return '`' + value.replace('`', '``') + '`'


def identity(connection, user, host):
    return connection.escape(user) + '@' + connection.escape(host)


@contextmanager
def connect(instance):
    secret = decrypt_middleware_password(instance['password_ciphertext'], instance['password_nonce'])
    key = hashlib.sha256((fingerprint(instance) + instance['username'] + '\0' + secret).encode()).digest()
    now = monotonic()
    with _pool_lock:
        for stale, (old_pool, used) in list(_pools.items()):
            if now - used > 300 and old_pool.checkedout() == 0:
                old_pool.dispose()
                del _pools[stale]
        if key not in _pools:
            if len(_pools) >= 24:
                raise AccountError('数据库连接池繁忙，请稍后重试')
            address = urlsplit(instance['base_url'])
            if address.scheme != 'mysql' or not address.hostname or not address.port:
                raise AccountError('实例连接地址无效')
            def creator():
                return pymysql.connect(host=address.hostname, port=address.port,
                    user=instance['username'], password=secret, charset='utf8mb4',
                    connect_timeout=5, read_timeout=10, write_timeout=10, autocommit=True,
                    cursorclass=pymysql.cursors.DictCursor)
            _pools[key] = (QueuePool(creator, pool_size=2, max_overflow=0, timeout=3,
                recycle=120, pre_ping=True, dialect=_dialect, use_lifo=True), now)
        pool, _ = _pools[key]
        _pools[key] = (pool, now)
    lease = None
    try:
        lease = pool.connect()
        yield lease
    except PoolTimeout:
        raise AccountError('此实例正在处理其他操作，请稍后重试') from None
    except (pymysql.Error, OSError) as exc:
        if lease is not None and _dialect.is_disconnect(exc, lease.dbapi_connection, None):
            lease.invalidate()
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else 0
        raise AccountError(f'数据库操作失败（错误码 {code}），请检查管理权限、网络或账号状态') from None
    finally:
        if lease is not None:
            lease.close()


def dispose_pools():
    with _pool_lock:
        for pool, _ in _pools.values():
            pool.dispose()
        _pools.clear()


def query(connection, sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def accounts(connection, kind):
    if kind == 'mysql':
        rows = query(connection, '''SELECT User,Host,plugin,account_locked,password_expired,
            password_lifetime,@@global.default_password_lifetime AS default_lifetime,
            UNIX_TIMESTAMP(password_last_changed) AS password_changed_epoch,UNIX_TIMESTAMP() AS server_epoch
            FROM mysql.user ORDER BY User,Host''')
        results = []
        for row in rows:
            item = mysql_account(row)
            item['password_expiry']=mysql_expiry(row)
            item['native_expires_at']=item['password_expiry']['expires_at']
            item['locked'] = row['account_locked'] == 'Y'
            results.append(item)
        return results
    return [doris_account(row) for row in query(connection, 'SHOW ALL GRANTS')]


def databases(connection):
    return sorted(str(next(iter(row.values()))) for row in query(connection, 'SHOW DATABASES')
        if str(next(iter(row.values()))) not in SYSTEM_DATABASES)


def capabilities(connection, kind):
    current = str(next(iter(query(connection,'SELECT CURRENT_USER()')[0].values())))
    rows = query(connection, 'SHOW GRANTS')
    if kind == 'doris':
        privileges = str(rows[0].get('GlobalPrivs') or '').upper() if rows else ''
        capable = 'ADMIN_PRIV' in privileges or 'GRANT_PRIV' in privileges
    else:
        roles = query(connection,'SELECT CURRENT_ROLE() AS roles')[0]['roles']
        if roles and roles != 'NONE':
            rows = query(connection,'SHOW GRANTS FOR CURRENT_USER() USING '+roles)
        grants = [str(next(iter(row.values()))).upper() for row in rows]
        capable = any(' ON *.* TO ' in grant and ' WITH GRANT OPTION' in grant for grant in grants)
        capable = capable and any('CREATE USER' in grant or 'ALL PRIVILEGES' in grant for grant in grants)
    return {'current_user':current,'can_manage':capable,
        'message':'' if capable else '当前数据库管理账号缺少全局授权能力；请配置具备 CREATE USER 和 GRANT OPTION 的 MySQL 账号，或具备 ADMIN_PRIV 的 Doris 账号'}


def tables(connection, database):
    if database in SYSTEM_DATABASES:
        raise AccountError('不能选择系统数据库')
    return sorted(str(next(iter(row.values()))) for row in query(connection, 'SHOW TABLES FROM ' + identifier(database)))


def doris_grants(row, destination, quote):
    statements = []
    scopes = {'GlobalPrivs':None, 'CatalogPrivs':1, 'DatabasePrivs':2, 'TablePrivs':3,
        'ResourcePrivs':'RESOURCE', 'WorkloadGroupPrivs':'WORKLOAD GROUP'}
    for column, value in row.items():
        if column.endswith('Privs') and column not in scopes and value not in (None, '', 'NULL'):
            raise AccountError('此账号包含暂不支持自动克隆的权限类型：' + column)
    for column, dimensions in scopes.items():
        value = row.get(column)
        if not value or value == 'NULL':
            continue
        entries = [('', value)] if column == 'GlobalPrivs' else [part.rsplit(': ', 1) for part in value.split('; ')]
        for scope, privileges in entries:
            tokens = [token.strip().upper() for token in privileges.split(',')]
            if not all(re.fullmatch(r'[A-Z_]+_PRIV', token) for token in tokens):
                raise AccountError('无法准确解析源账号权限，已停止克隆')
            if dimensions is None:
                obj = '*.*.*'
            elif isinstance(dimensions, int):
                parts = scope.split('.')
                if len(parts) != dimensions:
                    raise AccountError('源账号权限对象存在歧义，已停止克隆')
                obj = '.'.join('*' if part == '*' else identifier(part) for part in parts + ['*'] * (3-dimensions))
            else:
                obj = dimensions + ' ' + quote(scope)
            statements.append(f"GRANT {','.join(tokens)} ON {obj} TO {destination}")
    for role in (row.get('Roles') or '').split(','):
        if role.strip():
            statements.append(f'GRANT {quote(role.strip())} TO {destination}')
    return statements


def clone_plan(connection, kind, source, destination):
    try:
        user, host = _parse_user_identity(source)
    except RuntimeError:
        raise AccountError('暂不支持自动克隆该账号标识，请使用普通 user@host 账号') from None
    source_sql = identity(connection, user, host)
    rows = query(connection, f'SHOW GRANTS FOR {source_sql}')
    if not rows:
        raise AccountError('源账号不存在')
    if kind == 'doris':
        return doris_grants(rows[0], destination, connection.escape)
    plans = []
    # SHOW GRANTS output is server-generated; replace only its final grantee, never SQL object names.
    source_patterns = [source_sql, identifier(user)+'@'+identifier(host)]
    for row in rows:
        grant = str(next(iter(row.values())))
        if not grant.startswith(('GRANT ', 'REVOKE ')):
            raise AccountError('源账号包含无法克隆的授权语句')
        replacement = None
        for spelling in source_patterns:
            pattern = r'( TO | FROM )' + re.escape(spelling) + r'( WITH (?:GRANT|ADMIN) OPTION)?$'
            replacement, count = re.subn(pattern, lambda m: m[1]+destination+(m[2] or ''), grant)
            if count:
                break
        else:
            raise AccountError('无法准确匹配源账号授权，已停止克隆')
        plans.append(replacement)
    roles = query(connection, 'SELECT DEFAULT_ROLE_USER,DEFAULT_ROLE_HOST FROM mysql.default_roles WHERE USER=%s AND HOST=%s',(user,host))
    if roles:
        plans.append('SET DEFAULT ROLE ' + ','.join(identity(connection,row['DEFAULT_ROLE_USER'],row['DEFAULT_ROLE_HOST']) for row in roles) + ' TO ' + destination)
    return plans


def canonical_grants(statements):
    result = set()
    for statement in statements:
        if statement.startswith('GRANT USAGE ON '):
            continue
        tokens = []
        for token in sqlparse.parse(statement)[0].flatten():
            if token.is_whitespace:
                continue
            tokens.append(token.value.upper() if token.ttype in sql_tokens.Keyword else token.value)
        # A server may merge grants on the same scope or reorder privilege names.
        if tokens and tokens[0] == 'GRANT' and 'ON' in tokens and '(' not in tokens[:tokens.index('ON')]:
            split = tokens.index('ON')
            privileges = ' '.join(tokens[1:split]).split(',')
            result.update(('GRANT', privilege.strip(), *tokens[split:]) for privilege in privileges)
        else:
            result.add(tuple(tokens))
    return result


def verify_grants(connection, kind, destination, expected):
    actual = clone_plan(connection, kind, destination, destination)
    if canonical_grants(actual) != canonical_grants(expected):
        raise AccountError('账号权限回查与目标不一致，不能确认创建成功')


def table_plan(connection, kind, selected, mode, destination, allow_ddl=False):
    available = {}
    statements = []
    choices = {}
    mysql_literal_scopes = None
    for item in selected:
        key = (item.database, item.table)
        access = getattr(item, 'access', None) or mode
        if key in choices and choices[key] != access:
            raise AccountError('同一库表不能同时指定两种权限')
        choices[key] = access
    for (database, table), access in sorted(choices.items(), key=lambda item:(item[0][0],item[0][1] or '')):
        effective_access = 'write' if allow_ddl else access
        privileges = ('SELECT' if effective_access == 'read' else 'SELECT,INSERT,UPDATE,DELETE') if kind == 'mysql' else ('SELECT_PRIV' if effective_access == 'read' else 'SELECT_PRIV,LOAD_PRIV')
        if table is None:
            if database in SYSTEM_DATABASES or database not in databases(connection):
                raise AccountError('所选数据库不存在或属于系统库')
            if kind == 'mysql' and mysql_literal_scopes is None:
                mysql_literal_scopes = bool(query(connection,'SELECT @@partial_revokes AS enabled')[0]['enabled'])
        else:
            if database not in available:
                available[database] = set(tables(connection, database))
            if table not in available[database]:
                raise AccountError('所选表已不存在，请刷新库表列表')
        inherited = choices.get((database,None)) if table is not None else None
        if inherited == 'write' and access == 'read':
            raise AccountError('整库已授权读写，无法把其中一张表限制为只读；请改用逐表授权')
        if inherited == access:
            continue
        scope_database = database
        if kind == 'mysql' and table is None and not mysql_literal_scopes:
            scope_database = database.replace('\\','\\\\').replace('_',r'\_').replace('%',r'\%')
        obj = ('`internal`.' if kind == 'doris' else '') + identifier(scope_database) + '.' + (identifier(table) if table is not None else '*')
        statements.append(f'GRANT {privileges} ON {obj} TO {destination}')
    if allow_ddl:
        ddl = 'CREATE,ALTER,DROP,CREATE TEMPORARY TABLES' if kind=='mysql' else 'CREATE_PRIV,ALTER_PRIV,DROP_PRIV'
        for database in sorted({item.database for item in selected}):
            if database in SYSTEM_DATABASES or database not in databases(connection):
                raise AccountError('所选数据库不存在或属于系统库')
            scope=('`internal`.' if kind=='doris' else '')+identifier(database)+'.*'
            statements.append(f'GRANT {ddl} ON {scope} TO {destination}')
    return statements


def global_plan(kind, mode, destination, allow_ddl=False):
    if mode not in ('read','write'):
        raise AccountError('全库权限类型无效')
    privileges = ('SELECT,INSERT,UPDATE,DELETE' if allow_ddl or mode=='write' else 'SELECT') if kind=='mysql' else ('SELECT_PRIV,LOAD_PRIV' if allow_ddl or mode=='write' else 'SELECT_PRIV')
    if allow_ddl: privileges += ',CREATE,ALTER,DROP,CREATE TEMPORARY TABLES' if kind=='mysql' else ',CREATE_PRIV,ALTER_PRIV,DROP_PRIV'
    return [f'GRANT {privileges} ON {"*.*" if kind=="mysql" else "*.*.*"} TO {destination}']


def verify_managed_account(connection, kind, user_identity, record_id):
    user, host = _parse_user_identity(user_identity)
    marker = f'infraops-managed:{record_id}'
    if kind == 'mysql':
        rows = query(connection,"SELECT JSON_UNQUOTE(JSON_EXTRACT(User_attributes,'$.metadata.comment')) AS marker FROM mysql.user WHERE User=%s AND Host=%s",(user,host))
        actual = rows[0]['marker'] if rows else None
    else:
        rows = query(connection,'SHOW GRANTS FOR '+identity(connection,user,host))
        actual = rows[0].get('Comment') if rows else None
    if actual != marker:
        raise AccountError('数据库账号标记已变化，停止自动到期操作')


def expire_account(connection, kind, user_identity):
    user, host = _parse_user_identity(user_identity)
    destination = identity(connection, user, host)
    if kind == 'mysql':
        query(connection, f'ALTER USER {destination} ACCOUNT LOCK')
    else:
        # Doris 2.1 has ACCOUNT_UNLOCK but no explicit ACCOUNT_LOCK. Destroy a fresh random
        # credential to prevent future authentication; keep the recorded password as history.
        query(connection, f'SET PASSWORD FOR {destination} = PASSWORD({connection.escape(secrets.token_urlsafe(48))})')
