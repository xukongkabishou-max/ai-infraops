import sqlite3
from datetime import datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from passlib.context import CryptContext

from app import middleware_crypto, session_store, user_passwords


@pytest.fixture
def system(monkeypatch):
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))
    sqlite3.register_converter("timestamp", lambda value: datetime.fromisoformat(value.decode()))
    db = sqlite3.connect(":memory:", check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE rbac_users (id INTEGER PRIMARY KEY,username TEXT,password_hash TEXT,
        is_active INT,is_superuser INT,auth_version INT DEFAULT 0,password_ciphertext BLOB,
        password_nonce BLOB,password_changed_at timestamp)""")
    context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=4)
    old_hash = context.hash("old-password")
    db.executemany("INSERT INTO rbac_users (id,username,password_hash,is_active,is_superuser) VALUES (?,?,?,?,?)",
                   [(1,"admin",old_hash,1,1),(2,"developer",old_hash,1,0),(3,"another-root",old_hash,1,1),(4,"ops",old_hash,1,0)])
    db.commit()

    def query(sql, params=None):
        return db.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), params or ())

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None): self.result = query(sql, params)
        def fetchall(self): return [dict(row) for row in self.result.fetchall()]
        def fetchone(self):
            row = self.result.fetchone()
            return dict(row) if row else None

    class Connection:
        def cursor(self): return Cursor()
        def commit(self): db.commit()
        def rollback(self): db.rollback()
        def close(self): pass

    class Redis:
        def __init__(self): self.values = {}
        def get(self, key): return self.values.get(key)
        def setex(self, key, ttl, value): self.values[key] = value
        def expire(self, key, ttl): pass
        def delete(self, key): self.values.pop(key, None)

    redis = Redis()
    monkeypatch.setattr(user_passwords, "get_connection", Connection)
    monkeypatch.setattr(middleware_crypto, "_encryption_key", lambda: b"k" * 32)
    monkeypatch.setattr(session_store, "get_redis_client", lambda: redis)
    monkeypatch.setattr(session_store, "execute_query", lambda sql, params=None: [dict(row) for row in query(sql, params)])
    audit = Mock()
    monkeypatch.setattr(user_passwords, "record_audit_event", audit)
    actor = {"id":1, "version":0}
    app = FastAPI()
    app.include_router(user_passwords.build_user_password_router(
        lambda: {"user":{"id":actor["id"],"username":"admin","isSuperuser":True},"_auth_version":actor["version"]}, context))
    with TestClient(app) as client:
        yield client, db, actor, context, audit
    db.close()


def reset(client, user_id=2, password="new-private-password"):
    return client.put(f"/api/rbac/users/{user_id}/password", json={"new_password":password,"confirm_password":password})


def test_admin_resets_hash_and_encrypted_record_without_leaking(system):
    client, db, _, context, audit = system
    response = reset(client)
    assert response.status_code == 200 and response.json()["sessions_invalidated"]
    assert not response.json()["reauthenticate"]
    assert "new-private-password" not in response.text and "password_hash" not in response.text
    row = db.execute("SELECT * FROM rbac_users WHERE id=2").fetchone()
    assert context.verify("new-private-password", row["password_hash"])
    assert not context.verify("old-password", row["password_hash"])
    assert b"new-private-password" not in row["password_ciphertext"]
    assert row["auth_version"] == 1
    result = client.get("/api/rbac/users/2/password")
    assert result.status_code == 200 and result.json()["password"] == "new-private-password"
    assert result.headers["cache-control"] == "no-store, private"
    assert result.json()["changed_at"].endswith("+00:00")
    assert [call.kwargs["action"] for call in audit.call_args_list] == ["user_password_reset", "user_password_view"]
    assert "new-private-password" not in str(audit.call_args_list)


def test_live_identity_controls_reset_and_plaintext_visibility(system):
    client, db, actor, _, _ = system
    actor["id"] = 4
    assert reset(client).status_code == 403
    assert client.get("/api/rbac/users/2/password").status_code == 403
    actor["id"] = 3
    assert reset(client).status_code == 200
    assert client.get("/api/rbac/users/2/password").status_code == 403
    assert reset(client, 1).status_code == 403
    actor["id"] = 1
    db.execute("UPDATE rbac_users SET is_superuser=0 WHERE id=1")
    db.commit()
    assert reset(client).status_code == 403
    assert client.get("/api/rbac/users/2/password").status_code == 403


def test_admin_can_change_own_password_and_must_reauthenticate(system):
    client, _, actor, _, _ = system
    result = reset(client, 1)
    assert result.status_code == 200 and result.json()["reauthenticate"]
    assert reset(client, 1).status_code == 401
    assert client.get("/api/rbac/users/1/password").status_code == 401
    actor["version"] = 1
    assert client.get("/api/rbac/users/1/password").json()["password"] == "new-private-password"


def test_sessions_from_both_clients_and_racing_old_login_are_invalidated(system):
    client, _, _, _, _ = system
    for kind in ("user_web", "backend_admin_web"):
        session_store.save_session(kind, "old", {"user":{"id":2}})
        assert session_store.load_session(kind, "old")
    session_store.save_session("user_web", "unrelated", {"user":{"id":4}})
    assert reset(client).status_code == 200
    for kind in ("user_web", "backend_admin_web"):
        assert session_store.load_session(kind, "old") is None
        session_store.save_session(kind, "racing", {"user":{"id":2},"_auth_version":0})
        assert session_store.load_session(kind, "racing") is None
        session_store.save_session(kind, "new", {"user":{"id":2},"_auth_version":1})
        assert session_store.load_session(kind, "new")
    assert session_store.load_session("user_web", "unrelated")


@pytest.mark.parametrize("payload", [
    {"new_password":"private-sentinel","confirm_password":"different"},
    {"new_password":"private-sentinel"},
    {"new_password":" ","confirm_password":" "},
    {"new_password":"中"*25,"confirm_password":"中"*25},
    {"new_password":"x"*73,"confirm_password":"x"*73},
    {"new_password":{"secret":"private-sentinel"},"confirm_password":"x"},
])
def test_invalid_password_errors_do_not_echo_submitted_secrets(system, payload):
    client, db, _, _, _ = system
    result = client.put("/api/rbac/users/2/password", json=payload)
    assert result.status_code == 422
    assert "private-sentinel" not in result.text and '"input"' not in result.text
    assert db.execute("SELECT auth_version FROM rbac_users WHERE id=2").fetchone()[0] == 0


def test_hash_only_and_outdated_records_do_not_display_incorrect_passwords(system):
    client, db, _, context, _ = system
    assert client.get("/api/rbac/users/2/password").json()["password"] is None
    reset(client)
    db.execute("UPDATE rbac_users SET password_hash=? WHERE id=2", (context.hash("externally-changed"),))
    result = client.get("/api/rbac/users/2/password")
    assert not result.json()["available"] and result.json()["password"] is None


def test_crypto_failure_rolls_back_and_aad_prevents_record_swapping(system, monkeypatch):
    client, db, _, _, _ = system
    def fail(*args): raise RuntimeError("sensitive encryption detail")
    with monkeypatch.context() as scoped:
        scoped.setattr(user_passwords, "_encrypt_password", fail)
        result = reset(client)
        assert result.status_code == 503 and "sensitive" not in result.text
        assert db.execute("SELECT auth_version FROM rbac_users WHERE id=2").fetchone()[0] == 0
    reset(client)
    row = db.execute("SELECT password_hash,password_ciphertext,password_nonce FROM rbac_users WHERE id=2").fetchone()
    db.execute("UPDATE rbac_users SET password_hash=?,password_ciphertext=?,password_nonce=? WHERE id=4", tuple(row))
    assert client.get("/api/rbac/users/4/password").status_code == 503


def test_password_bytes_preserve_spaces_and_disabled_targets_remain_disabled(system):
    client, db, _, context, _ = system
    db.execute("UPDATE rbac_users SET is_active=0 WHERE id=2")
    value = " " + "中" * 23 + "  "
    assert len(value.encode()) == 72
    assert reset(client, password=value).status_code == 200
    row = db.execute("SELECT password_hash,is_active FROM rbac_users WHERE id=2").fetchone()
    assert row["is_active"] == 0 and context.verify(value, row["password_hash"])
    assert client.get("/api/rbac/users/2/password").json()["password"] == value


def test_session_load_uses_current_superuser_flag_and_disables_deleted_accounts(system):
    _, db, _, _, _ = system
    session_store.save_session("backend_admin_web", "admin", {"user":{"id":1,"isSuperuser":True}})
    db.execute("UPDATE rbac_users SET is_superuser=0 WHERE id=1")
    assert not session_store.load_session("backend_admin_web", "admin")["user"]["isSuperuser"]
    db.execute("UPDATE rbac_users SET is_active=0 WHERE id=1")
    assert session_store.load_session("backend_admin_web", "admin") is None
    session_store.save_session("user_web", "removed", {"user":{"id":4}})
    db.execute("DELETE FROM rbac_users WHERE id=4")
    db.commit()
    assert session_store.load_session("user_web", "removed") is None
