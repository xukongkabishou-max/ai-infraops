import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import value_access as access
from app import nacos_value_selection as selection

NACOS_SOURCE = '# internal comment\n\npassword: secret\nother: must-stay-hidden\n'


def submit_ranges(client, source, expression="18-26，36-57"):
    document = selection.parse_config_document(source, "yaml", selection.selection_scope(1, "", "DEFAULT_GROUP", "app.yaml", "yaml"))
    payload = dict(category="nacos", instance_id=1, namespace_id="", group="DEFAULT_GROUP", data_id="app.yaml",
        config_type="yaml", config_revision=document.revision, line_ranges=expression)
    return client.post("/api/value-requests", json=payload)


def test_multi_range_workflow_maps_exact_source_and_preserves_isolation(system, monkeypatch):
    client, db, current, _ = system
    source = '# private comment\n\nroot:\n' + ''.join(f'  key{i}: test-value-{i}\n\n# private comment\n' for i in range(1,61))
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: source)
    result = submit_ranges(client, source)
    assert result.status_code == 201, result.text
    request_id = result.json()['id']
    path = f'/api/value-requests/{request_id}'
    detail = client.get(path)
    assert 'test-value-' not in detail.text
    assert detail.json()['items'][0]['target']['scope_version'] == 2
    assert client.get(path+'/value').status_code == 403
    assert client.post(f'/api/admin/value-requests/{request_id}/review', json={'decision':'approved'}).status_code == 200
    expected_numbers = list(range(18,27)) + list(range(36,58))
    expected = [{'line_number':n,'config_path':f'/root/key{n-1}','source_line':4+(n-2)*3,
        'source_end_line':4+(n-2)*3,'value':f'test-value-{n-1}'} for n in expected_numbers]
    for endpoint in (path+'/value', f'/api/admin/value-requests/{request_id}/value'):
        result = client.get(endpoint)
        assert result.status_code == 200
        assert result.json()['snapshot']['values'] == expected
        assert 'value' not in result.json()['snapshot']
        assert result.headers['cache-control'] == 'no-store, private'
    current['user'] = 3
    assert client.get(path).status_code == 404
    assert client.get(path+'/value').status_code == 404
    current['user'] = 2
    db.execute('UPDATE value_access_requests SET expires_at=?', (access.now_utc()-timedelta(seconds=1),))
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: (_ for _ in ()).throw(AssertionError('must not fetch history')))
    assert client.get(path+'/value').json()['snapshot']['values'] == expected


@pytest.mark.parametrize('tamper', ['source', 'path', 'original_line', 'range'])
def test_multi_range_approval_refuses_changed_version_or_mapping(system, monkeypatch, tamper):
    client, db, _, _ = system
    result = submit_ranges(client, NACOS_SOURCE, '1')
    assert result.status_code == 201
    request_id = result.json()['id']
    if tamper == 'source':
        monkeypatch.setattr(access, 'fetch_nacos_config_content', lambda *args: '# new comment\n'+NACOS_SOURCE)
    else:
        target = json.loads(db.execute('SELECT target FROM value_access_requests WHERE id=?',(request_id,)).fetchone()[0])
        if tamper == 'path': target['selections'][0]['config_path'] = '/other'
        if tamper == 'original_line': target['selections'][0]['source_line'] += 1
        if tamper == 'range': target['line_ranges'] = '1-2'
        db.execute('UPDATE value_access_requests SET target=? WHERE id=?',(json.dumps(target),request_id))
    result = client.post(f'/api/admin/value-requests/{request_id}/review',json={'decision':'approved'})
    assert result.status_code == 409 and 'secret' not in result.text
    assert db.execute('SELECT status,snapshot_ciphertext FROM value_access_requests WHERE id=?',(request_id,)).fetchone()[:] == ('pending',None)


