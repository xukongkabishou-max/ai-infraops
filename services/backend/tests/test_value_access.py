import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import value_access as access


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
        expires_at timestamp,snapshot_ciphertext BLOB,snapshot_nonce BLOB);
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
    monkeypatch.setattr(access, "get_connection", Connection)
    from app import middleware_crypto
    monkeypatch.setattr(middleware_crypto, "_encryption_key", lambda: b"x" * 32)
    monkeypatch.setattr(access, "decrypt_middleware_password", lambda *args: "source-password")
    calls = []
    def collect(*args, **kwargs):
        calls.append(kwargs)
        return {"key": kwargs["value_key"], "value": "private\nvalue=1", "pod_name": "pod-at-approval", "container_name": "app"}
    monkeypatch.setattr(access, "get_workload_environment_keys", collect)
    monkeypatch.setattr(access, "fetch_nacos_config_content", lambda *args: "password: secret\n")
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
    assert value == ("private\nvalue=1" if category == "environment" else "password: secret\n")
    assert result.json()["captured_at"].endswith("+00:00")
    stored = db.execute("SELECT snapshot_ciphertext FROM value_access_requests WHERE id=?", (request_id,)).fetchone()[0]
    assert value.encode() not in stored
    assert client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"}).status_code == 409
    current["user"] = 1
    assert client.get(path).status_code == 404


def test_expiry_permission_revocation_and_namespace_revocation(system):
    client, db, current, _ = system
    request_id = submit(client)
    client.post(f"/api/admin/value-requests/{request_id}/review", json={"decision": "approved"})
    path = f"/api/value-requests/{request_id}/value"
    current["namespace_allowed"] = False
    assert client.get(path).status_code == 403
    current["namespace_allowed"] = True
    db.execute("UPDATE rbac_roles SET is_active=0")
    assert client.get(path).status_code == 403
    db.execute("UPDATE rbac_roles SET is_active=1")
    db.execute("UPDATE rbac_users SET is_active=0 WHERE id=2")
    assert client.get(path).status_code == 403
    db.execute("UPDATE rbac_users SET is_active=1 WHERE id=2")
    db.execute("UPDATE value_access_requests SET expires_at=?", (access.now_utc()-timedelta(seconds=1),))
    assert client.get(path).status_code == 410
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
