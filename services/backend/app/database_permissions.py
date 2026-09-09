"""Read current grants and edit explicit database/table read-write permissions."""
import hashlib
import hmac
import json
import re
from collections import defaultdict

from . import database_account_client as remote
from .middleware_crypto import _encryption_key


def split_scope(scope):
    token = r'(?:`(?:``|[^`])+`|\*|[A-Za-z0-9_]+)'
    if not re.fullmatch(token + r'(?:\.' + token + r')+', scope):
        return None
    parts = re.findall(token, scope)
    return [None if part == '*' else part[1:-1].replace('``','`') if part.startswith('`') else part for part in parts]


def unpack(plans, kind):
    groups = defaultdict(set)
    protected = []
    reasons = []
    allowed = {'SELECT','INSERT','UPDATE','DELETE'} if kind == 'mysql' else {'SELECT_PRIV','LOAD_PRIV'}
    for statement in plans:
        match = re.fullmatch(r'GRANT ([A-Z_, ]+) ON (.+) TO (.+?)( WITH GRANT OPTION)?',statement)
        if not match:
            protected.append(statement)
            if not statement.startswith('GRANT USAGE ON '):
                reasons.append('账号包含角色、列级或其他复杂授权，请通过原授权来源维护')
            continue
        privileges = {item.strip() for item in match[1].split(',')}
        scope = split_scope(match[2])
        if privileges == {'USAGE'}:
            protected.append(statement)
            continue
        if scope and kind == 'doris' and len(scope)==3 and scope[0]=='internal':
            scope = scope[1:]
        if scope and len(scope)==2 and scope[0] in remote.SYSTEM_DATABASES:
            protected.append(statement)
        elif scope and len(scope)==2 and scope[0] is not None and privileges <= allowed and not match[4]:
            groups[(scope[0],scope[1])].update(privileges)
        else:
            protected.append(statement)
            # The standard Doris workload group grant is not table access.
            if not (kind=='doris' and match[2].startswith('WORKLOAD GROUP ')):
                reasons.append('账号包含全局、授权转授或非读写权限，不能用简化库表编辑器覆盖')
    return dict(groups), protected, sorted(set(reasons))


def snapshot(connection, instance, user_identity):
    user,host = remote._parse_user_identity(user_identity)
    destination = remote.identity(connection,user,host)
    plans = remote.clone_plan(connection,instance['middleware_type'],destination,destination)
    groups,protected,reasons = unpack(plans,instance['middleware_type'])
    entries = []
    read = {'SELECT'} if instance['middleware_type']=='mysql' else {'SELECT_PRIV'}
    write = {'SELECT','INSERT','UPDATE','DELETE'} if instance['middleware_type']=='mysql' else {'SELECT_PRIV','LOAD_PRIV'}
    for (database,table),privileges in sorted(groups.items(),key=lambda item:(item[0][0],item[0][1] or '')):
        access = 'read' if privileges == read else 'write' if privileges == write else 'custom'
        if access == 'custom':reasons.append('账号存在部分写权限，不能自动替换为完整读写权限')
        display_database=database.replace(r'\_', '_').replace(r'\%','%') if instance['middleware_type']=='mysql' and table is None else database
        entries.append({'database':display_database,'table':table,'access':access,'privileges':sorted(privileges)})
    if user.lower() in ('root','admin') or user == instance['username']:
        reasons.append('数据库管理账号禁止通过简化库表编辑器修改')
    # Bind the account incarnation as well as its grants (MySQL created accounts have attributes).
    if instance['middleware_type']=='mysql':
        marker_rows=remote.query(connection,'SELECT User_attributes FROM mysql.user WHERE User=%s AND Host=%s',(user,host))
        marker=marker_rows[0].get('User_attributes') if marker_rows else None
    else:
        marker=remote.query(connection,'SHOW GRANTS FOR '+destination)[0].get('Comment')
    serialized = json.dumps([remote.fingerprint(instance),destination,marker,sorted(remote.canonical_grants(plans))],ensure_ascii=False)
    revision = hmac.new(_encryption_key(),serialized.encode(),hashlib.sha256).hexdigest()
    return {'user_identity':destination,'tables':entries,'editable':not reasons,'message':'；'.join(sorted(set(reasons))),
        'other_grants':protected,'revision':revision,'plans':plans,'marker':marker}


def public(snapshot):
    return {key:value for key,value in snapshot.items() if key not in ('plans','marker')}


def delta(before,after,kind,destination):
    old,old_extra,old_reasons=unpack(before,kind)
    new,new_extra,new_reasons=unpack(after,kind)
    if old_reasons or new_reasons or remote.canonical_grants(old_extra)!=remote.canonical_grants(new_extra):
        raise remote.AccountError('变更超出简单库表权限范围，已停止')
    commands=[]
    for action in ('REVOKE','GRANT'):
        for database,table in sorted(set(old)|set(new),key=lambda key:(key[0],key[1] or '')):
            previous=old.get((database,table),set());desired=new.get((database,table),set())
            changes=previous-desired if action=='REVOKE' else desired-previous
            if changes:
                scope=('`internal`.' if kind=='doris' else '')+remote.identifier(database)+'.'+(remote.identifier(table) if table is not None else '*')
                commands.append(f"{action} {','.join(sorted(changes))} ON {scope} {'FROM' if action=='REVOKE' else 'TO'} {destination}")
    return commands