def test_multi_range_snapshot_cannot_return_added_values(system):
    client, db, _, _ = system
    request_id = submit_ranges(client, NACOS_SOURCE, '1').json()['id']
    assert client.post(f'/api/admin/value-requests/{request_id}/review',json={'decision':'approved'}).status_code == 200
    path = f'/api/value-requests/{request_id}/value'
    snapshot = client.get(path).json()['snapshot']
    snapshot['values'].append({'line_number':2,'config_path':'/other','source_line':4,'source_end_line':4,'value':'must-stay-hidden'})
    ciphertext, nonce = access._encrypt_password(json.dumps(snapshot),access.aad(request_id))
    db.execute('UPDATE value_access_requests SET snapshot_ciphertext=?,snapshot_nonce=? WHERE id=?',(ciphertext,nonce,request_id))
    result = client.get(path)
    assert result.status_code == 410 and 'must-stay-hidden' not in result.text


@pytest.mark.parametrize('expression', ['0', '1~2', '2-1', '40001', '1,,2'])
def test_multi_range_api_rejects_invalid_ranges(system, expression):
    client, db, _, _ = system
    assert submit_ranges(client, NACOS_SOURCE, expression).status_code == 422
    assert db.execute('SELECT COUNT(*) FROM value_access_requests').fetchone()[0] == 0


@pytest.fixture
def system(monkeypatch):
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))
    sqlite3.register_converter("timestamp", lambda value: datetime.fromisoformat(value.decode()))
    db = sqlite3.connect(":memory:", check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    db.executescript("""
      CREATE TABLE rbac_users (id INTEGER PRIMARY KEY, username TEXT, is_active INT, is_superuser INT);
      INSERT INTO rbac_users VALUES (1,'admin',1,1),(2,'alice',1,0),(3,'bob',1,0);
      CREATE TABLE rbac_roles (id INT, is_active INT);
      INSERT INTO rbac_roles VALUES (1,1);
      CREATE TABLE rbac_user_roles (user_id INT,role_id INT);
      INSERT INTO rbac_user_roles VALUES (2,1),(3,1);
      CREATE TABLE rbac_permissions (id INT,code TEXT,is_active INT);
      INSERT INTO rbac_permissions VALUES (1,'k8s:env:list',1),(2,'nacos:config-structure:read',1);
      CREATE TABLE rbac_role_permissions (role_id INT,permission_id INT);
      INSERT INTO rbac_role_permissions VALUES (1,1),(1,2);
      CREATE TABLE infra_environments (id INT,name TEXT,is_active INT);
      INSERT INTO infra_environments VALUES (1,'Test',1);
      CREATE TABLE machine_hosts (id INT,hostname TEXT,environment_id INT,status TEXT);
      INSERT INTO machine_hosts VALUES (1,'test-host',1,'active');
      CREATE TABLE middleware_instances (id INT,environment_id INT,instance_name TEXT,
        middleware_type TEXT,status TEXT,base_url TEXT,username TEXT,password_ciphertext BLOB,password_nonce BLOB);
      INSERT INTO middleware_instances VALUES (1,1,'nacos','nacos','active','http://nacos','nacos',NULL,NULL);
      CREATE TABLE value_access_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, requester_id INT, category TEXT, environment_name TEXT,
        resource_name TEXT,target TEXT,reason TEXT,status TEXT DEFAULT 'pending',reviewer_id INT,
        review_note TEXT DEFAULT '',created_at timestamp,reviewed_at timestamp,captured_at timestamp,
        expires_at timestamp,snapshot_ciphertext BLOB,snapshot_nonce BLOB,
        release_ticket TEXT DEFAULT '',release_version TEXT DEFAULT '');
    """)

    def query(sql, params=None):
        sql = sql.replace("%s", "?").replace("UTC_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
        return db.execute(sql, params or ())

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            self.result = query(sql, params)
        @property
        def lastrowid(self): return self.result.lastrowid
        @property
        def rowcount(self): return self.result.rowcount

    class Connection:
        def cursor(self): return Cursor()
        def commit(self): db.commit()
        def rollback(self): db.rollback()
        def close(self): pass

    monkeypatch.setattr(access, "execute_query", lambda sql, params=None: [dict(row) for row in query(sql, params)])
    monkeypatch.setattr(access, "execute_queries", lambda statements: [[dict(row) for row in query(sql, params)] for sql, params in statements])
    monkeypatch.setattr(access, "get_connection", Connection)
    from app import middleware_crypto
    monkeypatch.setattr(middleware_crypto, "_encryption_key", lambda: b"x" * 32)
    monkeypatch.setattr(selection, "_encryption_key", lambda: b"x" * 32)
    monkeypatch.setattr(access, "decrypt_middleware_password", lambda *args: "source-password")
    calls = []
    def collect(*args, **kwargs):
        calls.append(kwargs)
        return {"key": kwargs["value_key"], "value": "private\nvalue=1", "pod_name": "pod-at-approval", "container_name": "app"}
    monkeypatch.setattr(access, "get_workload_environment_keys", collect)
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: NACOS_SOURCE)
    current = {"user": 2, "admin": 1, "namespace_allowed": True}
    def namespace(*args):
        if not current["namespace_allowed"]:
            raise HTTPException(403, "namespace denied")
    app = FastAPI()
    app.include_router(access.build_value_access_router(
        lambda: {"user": {"id": current["user"]}}, lambda: {"user": {"id": current["admin"]}},
        lambda *args, **kwargs: {}, namespace))
    with TestClient(app) as client:
        yield client, db, current, calls
    db.close()


def submit(client, category="environment"):
    target = dict(host_id=1, namespace="test", kind="Deployment", workload="app", container="app", key="TEST_KEY") if category == "environment" else dict(instance_id=1, namespace_id="", group="DEFAULT_GROUP", data_id="app.yaml")
    if category == "nacos":
        document = selection.parse_config_document(NACOS_SOURCE, "yaml", selection.selection_scope(1, "", "DEFAULT_GROUP", "app.yaml", "yaml"))
        target.update(line_number=1, config_type="yaml", config_revision=document.revision)
    response = client.post("/api/value-requests", json={"category": category, **target})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("category", ["environment", "nacos"])
def test_full_workflow_and_user_isolation(system, category):
    client, db, current, calls = system
    request_id = submit(client, category)
    path = f"/api/value-requests/{request_id}/value"
    assert client.get(path).status_code == 403
    assert not calls
    current["user"] = 3
    assert client.get("/api/value-requests").json()["total"] == 0
    assert client.get(path).status_code == 404
    response = client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    assert response.status_code == 200, response.text
    assert "secret" not in response.text and "private" not in response.text
    assert client.get(path).status_code == 404
    current["user"] = 2
    listing = client.get("/api/value-requests").json()
    assert listing["items"][0]["reason"] == ""
    assert listing["items"][0]["status"] == "approved"
    assert "snapshot_ciphertext" not in listing["items"][0]
    result = client.get(path)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store, private"
    value = result.json()["snapshot"]["value"]
    assert value == ("private\nvalue=1" if category == "environment" else "secret")
    assert "must-stay-hidden" not in result.text
    if category == "nacos":
        assert result.json()["snapshot"]["config_path"] == "/password"
        assert result.json()["snapshot"]["source_line"] == 3
    assert result.json()["captured_at"].endswith("+00:00")
    stored = db.execute("SELECT snapshot_ciphertext FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0]
    assert value.encode() not in stored
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"}).status_code == 409
    current["user"] = 1
    assert client.get(path).status_code == 200


def test_expiry_permission_revocation_and_namespace_revocation(system):
    client, db, current, _ = system
    request_id = submit(client)
    client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    path = f"/api/value-requests/{request_id}/value"
    current["namespace_allowed"] = False
    assert client.get(path).status_code == 200
    current["namespace_allowed"] = True
    db.execute("UPDATE rbac_roles SET is_active=0")
    assert client.get(path).status_code == 403
    db.execute("UPDATE rbac_roles SET is_active=1")
    db.execute("UPDATE rbac_users SET is_active=0 WHERE id=2")
    assert client.get(path).status_code == 403
    db.execute("UPDATE rbac_users SET is_active=1 WHERE id=2")
    db.execute("UPDATE value_access_requests SET expires_at=?", (access.now_utc()-timedelta(seconds=1),))
    assert client.get(path).status_code == 200
    assert client.get("/api/value-requests").json()["items"][0]["status"] == "expired"
    assert client.get("/api/admin/value-requests?status=expired").json()["total"] == 1


def test_rejection_and_admin_authorization(system):
    client, db, current, calls = system
    request_id = submit(client)
    review_path = f"/api/admin/value-requests/{request_id}/review"
    current["admin"] = 3
    assert client.get("/api/admin/value-requests").status_code == 403
    assert client.post(review_path, json={"decision": "approved"}).status_code == 403
    current["admin"] = 1
    current["user"] = 1
    own_id = submit(client)
    assert client.post(f"/api/admin/value-requests/{own_id}/review", json={"decision": "approved"}).status_code == 403
    current["user"] = 2
    assert client.post(review_path, json={"decision": "rejected", "note": "not needed"}).status_code == 200
    assert client.get(f"/api/value-requests/{request_id}/value").status_code == 403
    assert not calls
    assert db.execute("SELECT snapshot_ciphertext FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0] is None


def test_failed_capture_is_retryable_and_does_not_leak(system, monkeypatch):
    client, _, _, _ = system
    request_id = submit(client)
    def fail(*args, **kwargs): raise ValueError("secret database password")
    monkeypatch.setattr(access, "get_workload_environment_keys", fail)
    result = client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    assert result.status_code == 502 and "secret" not in result.text
    assert client.get("/api/value-requests").json()["items"][0]["status"] == "pending"


def test_validation_and_snapshot_binding(system):
    client, db, _, _ = system
    response = client.post("/api/value-requests", json={"category": "environment", "reason": "debug", "requester_id": 3})
    assert response.status_code == 422
    request_id = submit(client)
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved", "validity_minutes": 0}).status_code == 422
    client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    ciphertext, nonce = access._encrypt_password(json.dumps({"value": "swapped"}), access.aad(request_id+1))
    db.execute("UPDATE value_access_requests SET snapshot_ciphertext=?,snapshot_nonce=? WHERE id=?", (ciphertext, nonce, request_id))
    assert client.get(f"/api/value-requests/{request_id}/value").status_code == 503


def test_concurrent_review_cannot_overwrite_first_decision(system, monkeypatch):
    client, db, _, _ = system
    request_id = submit(client)
    def collect(*args, **kwargs):
        db.execute("UPDATE value_access_requests SET status='rejected' WHERE id=?", (request_id,))
        db.commit()
        return {"value": "must not be saved"}
    monkeypatch.setattr(access, "get_workload_environment_keys", collect)
    result = client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    assert result.status_code == 409
    assert client.get("/api/value-requests").json()["items"][0]["status"] == "rejected"
    assert db.execute("SELECT snapshot_ciphertext FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0] is None


def test_nacos_requires_line_and_current_preview(system):
    client, _, _, _ = system
    target = dict(category="nacos", instance_id=1, namespace_id="", group="DEFAULT_GROUP", data_id="app.yaml")
    assert client.post("/api/value-requests", json=target).status_code == 422
    assert client.post("/api/value-requests", json={**target, "line_number":1, "config_type":"yaml", "config_revision":"0"*64}).status_code == 409
    document = selection.parse_config_document(NACOS_SOURCE, "yaml", selection.selection_scope(1, "", "DEFAULT_GROUP", "app.yaml", "yaml"))
    assert client.post("/api/value-requests", json={**target, "line_number":99, "config_type":"yaml", "config_revision":document.revision}).status_code == 409


def test_changed_nacos_or_tampered_path_cannot_be_approved(system, monkeypatch):
    client, db, _, _ = system
    request_id = submit(client, "nacos")
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: '# another comment\n'+NACOS_SOURCE)
    response = client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision":"approved"})
    assert response.status_code == 409
    assert "secret" not in response.text
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: NACOS_SOURCE)
    raw = db.execute("SELECT target FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0]
    target = json.loads(raw)
    target["config_path"] = "/other"
    db.execute("UPDATE value_access_requests SET target=? WHERE id=?", (json.dumps(target),request_id))
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision":"approved"}).status_code == 409
    assert db.execute("SELECT snapshot_ciphertext FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0] is None


def test_legacy_whole_config_authorization_is_blocked(system):
    client, db, _, _ = system
    request_id = submit(client, "nacos")
    target = json.loads(db.execute("SELECT target FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0])
    del target["scope_version"]
    db.execute("UPDATE value_access_requests SET target=? WHERE id=?", (json.dumps(target),request_id))
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision":"approved"}).status_code == 409
    db.execute("UPDATE value_access_requests SET status='approved' WHERE id=?", (request_id,))
    assert client.get(f"/api/value-requests/{request_id}/value").status_code == 410
    assert client.get("/api/value-requests").json()["items"][0]["status"] == "invalidated"


def test_nacos_snapshot_binding_prevents_whole_file_fallback(system):
    client, db, _, _ = system
    request_id = submit(client, "nacos")
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision":"approved"}).status_code == 200
    ciphertext, nonce = access._encrypt_password(json.dumps({"value":NACOS_SOURCE}), access.aad(request_id))
    db.execute("UPDATE value_access_requests SET snapshot_ciphertext=?,snapshot_nonce=? WHERE id=?", (ciphertext,nonce,request_id))
    result = client.get(f"/api/value-requests/{request_id}/value")
    assert result.status_code == 410 and "secret" not in result.text


@pytest.mark.parametrize("category", ["environment", "nacos"])
def test_direct_link_detail_is_visible_only_to_owner_or_live_administrator(system, category):
    client, db, current, _ = system
    request_id = submit(client, category)
    path = f"/api/value-requests/{request_id}"
    result = client.get(path)
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store, private'
    assert result.json()['items'][0]['requester_name'] == 'alice'
    assert not result.json()['items'][0]['can_review']
    current['user'] = 3
    assert client.get(path).status_code == 404
    assert client.get(path+'?user=alice').status_code == 404
    assert client.post(path+'/review', json={'decision':'approved'}).status_code == 403
    current['user'] = 1
    assert client.get(path).json()['items'][0]['can_review']
    assert client.post(path+'/review', json={'decision':'approved'}).status_code == 200
    detail = client.get(path).json()['items'][0]
    assert not detail['can_review'] and detail['can_view_value']
    assert 'snapshot_ciphertext' not in detail and 'private' not in json.dumps(detail)
    assert client.get(path+'/value').status_code == 200
    current['user'] = 2
    assert client.get(path).json()['items'][0]['can_view_value']
    db.execute('UPDATE rbac_users SET is_active=0 WHERE id=2')
    assert client.get(path).status_code == 403


def test_release_context_and_detail_path_are_preserved(system):
    client, _, _, _ = system
    result = client.post('/api/value-requests', json={
        'category':'environment','host_id':1,'namespace':'test','workload':'app',
        'container':'app','key':'TEST_KEY','release_ticket':'REL-2026-019','release_version':'abc1234',
    })
    assert result.status_code == 201
    request_id = result.json()['id']
    assert result.json()['detail_path'] == f'/approvals/{request_id}'
    item = client.get(f'/api/value-requests/{request_id}').json()['items'][0]
    assert item['release_ticket'] == 'REL-2026-019' and item['release_version'] == 'abc1234'
    assert client.get('/api/value-requests/999999').status_code == 404


def test_detail_link_cannot_self_approve_or_reuse_revoked_administrator(system):
    client, db, current, _ = system
    current['user'] = 1
    request_id = submit(client)
    assert not client.get(f'/api/value-requests/{request_id}').json()['items'][0]['can_review']
    assert client.post(f'/api/value-requests/{request_id}/review', json={'decision':'approved'}).status_code == 403
    current['user'] = 2
    other = submit(client)
    current['user'] = 1
    db.execute('UPDATE rbac_users SET is_superuser=0 WHERE id=1')
    assert client.get(f'/api/value-requests/{other}').status_code == 404
    assert client.post(f'/api/value-requests/{other}/review', json={'decision':'approved'}).status_code == 403


@pytest.mark.parametrize("category", ["environment", "nacos"])
def test_expired_snapshots_remain_immutable_for_owner_and_administrator(system, monkeypatch, category):
    client, db, current, _ = system
    request_id = submit(client, category)
    assert client.post(f'/api/admin/value-requests/{request_id}/review', json={'decision':'approved'}).status_code == 200
    original = client.get(f'/api/value-requests/{request_id}/value').json()
    db.execute('UPDATE value_access_requests SET expires_at=? WHERE id=?', (access.now_utc()-timedelta(days=3), request_id))
    current['namespace_allowed'] = False
    db.execute("UPDATE machine_hosts SET status='disabled'")
    db.execute("UPDATE middleware_instances SET status='disabled'")
    def forbidden(*args, **kwargs): raise AssertionError('Historical reads must not fetch source values')
    monkeypatch.setattr(access,'get_workload_environment_keys',forbidden)
    monkeypatch.setattr(access,'fetch_nacos_config_content',forbidden)
    result = client.get(f'/api/value-requests/{request_id}/value')
    assert result.status_code == 200
    assert result.json()['snapshot'] == original['snapshot']
    assert result.json()['captured_at'] == original['captured_at']
    assert result.json()['historical']
    admin_result = client.get(f'/api/admin/value-requests/{request_id}/value')
    assert admin_result.status_code == 200 and admin_result.json()['snapshot'] == original['snapshot']
    current['user'] = 3
    assert client.get(f'/api/value-requests/{request_id}/value').status_code == 404
    current['admin'] = 3
    assert client.get(f'/api/admin/value-requests/{request_id}/value').status_code == 403
    current['admin'] = 1
    assert 'snapshot_ciphertext' not in client.get('/api/admin/value-requests').text


def test_history_dates_include_whole_local_days_and_preserve_owner_filters(system):
    client, db, current, _ = system
    ids = [submit(client) for _ in range(4)]
    timestamps = [datetime(2026,9,7,15,59,59), datetime(2026,9,7,16),
                  datetime(2026,9,8,15,59,59,999999),datetime(2026,9,8,16)]
    for request_id, timestamp in zip(ids,timestamps):
        db.execute('UPDATE value_access_requests SET created_at=? WHERE id=?',(timestamp,request_id))
    query = '?date_from=2026-09-08&date_to=2026-09-08'
    rows = client.get('/api/value-requests'+query).json()
    assert rows['total'] == 2
    assert [row['id'] for row in rows['items']] == [ids[2],ids[1]]
    assert client.get('/api/admin/value-requests'+query).json()['total'] == 2
    current['user'] = 3
    assert client.get('/api/value-requests'+query).json()['total'] == 0
    assert client.get('/api/value-requests?date_from=2026-09-09&date_to=2026-09-08').status_code == 422
    assert client.get('/api/admin/value-requests?date_from=invalid').status_code == 422


def test_history_search_category_status_and_pagination(system):
    client, db, _, _ = system
    for _ in range(21): submit(client)
    nacos = submit(client,'nacos')
    assert client.get('/api/value-requests?category=environment').json()['total'] == 21
    assert len(client.get('/api/value-requests?category=environment&page=2').json()['items']) == 1
    assert client.get('/api/value-requests?keyword=TEST_KEY').json()['total'] == 21
    assert client.get('/api/value-requests?keyword=%25').json()['total'] == 0
    db.execute('UPDATE value_access_requests SET release_ticket=? WHERE id=?',('REL_100%',nacos))
    assert client.get('/api/admin/value-requests?keyword=REL_100%25').json()['total'] == 1
    assert client.get('/api/value-requests?status=rejected').json()['total'] == 0
    client.post(f'/api/admin/value-requests/{nacos}/review',json={'decision':'rejected'})
    assert client.get('/api/value-requests?category=nacos&status=rejected').json()['total'] == 1
    assert client.get(f'/api/admin/value-requests/{nacos}/value').status_code == 403


def test_reviewer_can_read_own_history_without_current_source_permission(system):
    client, db, _, _ = system
    request_id = submit(client)
    assert client.post(f'/api/admin/value-requests/{request_id}/review',json={'decision':'approved'}).status_code == 200
    db.execute('INSERT INTO rbac_roles VALUES (2,1)')
    db.execute("INSERT INTO rbac_permissions VALUES (3,'admin:console:access',1),(4,'value:approve',1)")
    db.execute('INSERT INTO rbac_role_permissions VALUES (2,3),(2,4)')
    db.execute('UPDATE rbac_user_roles SET role_id=2 WHERE user_id=2')
    assert client.get(f'/api/value-requests/{request_id}').json()['items'][0]['can_view_value']
    assert client.get(f'/api/value-requests/{request_id}/value').status_code == 200
